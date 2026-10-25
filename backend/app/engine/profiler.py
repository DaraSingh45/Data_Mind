"""Profiling: facts about the data computed in code (never by the LLM).

The profile is the *only* view of the data the LLM receives.
"""
from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as sstats

from datamind_transformers import FALSE_SET, TRUE_SET, parse_datetime, parse_numeric

EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")
URL_RE = re.compile(r"^(https?://|www\.)", re.I)
PHONE_RE = re.compile(r"^\+?[\d\s().-]{7,}$")
ID_NAME_RE = re.compile(r"(^|_|\b)(id|uuid|guid|key|code|number|no)$|^id_|_id$", re.I)
TARGET_HINTS = ("target", "label", "churn", "default", "outcome", "class", "survived", "fraud", "converted", "is_", "y")
LEAK_HINTS = ("refund", "cancel", "closed", "end_date", "termination", "outcome", "result", "resolved", "final", "after", "post_")
GEO_HINTS = ("country", "state", "city", "region", "zip", "pincode", "postal", "province", "district", "latitude", "longitude", "lat", "lon", "lng")
SAMPLE_ROWS = 5000


def _py(v: Any) -> Any:
    """Make numpy/pandas scalars JSON-friendly."""
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        f = float(v)
        return None if np.isnan(f) or np.isinf(f) else round(f, 6)
    if isinstance(v, (pd.Timestamp,)):
        return v.isoformat()
    if v is pd.NA or v is pd.NaT:
        return None
    return v


def numeric_summary(s: pd.Series) -> dict:
    x = s.dropna().astype("float64")
    if x.empty:
        return {}
    q1, q3 = np.percentile(x, [25, 75])
    iqr = q3 - q1
    out_mask = (x < q1 - 1.5 * iqr) | (x > q3 + 1.5 * iqr)
    clipped = x.clip(q1 - 1.5 * iqr, q3 + 1.5 * iqr)
    skew_clipped = sstats.skew(clipped) if len(x) > 2 and clipped.std() > 0 else 0.0
    return {
        "skew_clipped": _py(skew_clipped),
        "mean": _py(x.mean()), "std": _py(x.std()), "min": _py(x.min()), "p25": _py(q1),
        "median": _py(x.median()), "p75": _py(q3), "max": _py(x.max()),
        "skew": _py(sstats.skew(x)) if len(x) > 2 and x.std() > 0 else 0.0,
        "zeros_pct": _py((x == 0).mean()), "negatives_pct": _py((x < 0).mean()),
        "outliers_pct": _py(out_mask.mean()), "is_integer": bool(np.all(np.mod(x, 1) == 0)),
    }


