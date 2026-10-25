"""Schema-agnostic insight engine.

Charts are never written for specific columns. Columns get *roles* (measure,
dimension, time, target, flag) and candidate insights are generated from role
combinations, tested statistically, scored, de-duplicated and ranked. Every
number is computed here; the LLM only writes the narrative around them.
"""
from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as sstats

MONEY_HINTS = ("revenue", "sales", "amount", "price", "charge", "spend", "cost", "profit", "income", "salary", "value", "total", "fee")
MAX_POINTS = 1500


# ---------------------------------------------------------------------------
# roles
# ---------------------------------------------------------------------------

def detect_roles(df: pd.DataFrame, plan: dict | None = None) -> dict[str, Any]:
    plan_cols = {c["column"]: c for c in (plan or {}).get("columns", [])}
    target = (plan or {}).get("target")
    task = (plan or {}).get("task", "none")
    roles: dict[str, list[str]] = {"measure": [], "dimension": [], "time": [], "flag": [], "text": [], "geo": []}
    for col in df.columns:
        s = df[col]
        pc = plan_cols.get(col, {})
        st = pc.get("semantic_type")
        if col == target:
            continue
        if pd.api.types.is_datetime64_any_dtype(s):
            roles["time"].append(col)
        elif st == "boolean" or (pd.api.types.is_numeric_dtype(s) and set(pd.unique(s.dropna())) <= {0.0, 1.0} and s.nunique() == 2):
            roles["flag"].append(col)
        elif pd.api.types.is_numeric_dtype(s):
            roles["measure"].append(col)
        elif st == "text" or (s.astype("string").str.len().mean() or 0) > 40:
            roles["text"].append(col)
        else:
            n = s.nunique()
            if 2 <= n <= 60:
                roles["dimension"].append(col)
                if re.search(r"country|state|city|region|district|province|zone|pincode|zip", col, re.I):
                    roles["geo"].append(col)
    roles["measure"].sort(key=lambda c: (not any(h in c.lower() for h in MONEY_HINTS), c))
    roles["dimension"].sort(key=lambda c: df[c].nunique())  # low-cardinality dimensions make clearer segments
    target_kind = None
    if target and target in df.columns:
        t = df[target]
        if pd.api.types.is_numeric_dtype(t) and set(pd.unique(t.dropna())) <= {0.0, 1.0}:
            target_kind = "binary"
        elif task == "classification":
            target_kind = "multiclass"
        elif pd.api.types.is_numeric_dtype(t):
            target_kind = "numeric"
    return {**roles, "target": target if target_kind else None, "target_kind": target_kind, "task": task}


def is_money(col: str) -> bool:
    return any(h in col.lower() for h in MONEY_HINTS)


def fmt(v: float, col: str = "") -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    a = abs(v)
    if is_money(col):
        if a >= 1e7:
            return f"{v / 1e7:.2f} Cr"
        if a >= 1e5:
            return f"{v / 1e5:.2f} L"
        return f"{v:,.0f}"
    if a >= 1e6:
        return f"{v / 1e6:.2f}M"
    if a >= 1e4 or (a >= 100 and float(v).is_integer()):
        return f"{v:,.0f}"
    if a >= 100:
        return f"{v:,.1f}"
    return f"{v:.3g}"


def pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _time_grain(t: pd.Series) -> str:
    span = (t.max() - t.min()).days if t.notna().any() else 0
    if span > 3 * 365:
        return "QE"
    if span > 120:
        return "ME"
    if span > 30:
        return "W"
    return "D"


GRAIN_NAME = {"QE": "quarter", "ME": "month", "W": "week", "D": "day"}


def _bar(x, y, name="", orientation="v", text_fmt=None) -> dict:
    tr: dict[str, Any] = {"type": "bar", "x": list(x), "y": list(y), "name": name, "orientation": orientation}
    if orientation == "h":
        tr["x"], tr["y"] = list(y), list(x)
    if text_fmt:
        tr["text"] = [text_fmt(v) for v in y]
        tr["textposition"] = "outside" if orientation == "v" else "auto"
    return tr


