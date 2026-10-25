"""Starts, resumes and tracks agent runs in background threads."""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from langgraph.types import Command

from ..core.config import RUNS_DIR
from ..core.events import atomic_write, bus
from ..core.settings import Settings
from .context import RunContext, get_ctx, has_ctx, register_ctx
from .graph import GRAPH


def _meta_path(run_id: str) -> Path:
    return RUNS_DIR / run_id / "meta.json"


def read_meta(run_id: str) -> dict | None:
    p = _meta_path(run_id)
    if not p.exists():
        return None
    for _ in range(5):
        try:
            return json.loads(p.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            time.sleep(0.02)  # being replaced right now
    return None


def write_meta(_run_id: str, **updates: Any) -> dict:
    run_id = _run_id
    meta = read_meta(run_id) or {}
    meta.update(updates, updated_at=time.time())
    atomic_write(_meta_path(run_id), json.dumps(meta, indent=1, default=str))
    return meta


class RunManager:
    def __init__(self) -> None:
        self._threads: dict[str, threading.Thread] = {}

    def start(self, dataset: dict, dataset_path: Path, messages: list[dict], intent: dict, settings: Settings) -> str:
        run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        ctx = RunContext(run_id=run_id, dataset_path=dataset_path, dataset_name=dataset["name"], settings=settings)
        register_ctx(ctx)
        write_meta(run_id, run_id=run_id, status="running", created_at=time.time(), dataset=dataset,
                   provider=settings.llm.provider, intent=intent, pending=None, error=None,
                   settings=settings.model_dump(exclude={"llm": {"groq_api_key", "gemini_api_key"}}))
        bus.emit(run_id, "run_started", None, f"Run started on {dataset['name']}",
                 {"provider": settings.llm.provider, "intent": intent})
        initial = {"run_id": run_id, "messages": messages, "intent": intent or {}, "decisions": [],
                   "plan_attempts": 0, "revise_loops": 0}
        self._spawn(run_id, initial)
        return run_id

    def resume(self, run_id: str, value: Any) -> None:
        meta = read_meta(run_id)
        if not meta or meta.get("status") != "waiting":
            raise ValueError("This run is not waiting for input.")
        if not has_ctx(run_id):
            raise ValueError("This run was paused before the server restarted and can't be resumed. Start a new run.")
        write_meta(run_id, status="running", pending=None)
        bus.emit(run_id, "run_resumed", None, "Resuming with your answer", value)
        self._spawn(run_id, Command(resume=value))

    def _spawn(self, run_id: str, payload: Any) -> None:
        t = threading.Thread(target=self._drive, args=(run_id, payload), daemon=True, name=f"run-{run_id}")
        self._threads[run_id] = t
        t.start()

    def _drive(self, run_id: str, payload: Any) -> None:
        cfg = {"configurable": {"thread_id": run_id}, "recursion_limit": 200}  # room for revise + self-repair loops
        try:
            for _ in GRAPH.stream(payload, cfg, stream_mode="updates"):
                pass
            state = GRAPH.get_state(cfg)
            repairs = (state.values or {}).get("repairs") or []
            pending = [i.value for t in state.tasks for i in (t.interrupts or [])]
            if state.next and pending:
                node = state.next[0]
                write_meta(run_id, status="waiting", pending={"node": node, **pending[0]})
                bus.emit(run_id, "awaiting_input", node, pending[0].get("title", "Waiting for your input"), pending[0])
            else:
                write_meta(run_id, status="completed", completed_at=time.time(), repairs=repairs)
                fixed = f" (self-repaired after {len(repairs)} attempt{'s' if len(repairs) != 1 else ''})" if repairs else ""
                bus.emit(run_id, "run_completed", None, f"Run complete — data, pipeline and insights are ready{fixed}", {"repairs": repairs})
        except Exception as e:  # node errors were already reported as node_failed
            failure = None
            try:
                failure = get_ctx(run_id).failure
            except Exception:  # noqa: BLE001
                pass
            if not failure:
                failure = {"stage": None, "label": "Agent", "error_type": e.__class__.__name__, "error": str(e)[:600],
                           "reason": f"The agent stopped unexpectedly: {str(e)[:200]}", "hint": "Start the run again. If it repeats, check the terminal for details.",
                           "attempts": [], "why_stopped": ""}
            write_meta(run_id, status="failed", error=failure["reason"], failure=failure, completed_at=time.time())
            bus.emit(run_id, "run_failed", None, f"Run failed: {failure['reason']}", failure)

    def list(self) -> list[dict]:
        runs = []
        for d in sorted(RUNS_DIR.iterdir(), reverse=True):
            meta = read_meta(d.name) if d.is_dir() else None
            if meta:
                if meta.get("status") in ("running", "waiting") and not has_ctx(d.name):
                    meta["status"] = "interrupted"
                runs.append({k: meta.get(k) for k in ("run_id", "status", "created_at", "dataset", "provider", "intent", "error")})
        return runs


manager = RunManager()
