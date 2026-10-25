import time

from fastapi.testclient import TestClient

from app.main import app


def _wait(c, rid, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        m = c.get(f"/api/runs/{rid}").json()["meta"]
        if m["status"] != "running":
            return m
        time.sleep(0.2)
    raise AssertionError("run timed out")


def test_full_run_asks_only_when_unclear():
    with TestClient(app) as c:
        ds = c.post("/api/samples/customer_churn").json()["dataset"]["id"]
        rid = c.post("/api/runs", json={"dataset_id": ds, "messages": [], "intent": {}}).json()["run_id"]
        m = _wait(c, rid)
        # 1) goal unclear -> one question card with options + Other
        assert m["status"] == "waiting" and m["pending"]["kind"] == "questions"
        q = m["pending"]["questions"][0]
        assert q["id"] == "target" and q["allow_other"] and q["options"][0]["value"] == "churn"
        # answer with free text through "Other"
        c.post(f"/api/runs/{rid}/resume", json={"value": {"answers": {"target": "I want to predict churn"}}})
        m = _wait(c, rid)
        # 2) a leaky column -> a question card, not a plan table
        assert m["pending"]["kind"] == "questions"
        ids = [q["id"] for q in m["pending"]["questions"]]
        assert ids == ["leak:refund_issued"]
        c.post(f"/api/runs/{rid}/resume", json={"value": {"answers": {"leak:refund_issued": "It is filled in after the customer leaves"}}})
        m = _wait(c, rid)
        assert m["status"] == "completed", m.get("error")
        detail = c.get(f"/api/runs/{rid}").json()
        assert detail["result"]["plan"]["target"] == "churn"
        refund = next(col for col in detail["result"]["plan"]["columns"] if col["column"] == "refund_issued")
        assert refund["role"] == "drop"
        assert c.get(f"/api/runs/{rid}/files/datamind_outputs.zip").status_code == 200
        assert len(c.get(f"/api/runs/{rid}/insights").json()["insights"]) > 5
        types = [e["type"] for e in c.get(f"/api/runs/{rid}/events").json()]
        assert types[0] == "run_started" and types[-1] == "run_completed" and types.count("awaiting_input") == 2


def test_clear_goal_runs_without_target_question():
    with TestClient(app) as c:
        ds = c.post("/api/samples/customer_churn").json()["dataset"]["id"]
        rid = c.post("/api/runs", json={"dataset_id": ds, "messages": [], "intent": {"target": "churn"}}).json()["run_id"]
        m = _wait(c, rid)
        assert m["pending"]["questions"][0]["id"].startswith("leak:")  # only the genuinely unclear thing is asked
        c.post(f"/api/runs/{rid}/resume", json={"value": {"answers": {"leak:refund_issued": "Keep it (it is available at prediction time)"}}})
        m = _wait(c, rid)
        assert m["status"] == "completed"
        refund = next(col for col in c.get(f"/api/runs/{rid}").json()["result"]["plan"]["columns"] if col["column"] == "refund_issued")
        assert refund["role"] == "feature" and refund["source"] == "user"


def test_database_import_and_read_only():
    with TestClient(app) as c:
        url = c.post("/api/samples/retail_db").json()["database_url"]
        joins = c.post("/api/db/joins", json={"url": url, "tables": ["orders", "customers", "products"]}).json()["joins"]
        assert len(joins) == 2
        r = c.post("/api/db/import", json={"url": url, "base": "orders", "joins": joins})
        assert r.status_code == 200 and r.json()["dataset"]["rows"] == 4000
        assert c.post("/api/db/preview", json={"url": url, "sql": "DROP TABLE orders"}).status_code == 400


def test_settings_mask_keys():
    with TestClient(app) as c:
        from app.core.env import ENV_FILE, read_env_file
        from app.core.settings import load_settings
        c.put("/api/settings", json={"llm": {"groq_api_key": "gsk_secret"}})
        assert c.get("/api/settings").json()["settings"]["llm"]["groq_api_key"] == "••••••••"
        c.put("/api/settings", json={"llm": {"groq_api_key": "••••••••", "temperature": 0.2}})
        assert load_settings().llm.groq_api_key == "gsk_secret"
        assert read_env_file(ENV_FILE)["GROQ_API_KEY"] == "gsk_secret"  # stored in .env …
        from app.core.config import SETTINGS_FILE
        assert "gsk_secret" not in SETTINGS_FILE.read_text()  # … never in settings.json
        c.put("/api/settings", json={"llm": {"groq_api_key": ""}})
