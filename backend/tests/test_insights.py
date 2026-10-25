import json

from app.core.settings import PrepSettings
from app.engine.executor import execute_plan
from app.engine.heuristic import build_heuristic_plan
from app.engine.profiler import target_analysis
from app.insights.engine import generate_insights
from app.insights.query import answer


def _cleaned(churn):
    df, prof = churn
    ta = target_analysis(df, "churn", "classification", prof)
    plan = build_heuristic_plan(prof, {"target": "churn", "task": "classification"}, ta, PrepSettings())
    return execute_plan(df, plan)["cleaned"], plan, prof


def test_insights_rank_contract_as_driver(churn):
    cleaned, plan, prof = _cleaned(churn)
    res = generate_insights(cleaned, plan, prof)
    json.dumps(res)
    assert res["insights"][0]["title"] == "What drives churn"
    assert any(i["title"] == "churn rate by contract" for i in res["insights"])


def test_chat_questions(churn):
    cleaned, plan, _ = _cleaned(churn)
    r = answer("churn rate by contract", cleaned, plan)
    assert r["spec"]["x"] == "contract" and "Monthly" in r["reply"]
    r = answer("average monthly charges by plan and region", cleaned, plan)
    assert r["spec"]["chart"] == "bar" and r["spec"]["color"] == "region"
    r = answer("how many customers in North", cleaned, plan)
    assert r["kpi"]["value"] == "588"
    assert answer("signups over time by month", cleaned, plan)["spec"]["chart"] == "line"
