"""Rule-based planner. Always produces a valid baseline plan; the LLM refines it.

Every decision carries a human-readable reason and a confidence score. Low
confidence decisions become questions for the user.
"""
from __future__ import annotations

from typing import Any

from ..core.settings import PrepSettings

LEAK_THRESHOLD = 0.95
LEAK_ASK_THRESHOLD = 0.8


def _scaling(prep: PrepSettings, has_outliers: bool) -> str:
    if prep.scaling != "auto":
        return prep.scaling
    if prep.model_family == "tree":
        return "none"
    return "robust" if has_outliers else "standard"


def build_heuristic_plan(profile: dict, intent: dict, target_info: dict | None, prep: PrepSettings) -> dict:
    target = intent.get("target")
    task = intent.get("task", "none") if target else "none"
    leak = {d["column"]: d for d in (target_info or {}).get("leakage", [])}
    columns: list[dict[str, Any]] = []
    questions: list[dict] = []
    notes: list[str] = []
    datetime_cols: list[str] = []

    for c in profile["column_profiles"]:
        name, st = c["name"], c["semantic_type"]
        stats = c.get("stats") or {}
        col: dict[str, Any] = {"column": name, "semantic_type": st, "role": "feature", "kind": "numeric",
                               "impute": "median", "encode": "none", "scale": "none", "outliers": "none",
                               "confidence": 0.9, "source": "heuristic"}
        reasons: list[str] = []

        if name == target:
            col.update(role="target", kind="categorical" if task == "classification" else "numeric",
                       dtype_fix=("numeric" if task == "regression" and st == "numeric" else
                                  "boolean" if st == "boolean" else "category"),
                       normalize_text=st == "categorical", impute="none", reason="Prediction target chosen for this run.")
            if st == "categorical" and c.get("variants"):
                col["category_map"] = c["variants"]
            columns.append(col)
            continue

        drop_reason = None
        if st in ("constant", "empty"):
            drop_reason = "Has a single value (or none) — carries no information."
        elif st in ("id", "email", "phone", "url"):
            drop_reason = f"Looks like an identifier ({st}); unique per row, no predictive value and a privacy risk."
        elif c["missing_pct"] > prep.drop_missing_threshold:
            drop_reason = f"{c['missing_pct']:.0%} of values are missing (threshold {prep.drop_missing_threshold:.0%})."
        elif st == "categorical" and c["unique_pct"] > 0.9 and c["unique"] > 100:
            drop_reason = "Almost every value is unique — behaves like an ID."
        if drop_reason:
            col.update(role="drop", reason=drop_reason, confidence=0.95)
            columns.append(col)
            continue

        lk = leak.get(name)
        if target and lk and (lk["score"] >= LEAK_THRESHOLD or (lk["name_flag"] and lk["score"] >= 0.5)):
            col.update(role="drop", confidence=0.6,
                       reason=f"Suspected target leakage: on its own it predicts '{target}' with score {lk['score']:.2f}"
                              + (" and its name suggests it is recorded after the outcome." if lk["name_flag"] else "."))
            questions.append({"id": f"leak:{name}", "column": name,
                              "question": f"'{name}' predicts the target almost perfectly. Is it known *before* the outcome happens?",
                              "options": ["Drop it (it is recorded after the outcome)", "Keep it (it is available at prediction time)"],
                              "default": "Drop it (it is recorded after the outcome)"})
            columns.append(col)
            continue
        if target and lk and lk["score"] >= LEAK_ASK_THRESHOLD:
            reasons.append(f"Very strong single-column signal ({lk['score']:.2f}) — check it is not leakage.")
            col["confidence"] = 0.65

        if st == "numeric":
            needs_parse = c["pandas_dtype"] not in ("float64", "int64", "Int64", "float32", "int32")
            col.update(kind="numeric", dtype_fix="numeric" if needs_parse else None)
            if needs_parse:
                ev = c.get("evidence", {})
                what = "currency symbols" if ev.get("currency_like") else "percent signs" if ev.get("percent_like") else "text formatting"
                reasons.append(f"Numbers stored as text with {what} — parse to numeric.")
            skew = abs(stats.get("skew") or 0)
            core_skew = abs(stats.get("skew_clipped") or 0)  # skew of the bulk, ignoring extreme values
            out_pct = stats.get("outliers_pct") or 0
            if c["missing_pct"] > 0:
                col["impute"] = "median" if skew > 1 or out_pct > 0.01 else "mean"
                reasons.append(f"Impute {c['missing_pct']:.1%} missing with the {col['impute']}"
                               + (" (robust to skew/outliers)." if col["impute"] == "median" else "."))
                if prep.add_missing_flags and c["missing_pct"] >= 0.05:
                    col["add_missing_flag"] = True
                    reasons.append("Add a missing-value flag — missingness itself may be informative.")
            strategy = prep.outlier_strategy
            if strategy == "auto":
                if core_skew > 1 and (stats.get("min") or 0) >= 0:
                    strategy = "log1p"
                elif out_pct > 0.002:
                    strategy = "clip_iqr"
                else:
                    strategy = "none"
            col["outliers"] = strategy
            if strategy == "log1p":
                reasons.append(f"Long right tail (skew {core_skew:.1f} even without extremes) and non-negative — log-transform.")
            elif strategy in ("clip_iqr", "winsorize"):
                reasons.append(f"{out_pct:.1%} outliers — {strategy.replace('_', ' ')} using bounds learned on train only.")
            col["scale"] = _scaling(prep, out_pct > 0.01)
            if col["scale"] != "none":
                reasons.append(f"{col['scale'].title()} scaling for distance/linear models.")
        elif st == "boolean":
            col.update(kind="numeric", dtype_fix="boolean", impute="most_frequent")
            reasons.append("Yes/No style values — convert to 1/0.")
        elif st == "datetime":
            datetime_cols.append(name)
            col.update(kind="numeric", dtype_fix="datetime", datetime_features=True, impute="median")
            reasons.append("Date — expand into year, month, day, weekday and weekend features.")
        elif st == "text":
            col.update(kind="numeric", dtype_fix="text", text_features=True, impute="median")
            reasons.append("Free text — extract length and word-count features.")
        else:  # categorical
            col.update(kind="categorical", dtype_fix="category", normalize_text=True)
            if c.get("variants"):
                col["category_map"] = c["variants"]
                reasons.append(f"Merge {len(c['variants'])} spelling variants (e.g. "
                               + ", ".join(f"'{k}'→'{v}'" for k, v in list(c["variants"].items())[:2]) + ").")
            if c["missing_pct"] > 0.1:
                col["impute"] = "constant"
                reasons.append("Many missing — use an explicit 'Missing' category.")
            else:
                col["impute"] = "most_frequent"
                if c["missing_pct"] > 0:
                    reasons.append("Fill the few missing values with the most common category.")
            n_unique = c["unique"] - len(c.get("variants") or {})
            if n_unique > 10:
                col["rare_threshold"] = prep.rare_category_threshold
                reasons.append(f"Group categories rarer than {prep.rare_category_threshold:.0%} into 'Other'.")
            if n_unique <= prep.max_onehot_categories:
                col["encode"] = "onehot"
                reasons.append(f"{n_unique} categories — one-hot encode.")
            elif target and task in ("classification", "regression"):
                col["encode"] = "target"
                reasons.append(f"{n_unique} categories — cross-validated target encoding (avoids a column explosion).")
            else:
                col["encode"] = "frequency"
                reasons.append(f"{n_unique} categories — frequency encoding.")
        col["reason"] = " ".join(reasons) or "Clean already — keep as is."
        columns.append(col)

    split: dict[str, Any] = {"strategy": "random", "test_size": prep.test_size, "time_column": None, "seed": prep.random_seed}
    imbalance = "none"
    if task == "classification":
        split["strategy"] = "stratified"
        ratio = (target_info or {}).get("imbalance_ratio", 1.0)
        if ratio >= 3:
            imbalance = "oversample" if prep.imbalance in ("auto", "oversample") else "none"
            notes.append(f"Classes are imbalanced ({ratio:.1f}:1)."
                         + (" Minority class will be oversampled in the training set only." if imbalance == "oversample" else ""))
        elif prep.imbalance == "oversample":
            imbalance = "oversample"
    if not target:
        notes.append("No target selected — the data is cleaned and encoded for exploration or unsupervised use.")
    if profile["duplicate_rows"]:
        notes.append(f"{profile['duplicate_rows']} exact duplicate rows will be removed before splitting.")
    if datetime_cols:
        notes.append("For time-ordered data consider a time-based split so the test set is the most recent period.")

    return {
        "target": target,
        "task": task,
        "drop_duplicates": prep.drop_duplicates and profile["duplicate_rows"] > 0,
        "split": split,
        "imbalance": imbalance,
        "columns": columns,
        "notes": notes,
        "questions": questions,
    }


def heuristic_revision(plan: dict, checks: dict) -> tuple[list[dict], list[str]]:
    """Rule-based response to failed quality checks: returns (changes, feedback)."""
    changes: list[dict] = []
    feedback: list[str] = []
    for w in checks.get("leakage_warnings", []):
        changes.append({"column": w["source_column"], "field": "role", "value": "drop",
                        "reason": f"Dropped after verification: feature '{w['feature']}' alone scores {w['score']:.3f}."})
        feedback.append(f"Drop '{w['source_column']}' — single-feature score {w['score']:.3f} indicates leakage.")
    base = checks.get("baseline") or {}
    if base.get("delta") is not None and base["delta"] < -0.02:
        for c in plan["columns"]:
            if c.get("outliers") == "log1p":
                changes.append({"column": c["column"], "field": "outliers", "value": "clip_iqr",
                                "reason": "Log transform hurt validation score; switched to IQR clipping."})
        feedback.append(f"Prepared data scored {abs(base['delta']):.3f} below the naive baseline — soften transforms.")
    return changes, feedback
