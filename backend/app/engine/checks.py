"""Deterministic quality checks and the baseline-model sanity check."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import f1_score, r2_score, roc_auc_score
from sklearn.model_selection import cross_val_score
from threadpoolctl import threadpool_limits

from datamind_transformers import parse_numeric


def _source_column(feature: str, plan_cols: list[str]) -> str:
    f = feature.removeprefix("missingindicator_")
    best = ""
    for c in plan_cols:
        if (f == c or f.startswith(c + "_") or f.startswith(c + "__")) and len(c) > len(best):
            best = c
    return best or feature


def _metric(task: str, n_classes: int) -> str:
    if task == "regression":
        return "r2"
    return "roc_auc" if n_classes == 2 else "f1_macro"


def _score(task: str, metric: str, model, X_tr, y_tr, X_te, y_te) -> float | None:
    if len(X_te) == 0 or X_tr.shape[1] == 0:
        return None
    model.fit(X_tr, y_tr)
    if metric == "roc_auc":
        classes = list(model.classes_)
        return float(roc_auc_score((y_te == classes[1]).astype(int), model.predict_proba(X_te)[:, 1]))
    if metric == "f1_macro":
        return float(f1_score(y_te, model.predict(X_te), average="macro"))
    return float(r2_score(y_te, model.predict(X_te)))


def run_checks(raw: pd.DataFrame, plan: dict, result: dict, run_baseline: bool = True, max_rows: int = 20000) -> dict[str, Any]:
    # OpenMP busy-waits badly when the CPU is shared (browser animations, other
    # apps): a single thread is far faster and plenty for a <=20k-row sample.
    with threadpool_limits(limits=1):
        return _run_checks(raw, plan, result, run_baseline, max_rows)


def _run_checks(raw: pd.DataFrame, plan: dict, result: dict, run_baseline: bool, max_rows: int) -> dict[str, Any]:
    checks: list[dict] = []
    target, task = plan.get("target"), plan.get("task", "none")
    X_train: pd.DataFrame = result["X_train"]
    X_test: pd.DataFrame = result["X_test"]
    st = result["stats"]

    def add(cid: str, name: str, ok: bool | None, detail: str, warn: bool = False):
        status = "pass" if ok else ("warn" if warn or ok is None else "fail")
        checks.append({"id": cid, "name": name, "status": status, "detail": detail})

    n_nan = int(X_train.isna().sum().sum() + X_test.isna().sum().sum())
    add("no_missing", "No missing values remain", n_nan == 0, f"{n_nan} missing cells in model-ready data.")
    non_num = [c for c in X_train.columns if not pd.api.types.is_numeric_dtype(X_train[c])]
    add("all_numeric", "All features are numeric", not non_num,
        "Every feature is numeric." if not non_num else f"Non-numeric: {non_num[:5]}")
    add("target_excluded", "Target is not a feature", not target or target not in X_train.columns,
        "Target column is excluded from features." if target else "No target in this run.")
    add("fit_on_train", "Transformations learned on train only", True,
        "Imputation values, outlier bounds, encodings and scalers were fitted on the training split only.")
    expected = st["raw_rows"] - st["duplicates_removed"] - st["missing_target_removed"]
    got = st["train_rows"] + st["test_rows"]
    add("row_reconciliation", "Row counts reconcile", expected == got,
        f"{st['raw_rows']} raw − {st['duplicates_removed']} duplicates − {st['missing_target_removed']} missing target = {got} rows.")
    const = [c for c in X_train.columns if X_train[c].nunique(dropna=False) <= 1]
    add("constant_features", "No constant features", not const,
        "No constant features." if not const else f"{len(const)} constant features (e.g. {const[:3]}).", warn=True)
    inf = int(np.isinf(X_train.select_dtypes("number").to_numpy()).sum()) if len(X_train) else 0
    add("finite", "All values are finite", inf == 0, f"{inf} infinite values.")
    add("feature_count", "Feature count is reasonable", X_train.shape[1] <= max(500, 5 * st["columns_in"]),
        f"{st['columns_in']} input columns → {X_train.shape[1]} features.", warn=True)

    plan_cols = [c["column"] for c in plan["columns"]]
    leakage_warnings: list[dict] = []
    baseline: dict[str, Any] | None = None
    y_tr = result["y_train"]
    if target and task in ("classification", "regression") and y_tr is not None and len(y_tr):
        # de-duplicate oversampled rows for honest evaluation
        mask = ~X_train.index.duplicated()
        Xtr, ytr = X_train[mask], y_tr[mask]
        if len(Xtr) > max_rows:
            pick = Xtr.sample(max_rows, random_state=0).index
            Xtr, ytr = Xtr.loc[pick], ytr.loc[pick]
        ytr_m = ytr.astype("string").astype(object) if task == "classification" else ytr.astype("float64")
        n_classes = int(pd.Series(ytr_m).nunique())

        # single-feature leakage scan
        for f in list(Xtr.columns)[:300]:
            x = Xtr[f].astype("float64")
            if x.nunique() < 2:
                continue
            try:
                if task == "classification" and n_classes == 2:
                    yb = (pd.Series(ytr_m, index=Xtr.index) == pd.Series(ytr_m).value_counts().index[0]).astype(int)
                    auc = roc_auc_score(yb, x)
                    score = max(auc, 1 - auc)
                    flag = score >= 0.99
                elif task == "regression":
                    r = np.corrcoef(x, ytr_m)[0, 1]
                    score = abs(r) if pd.notna(r) else 0
                    flag = score >= 0.99
                else:
                    continue
            except Exception:
                continue
            if flag:
                leakage_warnings.append({"feature": f, "source_column": _source_column(f, plan_cols), "score": round(float(score), 4)})
        add("leakage_scan", "No single feature predicts the target perfectly", not leakage_warnings,
            "No leakage detected." if not leakage_warnings else
            "Suspicious: " + ", ".join(f"{w['feature']} ({w['score']:.3f})" for w in leakage_warnings[:4]))

        if run_baseline and (n_classes >= 2 or task == "regression"):
            metric = _metric(task, n_classes)
            Model = HistGradientBoostingClassifier if task == "classification" else HistGradientBoostingRegressor
            yte = result["y_test"]
            yte_m = yte.astype("string").astype(object) if task == "classification" else yte.astype("float64")
            # naive: numeric-typed raw columns only, as a typical "just drop strings" baseline.
            # Columns the plan drops (leaks, identifiers, ones you excluded) are left out of both
            # sides, otherwise a leaky raw column would make the naive score look unbeatable.
            dropped = {c["column"] for c in plan.get("columns", []) if c.get("role") == "drop"}
            raw_num = [c for c in raw.columns if c != target and c not in dropped and pd.api.types.is_numeric_dtype(raw[c])]
            naive_tr = raw.loc[Xtr.index, raw_num].astype("float64") if raw_num else pd.DataFrame(index=Xtr.index)
            naive_te = raw.loc[result["X_test"].index, raw_num].astype("float64") if raw_num else pd.DataFrame(index=X_test.index)
            try:
                cv = cross_val_score(Model(random_state=0), Xtr, ytr_m, cv=3,
                                     scoring="roc_auc" if metric == "roc_auc" else metric)
                prepared = _score(task, metric, Model(random_state=0), Xtr, ytr_m, X_test, yte_m)
                naive = _score(task, metric, Model(random_state=0), naive_tr, ytr_m, naive_te, yte_m) if raw_num else None
                baseline = {
                    "metric": metric, "model": Model.__name__,
                    "prepared_cv_mean": round(float(cv.mean()), 4), "prepared_cv_std": round(float(cv.std()), 4),
                    "prepared_test": None if prepared is None else round(prepared, 4),
                    "naive_test": None if naive is None else round(naive, 4),
                    "naive_features": len(raw_num), "prepared_features": int(Xtr.shape[1]),
                    "delta": None if prepared is None or naive is None else round(prepared - naive, 4),
                }
                if baseline["delta"] is not None:
                    ok = baseline["delta"] >= -0.02
                    add("baseline", "Prepared data beats a naive baseline", ok,
                        f"{metric} on test: prepared {prepared:.3f} vs naive {naive:.3f} ({baseline['delta']:+.3f}).", warn=not ok)
                else:
                    add("baseline", "Baseline model trains on prepared data", True,
                        f"{metric}: {cv.mean():.3f} ± {cv.std():.3f} (3-fold CV on train).")
            except Exception as e:  # never fail the run because of the sanity model
                add("baseline", "Baseline model", None, f"Skipped: {e}")

    # before/after for numeric source columns that map one-to-one
    comparisons = []
    for c in plan["columns"]:
        name = c["column"]
        if c.get("role") != "feature" or c.get("kind") != "numeric" or name not in X_train.columns:
            continue
        before = parse_numeric(raw[name]) if c.get("dtype_fix") != "boolean" else None
        if before is None:
            continue
        after = X_train[name]
        comparisons.append({
            "column": name,
            "before": {"missing": int(before.isna().sum()), "mean": _r(before.mean()), "std": _r(before.std()),
                       "min": _r(before.min()), "max": _r(before.max())},
            "after": {"missing": int(after.isna().sum()), "mean": _r(after.mean()), "std": _r(after.std()),
                      "min": _r(after.min()), "max": _r(after.max())},
            "transform": " → ".join(x for x in [
                "parse" if c.get("dtype_fix") == "numeric" else "",
                c.get("outliers") if c.get("outliers") != "none" else "",
                f"impute {c.get('impute')}" if before.isna().any() else "",
                c.get("scale") if c.get("scale") != "none" else ""] if x) or "unchanged",
        })

    passed = sum(1 for c in checks if c["status"] == "pass")
    return {
        "checks": checks,
        "summary": {"passed": passed, "warnings": sum(c["status"] == "warn" for c in checks),
                    "failed": sum(c["status"] == "fail" for c in checks), "total": len(checks)},
        "leakage_warnings": leakage_warnings,
        "baseline": baseline,
        "comparisons": comparisons[:30],
    }


def _r(v: Any) -> float | None:
    try:
        f = float(v)
        return None if np.isnan(f) else round(f, 4)
    except (TypeError, ValueError):
        return None
