"""Self-repair: turn a crash into a plain-language reason, find the column that
caused it, and propose plan changes so the agent can try again.

Rules first (deterministic, offline). If an LLM is configured, the agent also
asks it for a fix and merges both; every change still goes through the plan
whitelist and validation, so a repair can never do anything a plan can't.
"""
from __future__ import annotations

import re
from typing import Any, Callable

import pandas as pd

# (pattern, plain-language reason, hint)
PATTERNS: list[tuple[str, str, str]] = [
    (r"could not convert string to float: ?'?([^'\n]*)'?",
     "A column still had text where a number was expected (value: '{0}').",
     "The column is probably a mix of numbers and words. Treat it as a category, or clean those values."),
    (r"Input (?:X |y )?contains (?:NaN|infinity|a value too large)",
     "Some values were still missing or infinite when the model step ran.",
     "Impute the column (or drop rows with a missing target) before scaling."),
    (r"Found unknown categor",
     "The test split contained categories the encoder never saw during training.",
     "Use frequency encoding or group rare categories into 'Other'."),
    (r"least populated class|only one class|n_splits=\d+ cannot be greater|should be at least|The test_size = \d+ should be greater",
     "The target has too few examples of some classes for this split.",
     "Use a random split, or merge very rare target classes."),
    (r"MemoryError|Unable to allocate|ArrayMemoryError",
     "Ran out of memory, usually because a column was one-hot encoded into thousands of features.",
     "Use frequency or target encoding for high-cardinality columns, or drop them."),
    (r"Permission denied|being used by another process|WinError 32|WinError 5",
     "An output file could not be written because it is open in another program or the folder is read-only.",
     "Close the file if it is open in Excel or another app, then try again."),
    (r"No space left on device|WinError 112",
     "The disk is full.",
     "Free some disk space and try again."),
    (r"NAType|boolean value of NA is ambiguous|Cannot cast|cannot convert|invalid literal|unsupported operand|not supported between instances",
     "A column mixed data types (for example numbers, text and blanks) in a way one step couldn't handle.",
     "Give the column one clear type: numeric, category or date."),
    (r"zero-size array|0 sample\(s\)|Found array with 0|empty",
     "A step received no rows or no features after cleaning.",
     "Too many rows or columns were dropped. Lower the missing-value drop threshold or keep more columns."),
    (r"KeyError: ?'([^']+)'",
     "The column '{0}' was expected but was not found.",
     "Check that the column exists and was not renamed or dropped earlier."),
    (r"Timeout|timed out",
     "A step took too long.",
     "Use a smaller baseline sample in Settings → Agent."),
]


def diagnose(stage: str, exc: BaseException, tb: str, columns: list[str]) -> dict[str, Any]:
    """Plain-language reason, hint and the columns mentioned in the error."""
    msg = str(exc).strip() or exc.__class__.__name__
    text = f"{msg}\n{tb}"
    reason, hint = None, None
    for pat, r, h in PATTERNS:
        m = re.search(pat, text, re.I)
        if m:
            g = m.group(1)[:60] if m.groups() and m.group(1) else ""
            reason, hint = r.format(g), h
            break
    if reason is None:
        reason = f"An unexpected error occurred in the {stage} stage: {msg[:200]}"
        hint = "The agent will try a safer plan. If it keeps failing, connect an LLM in Settings for a smarter repair."
    return {
        "stage": stage,
        "error_type": exc.__class__.__name__,
        "error": msg[:600],
        "reason": reason,
        "hint": hint,
        "columns": mentioned_columns(msg, columns),  # the message only: tracebacks are full of code words
    }


def mentioned_columns(text: str, columns: list[str]) -> list[str]:
    """Columns named in an error message: quoted ('col' / "col") or as a whole word."""
    low = text.lower()
    found: list[str] = []
    for c in sorted(columns, key=len, reverse=True):
        cl = str(c).lower()
        quoted = f"'{cl}'" in low or f'"{cl}"' in low
        word = len(cl) >= 4 and re.search(rf"(?<![\w]){re.escape(cl)}(?![\w])", low) is not None
        if (quoted or word) and not any(cl in f.lower() for f in found):
            found.append(c)
    return found[:5]


