import pandas as pd

from app.core.settings import PrepSettings
from app.engine.checks import run_checks
from app.engine.executor import execute_plan
from app.engine.heuristic import build_heuristic_plan
from app.engine.plan import apply_changes, validate_plan
from app.engine.profiler import guess_targets, infer_task, target_analysis
from datamind_transformers import build_pipeline, parse_boolean, parse_numeric


def _plan(df, prof, target="churn"):
    task = infer_task(df, target, prof)
    ta = target_analysis(df, target, task, prof) if target else None
    return build_heuristic_plan(prof, {"target": target, "task": task}, ta, PrepSettings()), ta


def test_parsers():
    assert parse_numeric(pd.Series(["₹1,200.50", "45%", "(30)", "n/a"])).round(3).tolist()[:3] == [1200.5, 0.45, -30.0]
    assert parse_boolean(pd.Series(["Yes", "no", "TRUE", "maybe"])).tolist()[:3] == [1.0, 0.0, 1.0]


def test_profile_detects_messiness(churn):
    df, prof = churn
    types = {c["name"]: c["semantic_type"] for c in prof["column_profiles"]}
    assert types["customer_id"] == "id" and types["email"] == "email"
    assert types["monthly_charges"] == "numeric" and types["signup_date"] == "datetime"
    gender = next(c for c in prof["column_profiles"] if c["name"] == "gender")
    assert gender["variants"].get("M") == "Male"
    assert prof["duplicate_rows"] == 40
    assert guess_targets(prof)[0] == "churn"


def test_leakage_flagged(churn):
    df, prof = churn
    plan, ta = _plan(df, prof)
    refund = next(c for c in plan["columns"] if c["column"] == "refund_issued")
    assert refund["role"] == "drop" and any(q["column"] == "refund_issued" for q in plan["questions"])


def test_plan_is_valid_and_whitelisted(churn):
    df, prof = churn
    plan, _ = _plan(df, prof)
    sem = {c["name"]: c["semantic_type"] for c in prof["column_profiles"]}
    assert validate_plan(plan, list(df.columns), sem)[1] == []
    bad, applied = apply_changes(plan, [{"column": "age", "field": "evil", "value": 1}, {"column": "nope", "field": "role", "value": "drop"}], "llm")
    assert applied == []
    bad["columns"][[c["column"] for c in bad["columns"]].index("plan")]["scale"] = "standard"
    assert any("scaling only applies" in e for e in validate_plan(bad, list(df.columns), sem)[1])


def test_execute_and_checks(churn):
    df, prof = churn
    plan, _ = _plan(df, prof)
    res = execute_plan(df, plan)
    assert res["stats"]["duplicates_removed"] == 40
    assert res["X_train"].isna().sum().sum() == 0
    ck = run_checks(df, plan, res)
    assert ck["summary"]["failed"] == 0
    assert ck["baseline"]["delta"] > 0  # preparation beats the naive baseline


def test_pipeline_is_reproducible_and_reusable(churn):
    df, prof = churn
    plan, _ = _plan(df, prof)
    a = execute_plan(df, plan)
    b = execute_plan(df, plan)
    pd.testing.assert_frame_equal(a["train"], b["train"])
    out = a["pipeline"].transform(df.head(20))  # raw rows in, model-ready rows out
    assert list(out.columns) == a["feature_names"]


def test_no_target_and_regression(churn):
    df, prof = churn
    plan, _ = _plan(df, prof, None)
    assert plan["task"] == "none" and execute_plan(df, plan)["stats"]["test_rows"] > 0
    plan, _ = _plan(df, prof, "total_spend")
    assert plan["task"] == "regression"
    assert build_pipeline(plan) is not None
