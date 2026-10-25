"""Insight chat: natural-language request -> validated chart spec -> chart.

With an LLM configured, the model writes the spec; otherwise a rule-based
parser does. Either way the spec is validated against the real schema and
executed here in pandas, so numbers always come from the data.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

import numpy as np
import pandas as pd

from .engine import _clean_list, detect_roles, fmt, is_money, pct

CHARTS = {"bar", "line", "area", "scatter", "histogram", "pie", "box", "heatmap", "table", "kpi"}
AGGS = {"sum", "mean", "median", "count", "min", "max", "nunique"}
GRAINS = {"day": "D", "week": "W", "month": "ME", "quarter": "QE", "year": "YE"}


# ---------------------------------------------------------------------------
# rule-based parser
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _find_columns(question: str, columns: list[str]) -> list[str]:
    q = " " + _norm(question) + " "
    exact: list[tuple[int, str]] = []
    covered: set[str] = set()  # words already explained by an exact column match
    for c in columns:
        n = _norm(c)
        for v in (n, n.rstrip("s"), n + "s", n.replace(" ", "")):
            if v and f" {v} " in q:
                exact.append((q.index(f" {v} "), c))
                covered.update(n.split())
                break
    fuzzy: list[tuple[int, str]] = []
    words = q.split()
    for c in columns:
        if any(c == e for _, e in exact):
            continue
        # fuzzy single-word match (e.g. 'charges' -> 'monthly_charges'), but not when the word
        # belongs to a column you named exactly ('seller phone' must not pull in 'seller type')
        parts = _norm(c).split()
        hits = [p for p in parts if p in words and len(p) > 4 and p not in covered]
        if len(parts) > 1 and hits:
            fuzzy.append((min(q.index(f" {p} ") for p in hits) + 1000, c))
    out: list[str] = []
    for _, c in sorted(exact) + sorted(fuzzy):
        if c not in out:
            out.append(c)
    return out


def _find_values(question: str, df: pd.DataFrame, dims: list[str]) -> list[tuple[str, str]]:
    q = " " + _norm(question) + " "
    hits = []
    for d in dims:
        for v in df[d].dropna().astype("string").unique()[:200]:
            nv = _norm(str(v))
            if len(nv) >= 2 and f" {nv} " in q:
                hits.append((d, str(v)))
    return hits


GRAIN_WORDS = {"monthly", "weekly", "daily", "yearly", "quarterly", "month", "week", "day", "year", "quarter", "top", "total"}


def parse_question(question: str, df: pd.DataFrame, roles: dict) -> dict:
    cols = _find_columns(question, list(df.columns))
    # keyword detection runs on the question with column names removed, so a
    # column like 'monthly_charges' doesn't read as "monthly trend"
    q = " " + _norm(question) + " "
    for c in cols:
        q = q.replace(" " + _norm(c) + " ", " ")
    q = q.strip()
    measures = roles["measure"] + roles["flag"] + ([roles["target"]] if roles["target"] else [])
    dims = roles["dimension"] + roles["flag"]
    times = roles["time"]
    m_cols = [c for c in cols if c in measures]
    d_cols = [c for c in cols if c in dims and c not in m_cols]
    t_cols = [c for c in cols if c in times]

    spec: dict[str, Any] = {"chart": None, "x": None, "y": None, "agg": None, "color": None, "time_grain": None,
                            "filters": [], "top_n": None, "sort": None, "title": None}
    if re.search(r"\b(average|avg|mean)\b", q):
        spec["agg"] = "mean"
    elif re.search(r"\b(total|sum|overall)\b", q):
        spec["agg"] = "sum"
    elif re.search(r"\bmedian\b", q):
        spec["agg"] = "median"
    elif re.search(r"how many|count|number of|frequency", q):
        spec["agg"] = "count"
    elif re.search(r"\b(rate|share|percentage|percent|proportion)\b", q):
        spec["agg"] = "mean"
    elif re.search(r"\b(max|maximum|highest)\b", q) and not re.search(r"\bby\b", q):
        spec["agg"] = "max"
    elif re.search(r"\b(min|minimum|lowest)\b", q) and not re.search(r"\bby\b", q):
        spec["agg"] = "min"
    if (m := re.search(r"\btop\s+(\d+)", q)):
        spec["top_n"], spec["sort"] = int(m.group(1)), "desc"
    elif (m := re.search(r"\bbottom\s+(\d+)", q)):
        spec["top_n"], spec["sort"] = int(m.group(1)), "asc"
    if re.search(r"\b(highest|most|best|largest|biggest)\b", q):
        spec["sort"] = "desc"
    if re.search(r"\b(lowest|least|worst|smallest)\b", q):
        spec["sort"] = "asc"
    for g in GRAINS:
        if re.search(rf"\b(by|per|each|every)\s+{g}|{g}ly\b|\b{'dai' if g == 'day' else g}ly\b", q):
            spec["time_grain"] = g
    if re.search(r"\b(trend|over time|timeline|growth|monthly|weekly|daily|yearly|quarterly)\b", q) and times:
        spec["chart"] = "line"
    if re.search(r"distribution|histogram|spread", q):
        spec["chart"] = "histogram"
    if re.search(r"\b(vs|versus|against|relationship|correlat)", q) and len(m_cols) >= 2:
        spec["chart"] = "scatter"
    if re.search(r"\b(pie|donut|composition|breakdown|share of|mix)\b", q):
        spec["chart"] = "pie"
    if re.search(r"\b(box|boxplot|outlier)", q):
        spec["chart"] = "box"
    if re.search(r"heat ?map|cross ?tab|matrix", q):
        spec["chart"] = "heatmap"
    if re.search(r"\btable\b|\blist\b|\bshow me (the )?rows", q):
        spec["chart"] = "table"
    year = re.search(r"\b(?:in|during|for)\s+((?:19|20)\d{2})\b", q)
    if year and times:
        spec["filters"].append({"column": times[0], "op": "year", "value": int(year.group(1))})
    for d, v in _find_values(q, df, [c for c in dims if c not in d_cols[:1]]):
        if _norm(v) in GRAIN_WORDS:
            continue
        spec["filters"].append({"column": d, "op": "==", "value": v})
    by = re.search(r"\b(?:by|per|across|for each|split by|grouped by)\s+([a-z0-9_ ]+)", q)
    by_cols = _find_columns(by.group(1), list(df.columns)) if by else []

    chart = spec["chart"]
    if chart == "scatter":
        spec["x"], spec["y"] = m_cols[0], m_cols[1]
        spec["color"] = d_cols[0] if d_cols else None
    elif chart == "histogram":
        spec["x"] = (m_cols or roles["measure"] or [None])[0]
        spec["color"] = d_cols[0] if d_cols else None
    elif chart == "line" or (t_cols and (m_cols or spec["agg"] == "count")):
        spec["chart"] = chart if chart in ("line", "area") else "line"
        spec["x"] = (t_cols or times)[0]
        spec["y"] = m_cols[0] if m_cols else None
        spec["agg"] = spec["agg"] or ("count" if not m_cols else "sum" if is_money(m_cols[0]) else "mean")
        spec["color"] = d_cols[0] if d_cols and len(d_cols) == 1 else None
    elif chart == "heatmap":
        ds = (d_cols + dims)[:2]
        spec["x"], spec["color"] = ds[0], ds[1] if len(ds) > 1 else None
        spec["y"] = m_cols[0] if m_cols else None
        spec["agg"] = spec["agg"] or ("mean" if m_cols else "count")
    else:
        x = (by_cols and by_cols[0] in dims and by_cols[0]) or (d_cols[0] if d_cols else None)
        if chart == "box":
            spec["x"], spec["y"] = x, (m_cols or roles["measure"] or [None])[0]
        elif x:
            spec["chart"] = chart or "bar"
            spec["x"] = x
            spec["y"] = m_cols[0] if m_cols else None
            spec["agg"] = spec["agg"] or ("count" if not m_cols else "sum" if is_money(m_cols[0]) else "mean")
            rest = [c for c in d_cols if c != x]
            spec["color"] = rest[0] if rest else None
        elif m_cols:
            if spec["agg"] and spec["agg"] != "count":
                spec["chart"], spec["y"] = "kpi", m_cols[0]
            else:
                spec["chart"], spec["x"] = "histogram", m_cols[0]
        elif spec["agg"] == "count":
            spec["chart"] = "kpi"
        else:
            spec["chart"] = None
    return spec


# ---------------------------------------------------------------------------
# validation + execution
# ---------------------------------------------------------------------------

def validate_spec(spec: dict, df: pd.DataFrame) -> tuple[dict, list[str]]:
    errs = []
    s = {k: spec.get(k) for k in ("chart", "x", "y", "agg", "color", "time_grain", "filters", "top_n", "sort", "title")}
    if s["chart"] not in CHARTS:
        errs.append(f"unsupported chart '{s['chart']}'")
    for k in ("x", "y", "color"):
        if s[k] in ("", "null", "None"):
            s[k] = None
        if s[k] is not None and s[k] not in df.columns:
            match = max(df.columns, key=lambda c: SequenceMatcher(None, str(c).lower(), str(s[k]).lower()).ratio())
            if SequenceMatcher(None, match.lower(), str(s[k]).lower()).ratio() > 0.75:
                s[k] = match
            else:
                errs.append(f"unknown column '{s[k]}'")
    if s["agg"] not in AGGS:
        s["agg"] = "count" if not s["y"] else "mean"
    if s["time_grain"] not in GRAINS:
        s["time_grain"] = None
    filters = []
    for f in s.get("filters") or []:
        if isinstance(f, dict) and f.get("column") in df.columns:
            filters.append(f)
    s["filters"] = filters
    try:
        s["top_n"] = int(s["top_n"]) if s["top_n"] else None
    except (TypeError, ValueError):
        s["top_n"] = None
    return s, errs


def _apply_filters(df: pd.DataFrame, filters: list[dict]) -> tuple[pd.DataFrame, list[str]]:
    desc = []
    for f in filters:
        c, op, v = f["column"], f.get("op", "=="), f.get("value")
        s = df[c]
        try:
            if op == "year" and pd.api.types.is_datetime64_any_dtype(s):
                df = df[s.dt.year == int(v)]
            elif op in ("==", "!=") and not pd.api.types.is_numeric_dtype(s):
                m = s.astype("string").str.lower() == str(v).lower()
                df = df[m if op == "==" else ~m]
            elif op == "in":
                vals = [str(x).lower() for x in (v if isinstance(v, list) else [v])]
                df = df[s.astype("string").str.lower().isin(vals)]
            elif op == "contains":
                df = df[s.astype("string").str.contains(str(v), case=False, na=False)]
            else:
                num = float(v)
                df = df[{"==": s == num, "!=": s != num, ">": s > num, ">=": s >= num, "<": s < num, "<=": s <= num}[op]]
            desc.append(f"{c} {op} {v}")
        except (KeyError, ValueError, TypeError):
            continue
    return df, desc


def _agg_label(agg: str, y: str | None, target: str | None) -> str:
    if agg == "count" or not y:
        return "count"
    if y == target and agg == "mean":
        return f"{y} rate"
    return f"{agg} of {y}"


def run_spec(spec: dict, df: pd.DataFrame, roles: dict) -> dict:
    data, fdesc = _apply_filters(df, spec["filters"])
    chart, x, y, agg, color = spec["chart"], spec["x"], spec["y"], spec["agg"], spec["color"]
    target = roles.get("target")
    rate = y is not None and (y == target or y in roles.get("flag", [])) and agg == "mean"
    vfmt = (lambda v: pct(v)) if rate else (lambda v: f"{v:,.0f}") if agg == "count" or not y else (lambda v: fmt(v, y or ""))
    title = spec.get("title") or ""
    label = _agg_label(agg, y, target)
    out: dict[str, Any] = {"spec": spec, "rows_used": int(len(data)), "filters_applied": fdesc}
    if data.empty:
        return {**out, "summary": "No rows match those filters.", "chart": None}

    def grouped(keys: list[str]) -> pd.DataFrame:
        if agg == "count" or not y:
            g = data.groupby(keys, observed=True).size().rename("value")
        else:
            g = getattr(data.groupby(keys, observed=True)[y], agg)().rename("value")
        return g.reset_index()

    layout: dict[str, Any] = {"title": {"text": title}, "xaxis": {"title": {"text": x or ""}}, "yaxis": {"title": {"text": label}}}
    if rate:
        layout["yaxis"]["tickformat"] = ".0%"

    if chart == "kpi":
        val = float(len(data)) if agg == "count" or not y else float(getattr(data[y], agg)())
        title = title or (label.capitalize() if y else "Row count")
        return {**out, "kpi": {"label": title, "value": vfmt(val) if agg != "count" else f"{int(val):,}"},
                "summary": f"{title}: **{vfmt(val) if agg != 'count' else f'{int(val):,}'}**" + (f" (filters: {', '.join(fdesc)})" if fdesc else ""),
                "chart": None}

    if chart == "histogram":
        vals = data[x].dropna()
        traces = []
        if color:
            for k, part in data.groupby(color, observed=True):
                traces.append({"type": "histogram", "x": part[x].dropna().round(4).tolist()[:5000], "name": str(k), "opacity": 0.65})
            layout["barmode"] = "overlay"
        else:
            traces.append({"type": "histogram", "x": vals.round(4).tolist()[:5000], "nbinsx": 40})
        layout["yaxis"]["title"]["text"] = "rows"
        layout["title"]["text"] = title or f"Distribution of {x}"
        return {**out, "chart": {"data": traces, "layout": layout},
                "summary": f"**{x}**: median {fmt(vals.median(), x)}, mean {fmt(vals.mean(), x)}, range {fmt(vals.min(), x)} – {fmt(vals.max(), x)}."}

    if chart == "scatter":
        sub = data[[x, y] + ([color] if color else [])].dropna()
        sub = sub.sample(min(len(sub), 2000), random_state=0)
        traces = []
        groups = sub.groupby(color, observed=True) if color else [(None, sub)]
        for k, part in groups:
            traces.append({"type": "scattergl", "mode": "markers", "x": part[x].round(4).tolist(), "y": part[y].round(4).tolist(),
                           "name": str(k) if k is not None else y, "marker": {"size": 6, "opacity": 0.6}})
        r = sub[[x, y]].corr(method="spearman").iloc[0, 1]
        layout["yaxis"]["title"]["text"] = y
        layout["title"]["text"] = title or f"{y} vs {x}"
        return {**out, "chart": {"data": traces, "layout": layout},
                "summary": f"Spearman correlation between **{x}** and **{y}**: **{r:.2f}** ({len(sub):,} points shown)."}

    if chart == "box":
        traces = []
        if x:
            for k, part in data.groupby(x, observed=True):
                traces.append({"type": "box", "y": part[y].dropna().round(4).tolist()[:3000], "name": str(k), "boxmean": True})
        else:
            traces.append({"type": "box", "y": data[y].dropna().round(4).tolist()[:3000], "name": y, "boxmean": True})
        layout["yaxis"]["title"]["text"] = y
        layout["showlegend"] = False
        layout["title"]["text"] = title or f"{y} by {x}" if x else f"{y}"
        return {**out, "chart": {"data": traces, "layout": layout}, "summary": f"Box plot of **{y}**" + (f" by **{x}**." if x else ".")}

    if x is not None and pd.api.types.is_datetime64_any_dtype(data[x]):
        grain = GRAINS.get(spec.get("time_grain") or "", None)
        if not grain:
            span = (data[x].max() - data[x].min()).days
            grain = "QE" if span > 1100 else "ME" if span > 120 else "W" if span > 30 else "D"
        data = data.dropna(subset=[x]).copy()
        data[x] = data[x].dt.to_period({"QE": "Q", "ME": "M", "YE": "Y"}.get(grain, grain)).dt.to_timestamp()

    if chart == "heatmap":
        g = grouped([x, color]).pivot(index=color, columns=x, values="value")
        layout["xaxis"]["title"]["text"], layout["yaxis"]["title"]["text"] = x, color
        layout["title"]["text"] = title or f"{label} by {x} and {color}"
        return {**out, "chart": {"data": [{"type": "heatmap", "z": np.round(g.values.astype(float), 4).tolist(),
                                           "x": _clean_list(g.columns), "y": _clean_list(g.index), "colorscale": "Viridis",
                                           "texttemplate": "%{z:.3s}"}], "layout": layout},
                "summary": f"{label.capitalize()} for each **{x}** × **{color}** combination."}

    keys = [k for k in (x, color) if k]
    if not keys:
        return {**out, "summary": "I couldn't work out what to group by. Try naming a column, e.g. 'average price by region'.", "chart": None}
    g = grouped(keys)
    is_time = x is not None and pd.api.types.is_datetime64_any_dtype(g[x])
    if not is_time:
        order = g.groupby(x)["value"].sum().sort_values(ascending=spec.get("sort") == "asc")
        if spec.get("top_n"):
            order = order.iloc[: spec["top_n"]]
        g = g[g[x].isin(order.index)]
        g[x] = pd.Categorical(g[x], categories=order.index, ordered=True)
        g = g.sort_values(x)
    else:
        g = g.sort_values(x)
        periods = sorted(g[x].unique())
        if len(periods) > 5:  # drop an incomplete final period so trends aren't distorted
            sizes = data.groupby(x).size()
            if sizes.iloc[-1] < 0.4 * sizes.iloc[:-1].median():
                g = g[g[x] != periods[-1]]
                fdesc.append(f"incomplete last period ({pd.Timestamp(periods[-1]):%b %Y}) hidden")

    if chart == "table":
        table = g.copy()
        table.columns = [str(c) if c != "value" else label for c in table.columns]
        return {**out, "chart": None, "table": {"columns": list(table.columns),
                                                 "rows": [_clean_list(r) for r in table.head(200).itertuples(index=False)]},
                "summary": f"{len(table):,} rows of {label} by {', '.join(keys)}."}

    traces = []
    groups = g.groupby(color, observed=True) if color else [(None, g)]
    for k, part in groups:
        xs = _clean_list(part[x].astype(object) if not is_time else part[x].dt.strftime("%Y-%m-%d"))
        ys = [None if pd.isna(v) else round(float(v), 4) for v in part["value"]]
        name = str(k) if k is not None else label
        if chart == "pie":
            traces = [{"type": "pie", "labels": xs, "values": ys, "hole": 0.5, "textinfo": "label+percent"}]
            break
        if chart in ("line", "area"):
            traces.append({"type": "scatter", "mode": "lines+markers", "x": xs, "y": ys, "name": name,
                           "line": {"shape": "spline", "width": 3}, **({"fill": "tozeroy"} if chart == "area" or not color else {})})
        else:
            traces.append({"type": "bar", "x": xs, "y": ys, "name": name,
                           **({"text": [vfmt(v) for v in ys if v is not None], "textposition": "outside"} if not color else {})})
    if color and chart == "bar":
        layout["barmode"] = "group"
    layout["title"]["text"] = title or f"{label.capitalize()} by {x}" + (f" and {color}" if color else "")

    combine = "sum" if agg in ("sum", "count") else "mean"
    total = getattr(g.groupby(x, observed=True)["value"], combine)()
    if is_time:
        first, last = total.iloc[0], total.iloc[-1]
        ch = (last - first) / abs(first) if first else 0
        peak = total.idxmax()
        summary = (f"{label.capitalize()} went from **{vfmt(first)}** to **{vfmt(last)}** ({ch * 100:+.0f}%), "
                   f"peaking in **{pd.Timestamp(peak):%b %Y}** at **{vfmt(total.max())}**.")
    else:
        top_k, bot_k = total.idxmax(), total.idxmin()
        summary = f"Highest: **{top_k}** ({vfmt(total.max())}). Lowest: **{bot_k}** ({vfmt(total.min())})."
        if len(total) > 2 and agg in ("sum", "count"):
            summary += f" The top entry is **{total.max() / total.sum() * 100:.0f}%** of the total."
    if fdesc:
        summary += f" Filters: {', '.join(fdesc)}."
    return {**out, "chart": {"data": traces, "layout": layout}, "summary": summary}


def answer(question: str, df: pd.DataFrame, plan: dict | None, llm=None, llm_spec: dict | None = None) -> dict:
    """Full chat turn. ``llm_spec`` is a spec already produced by an LLM (optional)."""
    roles = detect_roles(df, plan)
    source = "llm" if llm_spec else "rules"
    raw_spec = llm_spec or parse_question(question, df, roles)
    if not raw_spec.get("chart"):
        cols = ", ".join(list(df.columns)[:12])
        return {"reply": "I couldn't map that to a chart yet. Mention one or two column names — for example "
                         f"*'average {(roles['measure'] or ['value'])[0]} by {(roles['dimension'] or ['category'])[0]}'*. "
                         f"Available columns: {cols}…", "chart": None, "source": source}
    spec, errs = validate_spec(raw_spec, df)
    if errs and source == "llm":  # fall back to the rule parser
        spec, errs2 = validate_spec(parse_question(question, df, roles), df)
        source = "rules"
        if errs2 or not spec.get("chart"):
            return {"reply": f"That request referenced something I couldn't find ({'; '.join(errs)}).", "chart": None, "source": source}
    elif errs:
        return {"reply": f"I couldn't build that chart: {'; '.join(errs)}.", "chart": None, "source": source}
    try:
        res = run_spec(spec, df, roles)
    except Exception as e:
        return {"reply": f"That combination didn't work ({e}). Try a different grouping.", "chart": None, "spec": spec, "source": source}
    res["source"] = source
    res["reply"] = res.pop("summary", "")
    return res
