"""Executes a validated plan: clean, split, fit on train only, transform."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from datamind_transformers import Cleaner, build_pipeline


def execute_plan(raw: pd.DataFrame, plan: dict) -> dict[str, Any]:
    log: list[str] = []
    target = plan.get("target")
    task = plan.get("task", "none")

    cleaned = Cleaner(plan).transform(raw)
    log.append(f"Type repair and category cleanup applied to {cleaned.shape[1]} kept columns.")
    keep = pd.Series(True, index=raw.index)
    n_dups = 0
    if plan.get("drop_duplicates"):
        dup = raw.duplicated()
        n_dups = int(dup.sum())
        keep &= ~dup
        log.append(f"Removed {n_dups} duplicate rows.")
    n_missing_target = 0
    if target:
        miss = cleaned[target].isna()
        n_missing_target = int((miss & keep).sum())
        keep &= ~miss
        if n_missing_target:
            log.append(f"Removed {n_missing_target} rows with a missing target.")
    idx = raw.index[keep]

    split = plan.get("split", {})
    strategy = split.get("strategy", "random")
    test_size = float(split.get("test_size", 0.2))
    seed = int(split.get("seed", 42))
    if strategy == "none" or len(idx) < 10:
        train_idx, test_idx = idx, idx[:0]
    elif strategy == "time" and split.get("time_column"):
        t = cleaned.loc[idx, split["time_column"]]
        order = t.sort_values(kind="stable").index
        cut = int(len(order) * (1 - test_size))
        train_idx, test_idx = order[:cut], order[cut:]
        log.append(f"Time split on '{split['time_column']}': test set is the most recent {test_size:.0%}.")
    else:
        strat = None
        if strategy == "stratified" and target:
            y_s = cleaned.loc[idx, target].astype("string")
            if y_s.value_counts().min() >= 2:
                strat = y_s
            else:
                log.append("A class has fewer than 2 rows — fell back to a random split.")
        train_idx, test_idx = train_test_split(idx, test_size=test_size, random_state=seed, stratify=strat)
        log.append(f"{'Stratified' if strat is not None else 'Random'} split: {len(train_idx)} train / {len(test_idx)} test rows.")

    y_train = cleaned.loc[train_idx, target] if target else None
    y_test = cleaned.loc[test_idx, target] if target else None
    y_fit = None
    if target:
        y_fit = y_train.astype("string") if task == "classification" else y_train.astype("float64")
        if task == "classification":
            y_fit = y_fit.astype(object)

    pipe = build_pipeline(plan)
    X_train = pipe.fit_transform(raw.loc[train_idx], y_fit)
    log.append(f"Pipeline fitted on the {len(train_idx)} training rows only (no test-set leakage).")
    X_test = pipe.transform(raw.loc[test_idx]) if len(test_idx) else X_train.iloc[:0]
    X_train.index, X_test.index = train_idx, test_idx

    oversampled = 0
    if target and plan.get("imbalance") == "oversample" and task == "classification":
        vc = y_train.astype("string").value_counts()
        rng = np.random.default_rng(seed)
        parts_X, parts_y = [X_train], [y_train]
        for cls, cnt in vc.items():
            need = int(vc.max() - cnt)
            if need > 0:
                pool = y_train.index[y_train.astype("string") == cls]
                pick = rng.choice(pool, size=need, replace=True)
                parts_X.append(X_train.loc[pick])
                parts_y.append(y_train.loc[pick])
                oversampled += need
        if oversampled:
            X_train = pd.concat(parts_X)
            y_train = pd.concat(parts_y)
            log.append(f"Oversampled minority classes with {oversampled} extra training rows (test set untouched).")

    train_out = X_train.copy()
    test_out = X_test.copy()
    if target:
        train_out[target] = y_train.values
        test_out[target] = y_test.values

    return {
        "pipeline": pipe,
        "cleaned": cleaned.loc[idx],
        "train": train_out.reset_index(drop=True),
        "test": test_out.reset_index(drop=True),
        "X_train": X_train, "X_test": X_test, "y_train": y_train, "y_test": y_test,
        "feature_names": list(X_train.columns),
        "stats": {
            "raw_rows": int(len(raw)), "duplicates_removed": n_dups, "missing_target_removed": n_missing_target,
            "train_rows": int(len(train_idx)), "test_rows": int(len(test_idx)), "oversampled_rows": oversampled,
            "features_out": int(X_train.shape[1]), "columns_in": int(raw.shape[1]),
            "columns_dropped": [c["column"] for c in plan["columns"] if c.get("role") == "drop"],
        },
        "log": log,
    }