def _layout(title: str, xt: str = "", yt: str = "", **extra) -> dict:
    return {"title": {"text": title}, "xaxis": {"title": {"text": xt}}, "yaxis": {"title": {"text": yt}}, **extra}


def _clean_list(values) -> list:
    out = []
    for v in values:
        if isinstance(v, (pd.Timestamp,)):
            out.append(v.isoformat())
        elif isinstance(v, (np.floating, float)):
            out.append(None if np.isnan(v) else float(v))
        elif isinstance(v, np.integer):
            out.append(int(v))
        else:
            out.append(None if v is pd.NA else str(v) if not isinstance(v, (int, float, str)) else v)
    return out


# ---------------------------------------------------------------------------
# candidate generators
# ---------------------------------------------------------------------------

def _kpis(df: pd.DataFrame, roles: dict) -> list[dict]:
    k = [{"label": "Rows", "value": f"{len(df):,}", "hint": f"{df.shape[1]} columns"}]
    t = roles["target"]
    if t and roles["target_kind"] == "binary":
        k.append({"label": f"{t} rate", "value": pct(df[t].mean()), "hint": f"{int(df[t].sum()):,} positive"})
    for m in roles["measure"][:3]:
        s = df[m].dropna()
        if s.empty:
            continue
        if is_money(m):
            k.append({"label": f"Total {m}", "value": fmt(s.sum(), m), "hint": f"avg {fmt(s.mean(), m)}"})
        else:
            k.append({"label": f"Avg {m}", "value": fmt(s.mean(), m), "hint": f"median {fmt(s.median(), m)}"})
    if roles["time"]:
        tc = df[roles["time"][0]].dropna()
        if not tc.empty:
            k.append({"label": "Time span", "value": f"{tc.min():%b %Y} – {tc.max():%b %Y}", "hint": roles["time"][0]})
    return k[:6]


def _binary_target_by_dimension(df, t, dim, alpha) -> dict | None:
    sub = df[[dim, t]].dropna()
    if sub[dim].nunique() < 2 or len(sub) < 30:
        return None
    g = sub.groupby(dim, observed=True)[t].agg(["mean", "count"])
    g = g[g["count"] >= max(10, len(sub) * 0.01)].sort_values("mean", ascending=False)
    if len(g) < 2:
        return None
    ct = pd.crosstab(sub[dim], sub[t])
    try:
        chi2, p, _, _ = sstats.chi2_contingency(ct)
        n = ct.values.sum()
        cramers_v = float(np.sqrt(chi2 / (n * (min(ct.shape) - 1)))) if min(ct.shape) > 1 else 0.0
    except ValueError:
        return None
    hi, lo = g.index[0], g.index[-1]
    ratio = g["mean"].iloc[0] / max(g["mean"].iloc[-1], 1e-9)
    significant = p < alpha
    text = (f"**{t}** rate is **{pct(g['mean'].iloc[0])}** for {dim} = *{hi}* vs **{pct(g['mean'].iloc[-1])}** for *{lo}*"
            + (f" — {ratio:.1f}× higher." if ratio < 50 else ".")
            + ("" if significant else " (not statistically significant)"))
    overall = sub[t].mean()
    return {
        "kind": "driver", "title": f"{t} rate by {dim}", "text": text, "columns": [dim, t],
        "score": (0.55 + 0.45 * min(cramers_v * 2.5, 1)) * (1 if significant else 0.35),
        "stats": {"p_value": float(p), "cramers_v": round(cramers_v, 3), "ratio": round(float(ratio), 2)},
        "effect": cramers_v,
        "chart": {"data": [_bar(_clean_list(g.index), [round(v, 4) for v in g["mean"]], text_fmt=pct)],
                  "layout": _layout(f"{t} rate by {dim}", dim, f"{t} rate", yaxis={"tickformat": ".0%", "title": {"text": f"{t} rate"}},
                                    shapes=[{"type": "line", "xref": "paper", "x0": 0, "x1": 1, "y0": overall, "y1": overall,
                                             "line": {"dash": "dot", "width": 1}}])},
    }


