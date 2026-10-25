"""One interface over Ollama (local), Groq and Gemini (cloud) via LangChain.

``complete_json`` asks for a JSON object and returns ``None`` when the
provider is 'heuristic' or every configured provider failed — callers then
fall back to the rule-based engine, so a run never depends on an LLM.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

import httpx
from langchain_core.messages import HumanMessage, SystemMessage

from ..core.settings import LLMSettings, Settings

LOCAL_PROVIDERS = {"ollama"}


def extract_json(text: str) -> dict | None:
    """Parse the first JSON object in a model reply (tolerates ```json fences)."""
    if not text:
        return None
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.M)
    try:
        val = json.loads(text)
        return val if isinstance(val, dict) else {"items": val}
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    depth = 0
    for i in range(start, len(text)) if start >= 0 else []:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _model(provider: str, cfg: LLMSettings):
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(model=cfg.ollama_model, base_url=cfg.ollama_base_url, temperature=cfg.temperature,
                          format="json", num_predict=2048, client_kwargs={"timeout": cfg.timeout_seconds})
    if provider == "groq":
        from langchain_groq import ChatGroq

        if not cfg.groq_api_key:
            raise RuntimeError("Groq API key is not set (Settings → Models).")
        return ChatGroq(model=cfg.groq_model, api_key=cfg.groq_api_key, temperature=cfg.temperature,
                        request_timeout=cfg.timeout_seconds, max_retries=1, max_tokens=2048,
                        model_kwargs={"response_format": {"type": "json_object"}})
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        if not cfg.gemini_api_key:
            raise RuntimeError("Gemini API key is not set (Settings → Models).")
        return ChatGoogleGenerativeAI(model=cfg.gemini_model, google_api_key=cfg.gemini_api_key,
                                      temperature=cfg.temperature, timeout=cfg.timeout_seconds, max_retries=1,
                                      response_mime_type="application/json")
    raise ValueError(f"unknown provider {provider}")


def model_label(provider: str, cfg: LLMSettings) -> str:
    return {"ollama": cfg.ollama_model, "groq": cfg.groq_model, "gemini": cfg.gemini_model}.get(provider, "rules")


class LLM:
    def __init__(self, settings: Settings, on_call: Callable[[dict], None] | None = None):
        self.settings = settings
        self.cfg = settings.llm
        self.on_call = on_call
        self.calls: list[dict] = []

    @property
    def enabled(self) -> bool:
        return self.cfg.provider != "heuristic"

    def providers(self) -> list[str]:
        if not self.enabled:
            return []
        order = [self.cfg.provider]
        if self.cfg.use_fallback:
            order += [p for p in self.cfg.fallback_order if p != self.cfg.provider and p != "heuristic"]
        return order

    def may_share_labels(self, provider: str | None = None) -> bool:
        provider = provider or self.cfg.provider
        p = self.settings.privacy
        return p.share_labels_with_local if provider in LOCAL_PROVIDERS else p.share_labels_with_cloud

    def complete_json(self, system: str, user: str, purpose: str) -> dict | None:
        for provider in self.providers():
            started = time.time()
            record: dict[str, Any] = {"purpose": purpose, "provider": provider, "model": model_label(provider, self.cfg)}
            try:
                msg = _model(provider, self.cfg).invoke([
                    SystemMessage(content=system + "\nRespond with a single JSON object only."),
                    HumanMessage(content=user),
                ])
                text = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
                data = extract_json(text)
                record.update(ok=data is not None, seconds=round(time.time() - started, 2),
                              prompt_chars=len(system) + len(user), reply_chars=len(text))
                usage = getattr(msg, "usage_metadata", None) or {}
                if usage:
                    record["tokens"] = {k: usage.get(k) for k in ("input_tokens", "output_tokens")}
                if data is None:
                    record["error"] = "reply was not valid JSON"
            except Exception as e:  # network, auth, model missing, rate limit...
                data = None
                record.update(ok=False, seconds=round(time.time() - started, 2), error=str(e)[:300])
            self.calls.append(record)
            if self.on_call:
                self.on_call(record)
            if data is not None:
                return data
        return None


def test_provider(settings: Settings, provider: str) -> dict:
    s = settings.model_copy(deep=True)
    s.llm.provider = provider  # type: ignore[assignment]
    s.llm.use_fallback = False
    llm = LLM(s)
    started = time.time()
    data = llm.complete_json("You are a connectivity test.", 'Reply with {"ok": true, "model": "<your name>"}', "test")
    call = llm.calls[-1] if llm.calls else {}
    return {"ok": bool(data), "seconds": round(time.time() - started, 2), "reply": data, "error": call.get("error")}


def ollama_models(base_url: str) -> list[str]:
    try:
        r = httpx.get(base_url.rstrip("/") + "/api/tags", timeout=4)
        r.raise_for_status()
        return sorted(m["name"] for m in r.json().get("models", []))
    except Exception:
        return []
