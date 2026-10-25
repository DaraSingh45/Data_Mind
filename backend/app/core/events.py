"""In-process event bus. Every agent step publishes events here; the API streams
them to the browser over Server-Sent Events and saves them for replay."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .config import RUNS_DIR


@dataclass
class RunEvents:
    events: list[dict] = field(default_factory=list)
    cond: threading.Condition = field(default_factory=threading.Condition)


class EventBus:
    def __init__(self) -> None:
        self._runs: dict[str, RunEvents] = {}
        self._lock = threading.Lock()

    def _get(self, run_id: str) -> RunEvents:
        with self._lock:
            if run_id not in self._runs:
                self._runs[run_id] = RunEvents()
                path = RUNS_DIR / run_id / "events.jsonl"
                if path.exists():  # reload after a server restart
                    for line in path.read_text("utf-8").splitlines():
                        if line.strip():
                            self._runs[run_id].events.append(json.loads(line))
            return self._runs[run_id]

    def emit(self, run_id: str, type: str, node: str | None = None, message: str = "", data: Any = None) -> dict:
        rec = self._get(run_id)
        with rec.cond:
            event = {
                "seq": len(rec.events),
                "ts": time.time(),
                "type": type,
                "node": node,
                "message": message,
                "data": data,
            }
            rec.events.append(event)
            rec.cond.notify_all()
        path = RUNS_DIR / run_id / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")
        return event

    def since(self, run_id: str, after: int, timeout: float = 15.0) -> list[dict]:
        """Events with seq > after; blocks up to ``timeout`` waiting for new ones."""
        rec = self._get(run_id)
        with rec.cond:
            if len(rec.events) <= after + 1:
                rec.cond.wait(timeout)
            return rec.events[after + 1 :]

    def all(self, run_id: str) -> list[dict]:
        return list(self._get(run_id).events)


bus = EventBus()


def atomic_write(path, text: str) -> None:
    """Write a file so readers never see it half-written (write to a temp file, then swap)."""
    import os
    from pathlib import Path

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text, "utf-8")
    os.replace(tmp, path)