def _binary_target_by_measure(df, t, m, alpha) -> dict | None:
    sub = df[[m, t]].dropna()
    if len(sub) < 50 or sub[m].nunique() < 5:
        return None
    a, b = sub.loc[sub[t] == 1, m], sub.loc[sub[t] == 0, m]
    if len(a) < 10 or len(b) < 10:
        return None
    try:
        _, p = sstats.mannwhitneyu(a, b)
    except ValueError:
        return None
    auc = float(sstats.mannwhitneyu(a, b).statistic / (len(a) * len(b)))
    effect = abs(auc - 0.5) * 2
    try:
        bins = pd.qcut(sub[m], q=min(8, sub[m].nunique()), duplicates="drop")
    except ValueError:
        return None
    g = sub.groupby(bins, observed=True)[t].mean()
    labels = [f"{fmt(iv.left, m)}–{fmt(iv.right, m)}" for iv in g.index]
    direction = "rises" if g.iloc[-1] > g.iloc[0] else "falls"
    text = (f"**{t}** rate {direction} from **{pct(g.iloc[0])}** to **{pct(g.iloc[-1])}** across the range of **{m}** "
            f"(median {fmt(a.median(), m)} for {t}=1 vs {fmt(b.median(), m)} otherwise)."
            + ("" if p < alpha else " Not statistically significant."))
    return {
        "kind": "driver", "title": f"{t} rate across {m}", "text": text, "columns": [m, t],
        "score": (0.5 + 0.5 * min(effect * 2.5, 1)) * (1 if p < alpha else 0.35),
        "stats": {"p_value": float(p), "auc": round(auc, 3)}, "effect": effect,
        "chart": {"data": [{"type": "scatter", "mode": "lines+markers", "x": labels, "y": [round(v, 4) for v in g.values],
                            "line": {"shape": "spline", "width": 3}, "fill": "tozeroy"}],
                  "layout": _layout(f"{t} rate across {m} bands", m, f"{t} rate", yaxis={"tickformat": ".0%", "title": {"text": f"{t} rate"}})},
    }


def _numeric_target_by_dimension(df, t, dim, alpha) -> dict | None:
    sub = df[[dim, t]].dropna()
    groups = [g[t].values for _, g in sub.groupby(dim, observed=True) if len(g) >= 5]
    if len(groups) < 2:
        return None
    try:
        h, p = sstats.kruskal(*groups)
    except ValueError:
        return None
    eta = max(0.0, (h - len(groups) + 1) / (len(sub) - len(groups))) if len(sub) > len(groups) else 0
    g = sub.groupby(dim, observed=True)[t].mean().sort_values(ascending=False)
    text = (f"Average **{t}** is highest for {dim} = *{g.index[0]}* (**{fmt(g.iloc[0], t)}**) and lowest for "
            f"*{g.index[-1]}* (**{fmt(g.iloc[-1], t)}**).")
    return {"kind": "driver", "title": f"{t} by {dim}", "text": text, "columns": [dim, t],
            "score": (0.5 + 0.5 * min(eta * 4, 1)) * (1 if p < alpha else 0.35), "effect": eta,
            "stats": {"p_value": float(p), "eta_squared": round(float(eta), 3)},
            "chart": {"data": [_bar(_clean_list(g.index), [round(v, 4) for v in g.values], text_fmt=lambda v: fmt(v, t))],
                      "layout": _layout(f"Average {t} by {dim}", dim, f"avg {t}")}}


def _numeric_target_by_measure(df, t, m, alpha) -> dict | None:
    sub = df[[m, t]].dropna()
    if len(sub) < 30:
        return None
    rho, p = sstats.spearmanr(sub[m], sub[t])
    if np.isnan(rho):
        return None
    samp = sub.sample(min(len(sub), MAX_POINTS), random_state=0)
    text = (f"**{m}** and **{t}** have a {'positive' if rho > 0 else 'negative'} {'strong' if abs(rho) > 0.5 else 'moderate' if abs(rho) > 0.3 else 'weak'} "
            f"relationship (Spearman ρ = {rho:.2f}).")
    return {"kind": "driver", "title": f"{t} vs {m}", "text": text, "columns": [m, t],
            "score": (0.4 + 0.6 * min(abs(rho) * 1.5, 1)) * (1 if p < alpha else 0.3), "effect": abs(rho),
            "stats": {"p_value": float(p), "spearman": round(float(rho), 3)},
            "chart": {"data": [{"type": "scattergl", "mode": "markers", "x": samp[m].round(4).tolist(), "y": samp[t].round(4).tolist(),
                                "marker": {"size": 6, "opacity": 0.55}}],
                      "layout": _layout(f"{t} vs {m}", m, t)}}


