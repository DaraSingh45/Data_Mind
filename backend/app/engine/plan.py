"""The preparation plan: a strict, whitelisted schema.

The LLM can only ever *propose* values for these fields. Anything outside the
schema is rejected by ``validate_plan`` before a single row is touched.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

Role = Literal["feature", "target", "drop"]
Kind = Literal["numeric", "categorical"]
DtypeFix = Optional[Literal["numeric", "datetime", "boolean", "category", "text"]]
Impute = Literal["none", "mean", "median", "most_frequent", "constant"]
Outliers = Literal["none", "clip_iqr", "winsorize", "log1p"]
Encode = Literal["none", "onehot", "ordinal", "frequency", "target"]
Scale = Literal["none", "standard", "robust", "minmax"]
Task = Literal["classification", "regression", "none"]

EDITABLE_FIELDS = {
    "role", "kind", "dtype_fix", "normalize_text", "category_map", "impute", "add_missing_flag",
    "outliers", "encode", "rare_threshold", "scale", "datetime_features", "text_features",
}


class ColumnPlan(BaseModel):
    column: str
    role: Role = "feature"
    kind: Kind = "numeric"
    semantic_type: str = "numeric"
    dtype_fix: DtypeFix = None
    normalize_text: bool = False
    category_map: dict[str, str] = Field(default_factory=dict)
    impute: Impute = "median"
    add_missing_flag: bool = False
    outliers: Outliers = "none"
    encode: Encode = "none"
    rare_threshold: float = Field(0.0, ge=0.0, le=0.5)
    scale: Scale = "none"
    datetime_features: bool = False
    text_features: bool = False
    reason: str = ""
    confidence: float = Field(0.9, ge=0.0, le=1.0)
    source: Literal["heuristic", "llm", "user", "verifier", "repair"] = "heuristic"


class SplitPlan(BaseModel):
    strategy: Literal["stratified", "random", "time", "none"] = "random"
    test_size: float = Field(0.2, gt=0.0, lt=0.9)
    time_column: Optional[str] = None
    seed: int = 42


class Question(BaseModel):
    id: str
    question: str
    options: list[str] = Field(default_factory=list)
    column: Optional[str] = None
    default: Optional[str] = None


class Plan(BaseModel):
    target: Optional[str] = None
    task: Task = "none"
    drop_duplicates: bool = True
    split: SplitPlan = Field(default_factory=SplitPlan)
    imbalance: Literal["none", "oversample"] = "none"
    columns: list[ColumnPlan]
    notes: list[str] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)


def validate_plan(plan_dict: dict, column_names: list[str], semantic: dict[str, str]) -> tuple[Plan | None, list[str]]:
    """Schema + logic checks. Returns (plan, errors)."""
    errors: list[str] = []
    try:
        plan = Plan.model_validate(plan_dict)
    except ValidationError as e:
        for err in e.errors()[:12]:
            loc = ".".join(str(p) for p in err["loc"])
            errors.append(f"{loc}: {err['msg']}")
        return None, errors

    names = [c.column for c in plan.columns]
    unknown = set(names) - set(column_names)
    if unknown:
        errors.append(f"unknown columns in plan: {sorted(unknown)}")
    missing = set(column_names) - set(names)
    if missing:
        errors.append(f"plan does not cover columns: {sorted(missing)}")
    if len(names) != len(set(names)):
        errors.append("a column appears more than once in the plan")
    if plan.target:
        if plan.target not in column_names:
            errors.append(f"target '{plan.target}' is not a column")
        tcol = next((c for c in plan.columns if c.column == plan.target), None)
        if tcol and tcol.role != "target":
            errors.append(f"target column '{plan.target}' must have role 'target'")
        if plan.task == "none":
            errors.append("a target is set but task is 'none'")
    else:
        if any(c.role == "target" for c in plan.columns):
            errors.append("a column has role 'target' but no target is set")
        if plan.split.strategy == "stratified":
            errors.append("stratified split needs a classification target")
    if plan.split.strategy == "time":
        if not plan.split.time_column or semantic.get(plan.split.time_column) != "datetime":
            errors.append("time split needs a datetime time_column")
    if plan.task != "classification" and plan.split.strategy == "stratified":
        errors.append("stratified split is only valid for classification")
    if plan.task != "classification" and plan.imbalance != "none":
        errors.append("imbalance handling is only valid for classification")

    for c in plan.columns:
        st = semantic.get(c.column, "")
        if c.role != "feature":
            continue
        if c.datetime_features and st != "datetime":
            errors.append(f"{c.column}: datetime_features on a non-datetime column")
        if c.dtype_fix == "numeric" and st not in ("numeric", "boolean"):
            errors.append(f"{c.column}: cannot convert {st} column to numeric")
        if c.kind == "numeric" and c.encode not in ("none",):
            errors.append(f"{c.column}: numeric columns cannot be encoded")
        if c.kind == "categorical" and c.encode == "none" and not (c.datetime_features or c.text_features):
            errors.append(f"{c.column}: categorical column needs an encoding")
        if c.kind == "categorical" and c.scale != "none":
            errors.append(f"{c.column}: scaling only applies to numeric columns")
        if c.encode == "target" and plan.task == "none":
            errors.append(f"{c.column}: target encoding needs a target")
        if c.kind == "numeric" and c.impute == "none" and st == "numeric":
            pass  # pipeline guarantees a median fallback
    return (plan if not errors else None), errors


def apply_changes(plan_dict: dict, changes: list[dict], source: str) -> tuple[dict, list[str]]:
    """Apply proposed field changes [{column, field, value, reason}] to a plan.
    Only whitelisted fields can change. Returns (new_plan, applied_descriptions)."""
    cols = {c["column"]: c for c in plan_dict["columns"]}
    applied: list[str] = []
    for ch in changes or []:
        col, field, value = ch.get("column"), ch.get("field"), ch.get("value")
        if col not in cols or field not in EDITABLE_FIELDS:
            continue
        if cols[col].get(field) == value:
            continue
        cols[col][field] = value
        if ch.get("reason"):
            cols[col]["reason"] = str(ch["reason"])[:300]
        cols[col]["source"] = source
        applied.append(f"{col}.{field} → {value}")
    return plan_dict, applied


def apply_dataset_changes(plan_dict: dict, changes: dict) -> list[str]:
    applied = []
    for key in ("drop_duplicates", "imbalance", "target", "task"):
        if key in (changes or {}) and plan_dict.get(key) != changes[key]:
            plan_dict[key] = changes[key]
            applied.append(f"{key} → {changes[key]}")
    if isinstance((changes or {}).get("split"), dict):
        for k, v in changes["split"].items():
            if k in ("strategy", "test_size", "time_column", "seed") and plan_dict["split"].get(k) != v:
                plan_dict["split"][k] = v
                applied.append(f"split.{k} → {v}")
    return applied


def plan_json_schema() -> dict[str, Any]:
    return Plan.model_json_schema()