def detect_semantic(s: pd.Series, name: str, n_rows: int) -> tuple[str, dict]:
    """Returns (semantic_type, evidence)."""
    nn = s.dropna()
    ev: dict = {}
    if nn.empty:
        return "empty", ev
    n_unique = nn.nunique()
    lname = name.lower()

    if pd.api.types.is_bool_dtype(s):
        return "boolean", ev
    if pd.api.types.is_datetime64_any_dtype(s):
        return "datetime", ev
    if pd.api.types.is_numeric_dtype(s):
        vals = set(pd.unique(nn.astype("float64")))
        if vals <= {0.0, 1.0}:
            return "boolean", ev
        if ID_NAME_RE.search(lname) and n_unique > 10 and bool(np.all(np.mod(nn.astype("float64"), 1) == 0)):
            return "id", ev  # integer keys such as customer_id / order_no, unique or not (foreign keys repeat)
        return "numeric", ev

    sample = nn.astype("string").str.strip()
    if len(sample) > SAMPLE_ROWS:
        sample = sample.sample(SAMPLE_ROWS, random_state=0)
    low = sample.str.lower()
    ev["avg_length"] = _py(sample.str.len().mean())

    if set(low.unique()) <= (TRUE_SET | FALSE_SET) and low.nunique() <= 8:
        return "boolean", ev
    num = parse_numeric(sample)
    num_share = float(num.notna().mean())
    ev["numeric_parse_share"] = round(num_share, 3)
    if num_share >= 0.9:
        ev["currency_like"] = bool(sample.str.contains(r"[$€£¥₹]|rs\.?|inr", case=False, regex=True).mean() > 0.3)
        ev["percent_like"] = bool(sample.str.endswith("%").mean() > 0.3)
        ev["thousand_separators"] = bool(sample.str.contains(r"\d,\d{3}", regex=True).mean() > 0.2)
        if n_unique == len(nn) and n_unique > 20 and ID_NAME_RE.search(lname):
            return "id", ev
        return "numeric", ev
    if sample.str.match(EMAIL_RE).mean() > 0.8:
        return "email", ev
    if sample.str.match(URL_RE).mean() > 0.8:
        return "url", ev
    has_date_chars = sample.str.contains(r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|\d{4}-\d{2}|[A-Za-z]{3,9}\s+\d{1,2}", regex=True).mean()
    if has_date_chars > 0.6:
        d = parse_datetime(sample)
        ev["date_parse_share"] = round(float(d.notna().mean()), 3)
        if ev["date_parse_share"] >= 0.8:
            return "datetime", ev
    if sample.str.match(PHONE_RE).mean() > 0.8 and sample.str.count(r"\d").mean() >= 7:
        return "phone", ev
    unique_ratio = n_unique / max(len(nn), 1)
    if unique_ratio > 0.95 and n_unique > 20:
        if (ev["avg_length"] or 0) > 25 and sample.str.count(" ").mean() >= 3:
            return "text", ev
        return "id", ev
    if (ev["avg_length"] or 0) > 40 and sample.str.count(" ").mean() >= 5:
        return "text", ev
    return "categorical", ev


_ALIASES = {
    "m": "male", "f": "female", "y": "yes", "1": "yes", "true": "yes", "n": "no", "0": "no", "false": "no",
    "us": "usa", "unitedstates": "usa", "uk": "unitedkingdom", "na": "unknown",
    "1st": "first", "2nd": "second", "3rd": "third", "4th": "fourth", "5th": "fifth",
    "ev": "electric", "at": "automatic", "mt": "manual", "amt": "automatic",
}


def category_variants(s: pd.Series) -> dict[str, str]:
    """Groups spelling variants of one label and returns {variant: canonical}.

    Handles case/spacing/punctuation ('MALE', ' male'), common aliases ('Y'/'1' → 'Yes',
    '1st' → 'First', 'AT' → 'Automatic') and short codes that abbreviate exactly one
    longer label in the same column ('P' → 'Petrol', 'auto' → 'Automatic').
    An alias is used only when its full form is present in the column.
    """
    vc = s.dropna().astype("string").str.strip().value_counts()
    vc = vc[vc.index != ""]
    groups: dict[str, list[tuple[str, int]]] = {}
    for val, cnt in vc.items():
        key = re.sub(r"[^a-z0-9]+", "", str(val).lower())
        if key:
            groups.setdefault(key, []).append((str(val), int(cnt)))
    keys = set(groups)
    parent = {k: k for k in keys}

    def find(k: str) -> str:
        while parent[k] != k:
            k = parent[k]
        return k

    for k in keys:
        target = _ALIASES.get(k)
        if target in keys and target != k:
            parent[find(k)] = find(target)
            continue
        if k.isalpha() and len(k) <= 4:  # short code → the one longer label it abbreviates
            longer = [o for o in keys if o != k and len(o) >= len(k) + 2 and o.startswith(k)]
            if len(longer) == 1:
                parent[find(k)] = find(longer[0])
    merged: dict[str, list[tuple[str, str, int]]] = {}
    for k, members in groups.items():
        merged.setdefault(find(k), []).extend((k, v, c) for v, c in members)
    mapping: dict[str, str] = {}
    for members in merged.values():
        if len(members) < 2:
            continue
        # canonical: the full form (longest key), then the most used spelling, preferring 'Title' over 'UPPER'
        best_key = max({m[0] for m in members}, key=lambda k: (len(k), sum(c for kk, _, c in members if kk == k)))
        cands = [(v, c) for k, v, c in members if k == best_key]
        top = max(c for _, c in cands)

        def score(vc_: tuple[str, int]) -> float:
            v, c = vc_
            style = 0.5 if (v[:1].isupper() and not v.isupper()) else 0.3 if v.isupper() else 0.0
            return c + style * top

        canonical = max(cands, key=score)[0]
        for _, v, _c in members:
            if v != canonical:
                mapping[v] = canonical
    # original spellings with surrounding spaces map too
    for raw in s.dropna().astype("string").unique():
        st = str(raw).strip()
        if str(raw) != st and str(raw) not in mapping:
            mapping[str(raw)] = mapping.get(st, st)
    return mapping


def profile_column(df: pd.DataFrame, name: str) -> dict:
    s = df[name]
    n = len(s)
    semantic, ev = detect_semantic(s, name, n)
    n_missing = int(s.isna().sum())
    nn = s.dropna()
    n_unique = int(nn.nunique())
    col: dict[str, Any] = {
        "name": name,
        "pandas_dtype": str(s.dtype),
        "semantic_type": semantic,
        "missing": n_missing,
        "missing_pct": round(n_missing / n, 4) if n else 0.0,
        "unique": n_unique,
        "unique_pct": round(n_unique / max(len(nn), 1), 4),
        "evidence": ev,
        "warnings": [],
    }
    if semantic == "numeric":
        col["stats"] = numeric_summary(parse_numeric(s))
    elif semantic == "datetime":
        d = parse_datetime(s).dropna()
        if not d.empty:
            col["stats"] = {"min": d.min().isoformat(), "max": d.max().isoformat(),
                            "span_days": int((d.max() - d.min()).days)}
    if semantic in ("categorical", "boolean"):
        vc = nn.astype("string").str.strip().value_counts()
        col["top_values"] = [{"value": str(k), "count": int(v)} for k, v in vc.head(12).items()]
        if semantic == "categorical":
            col["variants"] = category_variants(nn)
    lname = name.lower()
    if any(h in lname for h in GEO_HINTS):
        col["geo_hint"] = True

    w = col["warnings"]
    if col["missing_pct"] > 0.5:
        w.append(f"{col['missing_pct']:.0%} missing")
    if n_unique <= 1:
        w.append("constant column")
        col["semantic_type"] = "constant"
    if semantic in ("id", "email", "phone", "url"):
        w.append(f"looks like an identifier ({semantic})")
    if semantic == "numeric" and ev.get("numeric_parse_share") is not None and s.dtype != "float64":
        w.append("numbers stored as text")
    if semantic == "categorical" and col.get("variants"):
        w.append(f"{len(col['variants'])} spelling variants")
    if semantic == "categorical" and n_unique > 50:
        w.append("high cardinality")
    st = col.get("stats") or {}
    if st.get("outliers_pct", 0) and st["outliers_pct"] > 0.01:
        w.append(f"{st['outliers_pct']:.1%} outliers")
    if abs(st.get("skew") or 0) > 2:
        w.append("highly skewed")
    return col


def profile_dataframe(df: pd.DataFrame) -> dict:
    cols = [profile_column(df, c) for c in df.columns]
    dups = int(df.duplicated().sum())
    numeric_cols = [c["name"] for c in cols if c["semantic_type"] == "numeric"]
    corr_pairs = []
    if len(numeric_cols) >= 2:
        num = pd.DataFrame({c: parse_numeric(df[c]) for c in numeric_cols[:40]})
        corr = num.corr(numeric_only=True)
        for i, a in enumerate(corr.columns):
            for b in corr.columns[i + 1 :]:
                v = corr.loc[a, b]
                if pd.notna(v) and abs(v) >= 0.6:
                    corr_pairs.append({"a": a, "b": b, "r": round(float(v), 3)})
        corr_pairs.sort(key=lambda p: -abs(p["r"]))
    total_cells = df.shape[0] * df.shape[1]
    return {
        "rows": int(df.shape[0]),
        "columns": int(df.shape[1]),
        "duplicate_rows": dups,
        "missing_cells_pct": round(float(df.isna().sum().sum()) / total_cells, 4) if total_cells else 0.0,
        "memory_mb": round(df.memory_usage(deep=True).sum() / 1e6, 2),
        "column_profiles": cols,
        "strong_correlations": corr_pairs[:15],
        "type_counts": pd.Series([c["semantic_type"] for c in cols]).value_counts().to_dict(),
    }


def guess_targets(profile: dict) -> list[str]:
    """Candidate target columns ranked by name hints and shape."""
    scored = []
    for c in profile["column_profiles"]:
        if c["semantic_type"] in ("id", "email", "url", "phone", "text", "constant", "empty", "datetime"):
            continue
        name = c["name"].lower()
        score = 0.0
        if any(name == h or name.startswith(h) or name.endswith(h) for h in TARGET_HINTS):
            score += 3
        if c["semantic_type"] == "boolean":
            score += 1.5
        if c["semantic_type"] == "categorical" and 2 <= c["unique"] <= 10:
            score += 0.5
        if c["missing_pct"] < 0.05:
            score += 0.3
        scored.append((score, c["name"]))
    scored.sort(reverse=True)
    return [n for s, n in scored if s >= 1.5][:5]


def infer_task(df: pd.DataFrame, target: str | None, profile: dict) -> str:
    if not target or target not in df.columns:
        return "none"
    c = next(c for c in profile["column_profiles"] if c["name"] == target)
    if c["semantic_type"] in ("boolean", "categorical"):
        return "classification"
    if c["semantic_type"] == "numeric":
        st = c.get("stats") or {}
        if st.get("is_integer") and c["unique"] <= 10:
            return "classification"
        return "regression"
    return "classification"


def target_analysis(df: pd.DataFrame, target: str, task: str, profile: dict) -> dict:
    """Class balance and per-column leakage scores against the target."""
    from sklearn.metrics import r2_score, roc_auc_score

    y_raw = df[target]
    out: dict[str, Any] = {"target": target, "task": task, "leakage": []}
    mask = y_raw.notna()
    if task == "classification":
        y = y_raw[mask].astype("string").str.strip().str.lower()
        vc = y.value_counts()
        out["classes"] = {str(k): int(v) for k, v in vc.head(20).items()}
        out["imbalance_ratio"] = round(float(vc.max() / max(vc.min(), 1)), 2) if len(vc) > 1 else 1.0
        out["missing_target"] = int((~mask).sum())
    else:
        y = parse_numeric(y_raw[mask])
        out["missing_target"] = int((~mask).sum())
    sub = df[mask]
    if len(sub) > SAMPLE_ROWS:
        sub = sub.sample(SAMPLE_ROWS, random_state=0)
        y = y.loc[sub.index]
    for c in profile["column_profiles"]:
        name = c["name"]
        if name == target or c["semantic_type"] in ("constant", "empty"):
            continue
        score = None
        try:
            if c["semantic_type"] == "numeric":
                x = parse_numeric(sub[name])
                ok = x.notna()
                if ok.sum() > 30:
                    if task == "classification" and y.nunique() == 2:
                        yb = (y[ok] == y[ok].value_counts().index[0]).astype(int)
                        auc = roc_auc_score(yb, x[ok])
                        score = max(auc, 1 - auc) * 2 - 1  # 0 = useless, 1 = perfect
                    elif task == "regression":
                        r = np.corrcoef(x[ok], y[ok])[0, 1]
                        score = abs(r) if pd.notna(r) else None
            elif c["semantic_type"] in ("categorical", "boolean") and c["unique"] <= 200:
                x = sub[name].astype("string").fillna("∅")
                if task == "classification":
                    # How well does the column alone predict the class? (purity)
                    ct = pd.crosstab(x, y)
                    purity = ct.max(axis=1).sum() / ct.values.sum()
                    base = y.value_counts(normalize=True).max()
                    score = max(0.0, (purity - base) / max(1 - base, 1e-9))
                else:
                    means = y.groupby(x).transform("mean")
                    score = max(0.0, r2_score(y, means))
        except Exception:
            score = None
        name_flag = any(h in name.lower() for h in LEAK_HINTS)
        if score is not None:
            out["leakage"].append({"column": name, "score": round(float(score), 4), "name_flag": name_flag})
        elif name_flag:
            out["leakage"].append({"column": name, "score": 0.0, "name_flag": True})
    out["leakage"].sort(key=lambda d: -d["score"])
    return out