def _driver_summary(drivers: list[dict], t: str) -> dict | None:
    ranked = sorted([d for d in drivers if d.get("effect") is not None], key=lambda d: -d["effect"])[:10]
    if len(ranked) < 3:
        return None
    names = [d["columns"][0] for d in ranked][::-1]
    vals = [round(d["effect"], 4) for d in ranked][::-1]
    top = ", ".join(f"**{d['columns'][0]}**" for d in ranked[:3])
    return {"kind": "driver", "title": f"What drives {t}", "text": f"The strongest signals for **{t}** are {top} "
            "(effect sizes from statistical tests on the cleaned data).", "columns": [t], "score": 0.97,
            "stats": {"ranking": [{"column": d["columns"][0], "effect": round(d["effect"], 3)} for d in ranked]},
            "chart": {"data": [{"type": "bar", "orientation": "h", "x": vals, "y": names}],
                      "layout": _layout(f"Key drivers of {t}", "effect size", "", margin={"l": 140})}}


def _trend(df, tcol, measure, agg, alpha, target=None, show_time_col=False) -> dict | None:
    sub = df[[tcol] + ([measure] if measure else [])].dropna(subset=[tcol])
    if len(sub) < 20:
        return None
    grain = _time_grain(sub[tcol])
    s = sub.set_index(tcol)
    if measure is None:
        series = s.resample(grain).size().astype(float)
        label, ylab = f"Records per {GRAIN_NAME[grain]}", "count"
    else:
        series = getattr(s[measure].resample(grain), agg)()
        label = (f"{target} rate per {GRAIN_NAME[grain]}" if target is not None and target == measure else
                 f"{'Total' if agg == 'sum' else 'Average'} {measure} per {GRAIN_NAME[grain]}")
        ylab = measure
    series = series.dropna()
    if show_time_col:
        label += f" ({tcol})"
    if len(series) < 4:
        return None
    # drop a partial last period if it is much smaller than usual
    if len(series) > 5:
        counts = s.resample(grain).size()
        if counts.iloc[-1] < 0.4 * counts.iloc[:-1].median():
            series = series.iloc[:-1]  # incomplete final period
    x = np.arange(len(series))
    slope, intercept, r, p, _ = sstats.linregress(x, series.values)
    first, last = series.iloc[: max(1, len(series) // 4)].mean(), series.iloc[-max(1, len(series) // 4):].mean()
    change = (last - first) / abs(first) if first else 0.0
    resid = series.values - (intercept + slope * x)
    z = (resid - resid.mean()) / (resid.std() or 1)
    anomalies = [i for i in np.where(np.abs(z) > 2.5)[0]]
    peak_i = int(np.argmax(series.values))
    is_rate = target is not None and target == measure
    fmt_v = (lambda v: pct(v)) if is_rate else (lambda v: f"{v:,.0f}") if measure is None else (lambda v: fmt(v, measure))
    text = (f"{label}: {'up' if change > 0 else 'down'} **{abs(change) * 100:.0f}%** from the start to the end of the period"
            f" (trend {'significant' if p < alpha else 'not significant'}). Peak in **{series.index[peak_i]:%b %Y}** at **{fmt_v(series.iloc[peak_i])}**.")
    if anomalies:
        text += f" {len(anomalies)} unusual {GRAIN_NAME[grain]}(s) detected."
    xs = [d.strftime("%Y-%m-%d") for d in series.index]
    data = [{"type": "scatter", "mode": "lines", "x": xs, "y": [round(float(v), 4) for v in series.values],
             "line": {"shape": "spline", "width": 3}, "fill": "tozeroy", "name": label},
            {"type": "scatter", "mode": "lines", "x": xs, "y": [round(float(intercept + slope * i), 4) for i in x],
             "line": {"dash": "dot", "width": 1.5}, "name": "trend"}]
    if anomalies:
        data.append({"type": "scatter", "mode": "markers", "x": [xs[i] for i in anomalies],
                     "y": [round(float(series.values[i]), 4) for i in anomalies], "marker": {"size": 11, "symbol": "circle-open", "line": {"width": 2}},
                     "name": "anomaly"})
    layout = _layout(label, tcol, ylab, showlegend=False)
    if is_rate:
        layout["yaxis"]["tickformat"] = ".0%"
    return {"kind": "trend", "title": label, "text": text, "columns": [tcol] + ([measure] if measure else []),
            "score": (0.45 + 0.4 * min(abs(change), 1) + (0.1 if anomalies else 0)) * (1 if p < alpha else 0.6),
            "stats": {"p_value": float(p), "change": round(float(change), 4), "anomalies": len(anomalies), "grain": GRAIN_NAME[grain]},
            "chart": {"data": data, "layout": layout}}


def _segment(df, dim, m, alpha) -> dict | None:
    sub = df[[dim, m]].dropna()
    groups = [g[m].values for _, g in sub.groupby(dim, observed=True) if len(g) >= 5]
    if len(groups) < 2:
        return None
    try:
        h, p = sstats.kruskal(*groups)
    except ValueError:
        return None
    eta = max(0.0, (h - len(groups) + 1) / (len(sub) - len(groups))) if len(sub) > len(groups) else 0
    agg = "sum" if is_money(m) and False else "mean"
    g = sub.groupby(dim, observed=True)[m].agg(["mean", "sum", "count"]).sort_values("mean", ascending=False)
    ratio = g["mean"].iloc[0] / g["mean"].iloc[-1] if g["mean"].iloc[-1] else np.inf
    text = (f"Average **{m}** for {dim} = *{g.index[0]}* is **{fmt(g['mean'].iloc[0], m)}** vs **{fmt(g['mean'].iloc[-1], m)}** for *{g.index[-1]}*"
            + (f" ({ratio:.1f}×)." if np.isfinite(ratio) and ratio < 100 else "."))
    if p >= alpha:
        text += " Differences are not statistically significant."
    return {"kind": "segment", "title": f"{m} by {dim}", "text": text, "columns": [dim, m],
            "score": (0.35 + 0.55 * min(eta * 4, 1)) * (1 if p < alpha else 0.3), "effect": eta,
            "stats": {"p_value": float(p), "eta_squared": round(float(eta), 3), "agg": agg},
            "chart": {"data": [_bar(_clean_list(g.index), [round(v, 4) for v in g["mean"]], text_fmt=lambda v: fmt(v, m))],
                      "layout": _layout(f"Average {m} by {dim}", dim, f"avg {m}")}}


def _distribution(df, m) -> dict | None:
    s = df[m].dropna()
    if len(s) < 30 or s.nunique() < 10:
        return None
    skew = float(sstats.skew(s))
    data = [{"type": "histogram", "x": s.sample(min(len(s), 5000), random_state=0).round(4).tolist(), "nbinsx": 40, "opacity": 0.9}]
    pareto = None
    if (s >= 0).all() and s.sum() > 0:
        top = s.sort_values(ascending=False)
        k = max(1, int(len(top) * 0.2))
        pareto = float(top.iloc[:k].sum() / top.sum())
    text = f"**{m}** has median **{fmt(s.median(), m)}** and mean **{fmt(s.mean(), m)}**"
    if abs(skew) > 1:
        text += f"; the distribution is {'right' if skew > 0 else 'left'}-skewed (skew {skew:.1f})"
    if pareto and pareto > 0.4:
        text += f". The top 20% of rows account for **{pct(pareto)}** of the total"
    text += "."
    score = 0.25 + 0.25 * min(abs(skew) / 3, 1) + (0.35 * min((pareto - 0.2) / 0.5, 1) if pareto and pareto > 0.35 else 0)
    return {"kind": "distribution", "title": f"Distribution of {m}", "text": text, "columns": [m], "score": score,
            "stats": {"skew": round(skew, 3), "top20_share": None if pareto is None else round(pareto, 3)},
            "chart": {"data": data, "layout": _layout(f"Distribution of {m}", m, "rows", bargap=0.05)}}


def _correlations(df, measures, alpha) -> list[dict]:
    out = []
    ms = measures[:15]
    if len(ms) < 2:
        return out
    corr = df[ms].corr(method="spearman")
    pairs = []
    for i, a in enumerate(ms):
        for b in ms[i + 1:]:
            r = corr.loc[a, b]
            if pd.notna(r) and abs(r) >= 0.45:
                pairs.append((abs(r), a, b, r))
    for _, a, b, r in sorted(pairs, reverse=True)[:3]:
        sub = df[[a, b]].dropna()
        samp = sub.sample(min(len(sub), MAX_POINTS), random_state=0)
        out.append({"kind": "correlation", "title": f"{a} vs {b}", "columns": [a, b],
                    "text": f"**{a}** and **{b}** move {'together' if r > 0 else 'in opposite directions'} (Spearman ρ = {r:.2f}).",
                    "score": 0.3 + 0.5 * min((abs(r) - 0.45) / 0.5, 1), "stats": {"spearman": round(float(r), 3)},
                    "chart": {"data": [{"type": "scattergl", "mode": "markers", "x": samp[a].round(4).tolist(), "y": samp[b].round(4).tolist(),
                                        "marker": {"size": 6, "opacity": 0.5}}],
                              "layout": _layout(f"{a} vs {b}", a, b)}})
    if len(ms) >= 3:
        z = corr.round(2)
        out.append({"kind": "correlation", "title": "Correlation matrix", "columns": ms,
                    "text": "Spearman correlations between all numeric measures.", "score": 0.28, "stats": {},
                    "chart": {"data": [{"type": "heatmap", "z": z.values.tolist(), "x": ms, "y": ms, "zmin": -1, "zmax": 1,
                                        "colorscale": "RdBu", "reversescale": True, "text": z.values.tolist(), "texttemplate": "%{text}"}],
                              "layout": _layout("Correlation matrix", "", "", margin={"l": 120, "b": 100})}})
    return out


def _composition(df, dim) -> dict | None:
    vc = df[dim].value_counts()
    if not 2 <= len(vc) <= 7:
        return None
    share = vc.iloc[0] / vc.sum()
    return {"kind": "composition", "title": f"Mix of {dim}", "columns": [dim],
            "text": f"*{vc.index[0]}* is the largest {dim} group with **{pct(share)}** of rows.",
            "score": 0.18 + 0.2 * share, "stats": {"top_share": round(float(share), 3)},
            "chart": {"data": [{"type": "pie", "labels": _clean_list(vc.index), "values": vc.values.tolist(), "hole": 0.55,
                                "textinfo": "label+percent"}],
                      "layout": _layout(f"Mix of {dim}", showlegend=False)}}


def _quality(profile: dict | None) -> dict | None:
    if not profile:
        return None
    miss = [(c["name"], c["missing_pct"]) for c in profile["column_profiles"] if c["missing_pct"] > 0]
    if not miss:
        return None
    miss.sort(key=lambda x: x[1])
    return {"kind": "quality", "title": "Missing values in the raw data", "columns": [m[0] for m in miss],
            "text": f"{len(miss)} columns had missing values before cleaning; the worst was **{miss[-1][0]}** ({pct(miss[-1][1])}).",
            "score": 0.15, "stats": {},
            "chart": {"data": [{"type": "bar", "orientation": "h", "x": [round(m[1], 4) for m in miss], "y": [m[0] for m in miss]}],
                      "layout": _layout("Missing values (raw data)", "share missing", "", xaxis={"tickformat": ".0%"}, margin={"l": 140})}}


# ---------------------------------------------------------------------------
# main entry
# ---------------------------------------------------------------------------

def generate_insights(df: pd.DataFrame, plan: dict | None, profile: dict | None, max_insights: int = 12, alpha: float = 0.05,
                      safe: bool = False) -> dict:
    """safe=True (used by self-repair) skips any single analysis that crashes instead of failing."""
    skipped: list[str] = []

    def call(fn, *args, **kw):
        if not safe:
            return fn(*args, **kw)
        try:
            return fn(*args, **kw)
        except Exception as e:  # noqa: BLE001
            skipped.append(f"{fn.__name__}: {e}"[:160])
            return None

    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_string_dtype(df[c]) or df[c].dtype == object:
            df[c] = df[c].astype("string")
    roles = detect_roles(df, plan)
    t, tk = roles["target"], roles["target_kind"]
    cands: list[dict] = []
    drivers: list[dict] = []
    if t and tk == "binary":
        for d in roles["dimension"] + roles["flag"]:
            r = call(_binary_target_by_dimension, df, t, d, alpha)
            if r:
                drivers.append(r)
        for m in roles["measure"]:
            r = call(_binary_target_by_measure, df, t, m, alpha)
            if r:
                drivers.append(r)
    elif t and tk == "numeric":
        for d in roles["dimension"] + roles["flag"]:
            r = call(_numeric_target_by_dimension, df, t, d, alpha)
            if r:
                drivers.append(r)
        for m in roles["measure"]:
            r = call(_numeric_target_by_measure, df, t, m, alpha)
            if r:
                drivers.append(r)
    cands += drivers
    if t:
        ds = call(_driver_summary, drivers, t)
        if ds:
            cands.append(ds)
    many_times = len(roles["time"]) > 1
    for tc in roles["time"][:2]:
        r = call(_trend, df, tc, None, "size", alpha, show_time_col=many_times)
        if r:
            cands.append(r)
        if t and tk == "binary":
            r = call(_trend, df, tc, t, "mean", alpha, target=t, show_time_col=many_times)
            if r:
                cands.append(r)
        for m in roles["measure"][:2]:
            r = call(_trend, df, tc, m, "sum" if is_money(m) else "mean", alpha, show_time_col=many_times)
            if r:
                cands.append(r)
    seg_measures = roles["measure"][:4]
    for d in [d for d in roles["dimension"] if df[d].nunique() <= 30][:8]:
        for m in seg_measures:
            r = call(_segment, df, d, m, alpha)
            if r:
                cands.append(r)
    for m in roles["measure"][:8]:
        r = call(_distribution, df, m)
        if r:
            cands.append(r)
    cands += call(_correlations, df, roles["measure"], alpha) or []
    for d in roles["dimension"][:4]:
        r = call(_composition, df, d)
        if r:
            cands.append(r)
    q = call(_quality, profile)
    if q:
        cands.append(q)

    # rank with diversity: cap per kind, avoid repeating the same column pair
    cands.sort(key=lambda c: -c["score"])
    caps = {"driver": 6, "trend": 4, "segment": 4, "distribution": 3, "correlation": 3, "composition": 2, "quality": 1}
    used: dict[str, int] = {}
    seen_pairs: set = set()
    chosen = []
    for c in cands:
        key = tuple(sorted(c["columns"][:2]))
        if used.get(c["kind"], 0) >= caps.get(c["kind"], 3) or key in seen_pairs:
            continue
        used[c["kind"]] = used.get(c["kind"], 0) + 1
        seen_pairs.add(key)
        chosen.append(c)
        if len(chosen) >= max_insights:
            break
    for i, c in enumerate(chosen):
        c["id"] = f"ins{i + 1}"
        c["score"] = round(float(c["score"]), 3)
        c.pop("effect", None)
    return {
        "roles": roles,
        "kpis": (call(_kpis, df, roles) or []) if safe else _kpis(df, roles),
        "insights": chosen,
        "candidates_considered": len(cands),
        "filters": {d: _clean_list(df[d].dropna().unique()[:40]) for d in roles["dimension"][:6]},
        "skipped": skipped,
    }


def template_narrative(result: dict) -> dict:
    ins = result["insights"]
    strip = lambda s: re.sub(r"\*+", "", s)  # drop markdown emphasis, keep snake_case names
    if not ins:
        return {"headline": "No strong patterns found", "summary": "The data was profiled but no statistically strong patterns stood out.",
                "bullets": [], "next_steps": []}
    top = ins[0]
    return {
        "headline": strip(top["title"]).capitalize(),
        "summary": " ".join(strip(i["text"]) for i in ins[:2]),
        "bullets": [strip(i["text"]) for i in ins[:6]],
        "next_steps": ["Ask the insight chat for any breakdown you need.",
                       "Use the model-ready train/test files to train and compare models."],
        "source": "template",
    }
