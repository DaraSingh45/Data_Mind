"""Per-run context: settings snapshot, LLM client and cached heavy objects.

LangGraph state holds only JSON-friendly values; dataframes and fitted
pipelines live here, keyed by run id.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from ..core.config import RUNS_DIR
from ..core.events import atomic_write, bus
from ..core.settings import Settings
from .llm import LLM


@dataclass
class RunContext:
    run_id: str
    dataset_path: Path
    dataset_name: str
    settings: Settings
    run_dir: Path = field(init=False)
    llm: LLM = field(init=False)
    raw: pd.DataFrame | None = None
    profile: dict | None = None
    target_info: dict | None = None
    result: dict | None = None
    current_node: str | None = None
    failure: dict | None = None      # final failure details for the UI
    flags: dict = field(default_factory=dict)  # self-repair switches (skip_baseline, insights_safe, ...)

    def __post_init__(self) -> None:
        self.run_dir = RUNS_DIR / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.llm = LLM(self.settings, on_call=self._on_llm_call)

    # -- events -------------------------------------------------------------
    def log(self, message: str, data: Any = None) -> None:
        bus.emit(self.run_id, "node_log", self.current_node, message, data)

    def _on_llm_call(self, record: dict) -> None:
        status = "ok" if record.get("ok") else f"failed: {record.get('error', '')}"
        bus.emit(self.run_id, "llm_call", self.current_node,
                 f"{record['provider']} · {record['model']} · {record['purpose']} · {record.get('seconds')}s · {status}", record)

    # -- data ---------------------------------------------------------------
    def raw_df(self) -> pd.DataFrame:
        if self.raw is None:
            self.raw = pd.read_parquet(self.run_dir / "raw.parquet")
        return self.raw

    def profile_or_load(self) -> dict:
        if self.profile is None:
            self.profile = json.loads((self.run_dir / "profile.json").read_text("utf-8"))
        return self.profile

    def target_info_or_load(self) -> dict | None:
        if self.target_info is None and (self.run_dir / "target_info.json").exists():
            self.target_info = json.loads((self.run_dir / "target_info.json").read_text("utf-8"))
        return self.target_info

    def save_json(self, name: str, obj: Any) -> None:
        atomic_write(self.run_dir / name, json.dumps(obj, indent=1, default=str))

    def save_parquet(self, name: str, df: pd.DataFrame) -> None:
        out = df.copy()
        for c in out.columns:
            if out[c].dtype == object:
                out[c] = out[c].astype("string")
        out.to_parquet(self.run_dir / name, index=False)

    def load_parquet(self, name: str) -> pd.DataFrame:
        return pd.read_parquet(self.run_dir / name)


_contexts: dict[str, RunContext] = {}
_lock = threading.Lock()


def register_ctx(ctx: RunContext) -> None:
    with _lock:
        _contexts[ctx.run_id] = ctx


def get_ctx(run_id: str) -> RunContext:
    with _lock:
        return _contexts[run_id]


def has_ctx(run_id: str) -> bool:
    with _lock:
        return run_id in _contexts
