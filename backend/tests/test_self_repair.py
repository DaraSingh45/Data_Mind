"""Self-repair: a crashing stage is diagnosed, fixed and retried up to the configured limit."""
import time

from fastapi.testclient import TestClient

import app.agent.graph as graph
from app.main import app


def _wait(c, rid, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        m = c.get(f"/api/runs/{rid}").json()["meta"]
        if m["status"] == "waiting":  # answer any question with its first option
            ans = {q["id"]: q["options"][0]["value"] for q in m["pending"].get("questions", [])}
            c.post(f"/api/runs/{rid}/resume", json={"value": {"approved": True, "answers": ans, "overrides": {}}})
        elif m["status"] != "running":
            return m
        time.sleep(0.2)
    raise AssertionError("run timed out")


def _start(c):
    ds = c.post("/api/samples/customer_churn").json()["dataset"]["id"]
    return c.post("/api/runs", json={"dataset_id": ds, "messages": [], "intent": {"target": "churn"}}).json()["run_id"]


def test_column_crash_is_found_and_fixed(monkeypatch):
    real = graph.execute_plan
    bad = {}

    def flaky(df, plan):
        cols = {c["column"]: c for c in plan["columns"]}
        if not bad:
            bad["col"] = next(c["column"] for c in plan["columns"] if c["role"] == "feature" and c.get("kind") == "numeric")
        col = cols.get(bad["col"])
        if col and col["role"] == "feature" and col.get("scale") != "robust":
            raise ValueError(f"could not convert string to float: 'N/A' in column '{bad['col']}'")
        return real(df, plan)

    monkeypatch.setattr(graph, "execute_plan", flaky)
    with TestClient(app) as c:
        rid = _start(c)
        m = _wait(c, rid)
        assert m["status"] == "completed", m.get("failure")
        rep = m["repairs"]
        assert len(rep) == 1 and rep[0]["stage"] == "execute" and rep[0]["culprits"] == [bad["col"]]
        assert "text where a number was expected" in rep[0]["reason"]
        types = [e["type"] for e in c.get(f"/api/runs/{rid}/events").json()]
        assert "node_error" in types and types[-1] == "run_completed"
        plan = c.get(f"/api/runs/{rid}").json()["result"]["plan"]
        assert next(x for x in plan["columns"] if x["column"] == bad["col"])["source"] == "repair"


def test_gives_up_after_the_limit_with_reasons(monkeypatch):
    def broken(df, plan):
        raise RuntimeError("disk exploded")

    monkeypatch.setattr(graph, "execute_plan", broken)
    with TestClient(app) as c:
        c.put("/api/settings", json={"agent": {"max_repair_attempts": 2}})
        rid = _start(c)
        m = _wait(c, rid)
        assert m["status"] == "failed"
        f = m["failure"]
        assert f["stage"] == "execute" and len(f["attempts"]) == 2 and "Gave up after 2" in f["why_stopped"]
        assert "disk exploded" in f["error"] and f["traceback"]
        assert all(a["fixes"] for a in f["attempts"])


def test_repair_off(monkeypatch):
    monkeypatch.setattr(graph, "execute_plan", lambda df, plan: (_ for _ in ()).throw(MemoryError("Unable to allocate 9 GiB")))
    with TestClient(app) as c:
        c.put("/api/settings", json={"agent": {"max_repair_attempts": 0}})
        m = _wait(c, _start(c))
        assert m["status"] == "failed" and m["failure"]["attempts"] == []
        assert "memory" in m["failure"]["reason"].lower() and "off" in m["failure"]["why_stopped"]
        c.put("/api/settings", json={"agent": {"max_repair_attempts": 2}})


def test_global_crash_does_not_drop_every_column(monkeypatch):
    def broken(df, plan):
        raise MemoryError("Unable to allocate 7 GiB")

    monkeypatch.setattr(graph, "execute_plan", broken)
    with TestClient(app) as c:
        c.put("/api/settings", json={"agent": {"max_repair_attempts": 2}})
        m = _wait(c, _start(c))
        for a in m["failure"]["attempts"]:
            assert a["culprits"] == []
            dropped = {ch.split(".role")[0] for ch in a["changes"] if "role → drop" in ch}
            assert dropped <= {"signup_date", "agent_notes"}, a["changes"]  # safe mode only drops date/text expansions