def probe_columns(raw: pd.DataFrame, plan: dict, run: Callable[[pd.DataFrame, dict], Any], sample: int = 1500) -> dict[str, str]:
    """Run the failing step with one feature at a time to find the culprit columns.
    Returns {column: error}. Cheap: a small sample and a single feature per try."""
    df = raw.sample(min(sample, len(raw)), random_state=0) if len(raw) > sample else raw
    target = plan.get("target")
    feats = [c["column"] for c in plan["columns"] if c["role"] == "feature"]
    bad: dict[str, str] = {}
    # First a control run with no features at all: if that fails too, no column is to blame.
    control = {**plan, "columns": [dict(c, role=("drop" if c["column"] != target else c["role"])) for c in plan["columns"]], "imbalance": "none"}
    try:
        run(df, control)
    except Exception:  # noqa: BLE001
        return {}
    for col in feats:
        p = {**plan, "columns": [dict(c, role=("drop" if c["column"] not in (col, target) else c["role"])) for c in plan["columns"]],
             "imbalance": "none"}
        try:
            run(df, p)
        except Exception as e:  # noqa: BLE001 - we want every failure
            bad[col] = f"{e.__class__.__name__}: {str(e)[:200]}"
    if feats and len(bad) > max(2, len(feats) // 2):
        return {}  # most columns fail alone too: the problem is global, not one column
    return bad


def _safe_changes(col: dict, why: str) -> list[dict]:
    """The most conservative treatment for one column."""
    name = col["column"]
    if col.get("kind") == "categorical":
        fields = {"impute": "constant", "outliers": "none", "encode": "frequency", "scale": "none", "rare_threshold": 0.01,
                  "text_features": False, "datetime_features": False}
    else:
        fields = {"impute": "median", "outliers": "none", "scale": "robust", "datetime_features": False, "text_features": False}
    return [{"column": name, "field": f, "value": v, "reason": f"Self-repair: {why}"} for f, v in fields.items()]


def rule_fix(failure: dict, plan: dict, history: list[dict], culprits: dict[str, str]) -> dict[str, Any]:
    """Pick plan changes for the next attempt. Escalates: safer treatment → drop the column → safe mode."""
    stage = failure["stage"]
    cols = {c["column"]: c for c in plan["columns"]}
    tried_safe = {c for h in history for c in h.get("safe_columns", [])}
    changes: list[dict] = []
    dataset: dict[str, Any] = {}
    flags: dict[str, Any] = {}
    notes: list[str] = []
    safe_cols: list[str] = []

    if stage == "export":
        notes.append("Retrying the export (files are often locked for a moment on Windows).")
        flags["wait"] = 1.5
        return {"changes": changes, "dataset": dataset, "flags": flags, "notes": notes, "safe_columns": safe_cols}
    if stage == "insights":
        flags["insights_safe"] = True
        notes.append("Re-running insights in safe mode (simpler analyses, failing ones are skipped).")
        return {"changes": changes, "dataset": dataset, "flags": flags, "notes": notes, "safe_columns": safe_cols}

    targets = [c for c in (list(culprits) or failure.get("columns") or []) if c in cols and c != plan.get("target")]
    n_feats = sum(1 for c in plan["columns"] if c["role"] == "feature")
    if len(targets) > max(2, n_feats // 3):
        targets = []  # too many to blame individually — fix the plan as a whole instead
    for c in targets:
        if c in tried_safe or cols[c].get("role") == "drop":
            changes.append({"column": c, "field": "role", "value": "drop",
                            "reason": f"Self-repair: still failed after a safer treatment ({failure['reason'][:120]})"})
            notes.append(f"Dropped '{c}' — it kept failing even with the safest treatment.")
        else:
            changes += _safe_changes(cols[c], failure["reason"][:120])
            safe_cols.append(c)
            notes.append(f"'{c}' caused the error — switched it to the safest treatment.")

    if not targets:
        # not tied to a column: make the whole plan more conservative
        level = sum(1 for h in history if not h.get("culprits"))
        dataset["imbalance"] = "none"
        if plan.get("split", {}).get("strategy") != "random":
            dataset["split"] = {"strategy": "random"}
        for c in plan["columns"]:
            if c["role"] != "feature":
                continue
            if c.get("encode") in ("target", "onehot", "ordinal") and (level >= 1 or c.get("encode") == "target"):
                changes.append({"column": c["column"], "field": "encode", "value": "frequency", "reason": "Self-repair: safer encoding."})
            if c.get("outliers") not in (None, "none"):
                changes.append({"column": c["column"], "field": "outliers", "value": "none", "reason": "Self-repair: no outlier step."})
            if level >= 1 and (c.get("text_features") or c.get("datetime_features")):
                changes.append({"column": c["column"], "field": "role", "value": "drop", "reason": "Self-repair: safe mode drops text/date expansions."})
        if stage == "checks":
            flags["skip_baseline"] = True
            notes.append("Skipping the baseline model in quality checks.")
        notes.append("No single column was to blame — using a more conservative plan"
                     + (" (safe mode)." if level >= 1 else ": random split, simpler encodings, no outlier step."))
    return {"changes": changes, "dataset": dataset, "flags": flags, "notes": notes, "safe_columns": safe_cols}
