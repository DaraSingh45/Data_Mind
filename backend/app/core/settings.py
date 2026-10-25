"""User-configurable settings.

* API keys, the LLM provider and model names live in ``backend/.env``
  (see ``.env.example``). They are never written to settings.json.
* Everything else (privacy, agent behaviour, preparation defaults, theme)
  is stored in ``data/settings.json``.
* Keys are masked whenever settings are sent to the browser.
"""
from __future__ import annotations

import json
import threading
from typing import Any, Literal

from pydantic import BaseModel, Field

from .config import SETTINGS_FILE
from .env import ENV_FILE, env, write_env

MASK = "••••••••"
_lock = threading.Lock()

Provider = Literal["heuristic", "ollama", "groq", "gemini"]

# LLM fields whose source of truth is the .env file
ENV_FIELDS = {
    "provider": "DATAMIND_LLM_PROVIDER",
    "ollama_base_url": "OLLAMA_BASE_URL",
    "ollama_model": "OLLAMA_MODEL",
    "groq_api_key": "GROQ_API_KEY",
    "groq_model": "GROQ_MODEL",
    "gemini_api_key": "GEMINI_API_KEY",
    "gemini_model": "GEMINI_MODEL",
}
SECRET_FIELDS = ("groq_api_key", "gemini_api_key")


class LLMSettings(BaseModel):
    provider: Provider = "heuristic"
    fallback_order: list[Provider] = Field(default_factory=lambda: ["ollama", "groq", "gemini"])
    use_fallback: bool = True
    temperature: float = 0.1
    timeout_seconds: int = 90
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"


class PrivacySettings(BaseModel):
    # The LLM always sees statistics only. These control whether a few distinct
    # category labels (needed to merge spelling variants) may be included.
    share_labels_with_local: bool = True
    share_labels_with_cloud: bool = False
    max_labels_per_column: int = 12


class AgentSettings(BaseModel):
    human_review: Literal["always", "on_uncertainty", "never"] = "on_uncertainty"
    max_plan_retries: int = 2
    max_revise_loops: int = 1
    max_repair_attempts: int = Field(2, ge=0, le=5)  # self-repair: retries after a stage crashes (0 = off)
    run_baseline_model: bool = True
    baseline_max_rows: int = 20000


class PrepSettings(BaseModel):
    model_family: Literal["auto", "tree", "linear"] = "auto"
    test_size: float = 0.2
    random_seed: int = 42
    drop_missing_threshold: float = 0.6
    max_onehot_categories: int = 15
    rare_category_threshold: float = 0.01
    outlier_strategy: Literal["auto", "clip_iqr", "winsorize", "log1p", "none"] = "auto"
    scaling: Literal["auto", "standard", "robust", "minmax", "none"] = "auto"
    imbalance: Literal["auto", "none", "oversample"] = "auto"
    add_missing_flags: bool = True
    drop_duplicates: bool = True


class InsightSettings(BaseModel):
    max_insights: int = 12
    significance_level: float = 0.05
    narrative: bool = True


class UISettings(BaseModel):
    theme: Literal["dark", "light", "system"] = "dark"
    animation_speed: float = 1.0
    reduce_motion: bool = False
    pace_runs: bool = True  # play live runs at a readable pace instead of instantly


class Settings(BaseModel):
    llm: LLMSettings = Field(default_factory=LLMSettings)
    privacy: PrivacySettings = Field(default_factory=PrivacySettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    prep: PrepSettings = Field(default_factory=PrepSettings)
    insights: InsightSettings = Field(default_factory=InsightSettings)
    ui: UISettings = Field(default_factory=UISettings)


def load_settings() -> Settings:
    with _lock:
        data: dict[str, Any] = {}
        if SETTINGS_FILE.exists():
            try:
                data = json.loads(SETTINGS_FILE.read_text("utf-8"))
            except Exception:  # corrupt file -> defaults, keep a backup
                SETTINGS_FILE.rename(SETTINGS_FILE.with_suffix(".bak"))
        llm = data.setdefault("llm", {})
        defaults = LLMSettings()
        for field, var in ENV_FIELDS.items():
            llm[field] = env(var, getattr(defaults, field)) or getattr(defaults, field)
        if llm.get("provider") not in ("heuristic", "ollama", "groq", "gemini"):
            llm["provider"] = "heuristic"
        try:
            return Settings.model_validate(data)
        except Exception:
            return Settings()


def save_settings(settings: Settings) -> None:
    """LLM provider/models/keys go to .env; the rest to settings.json."""
    data = settings.model_dump()
    env_updates = {var: str(data["llm"][field]) for field, var in ENV_FIELDS.items()}
    current = {var: env(var) for var in env_updates}
    changed = {k: v for k, v in env_updates.items() if current.get(k, "") != v}
    if changed:
        write_env(changed)
    for field in ENV_FIELDS:
        data["llm"].pop(field, None)
    with _lock:
        SETTINGS_FILE.write_text(json.dumps(data, indent=2), "utf-8")


def public_settings(settings: Settings) -> dict[str, Any]:
    """Settings safe to send to the browser (keys masked)."""
    data = settings.model_dump()
    for key in SECRET_FIELDS:
        data["llm"][key] = MASK if data["llm"][key] else ""
    data["env_file"] = str(ENV_FILE)
    return data


def merge_update(current: Settings, incoming: dict[str, Any]) -> Settings:
    """Apply a partial update from the UI, keeping existing keys when masked."""
    data = current.model_dump()
    for section, values in (incoming or {}).items():
        if section in data and isinstance(values, dict):
            for k, v in values.items():
                if k in SECRET_FIELDS and v == MASK:
                    continue
                data[section][k] = v
    return Settings.model_validate(data)


def dump(obj: Any) -> str:
    return json.dumps(obj, default=str)
