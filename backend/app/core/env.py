"""Minimal .env support (no extra dependency).

API keys and model configuration live in ``backend/.env``. The file is read
at startup into ``os.environ``; variables already set in the shell win. When
you change a key in Settings, it is written back to the same file.
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]

ENV_FILE = Path(os.environ.get("DATAMIND_ENV_FILE", BACKEND_DIR / ".env"))
EXAMPLE_FILE = BACKEND_DIR / ".env.example"
_lock = threading.Lock()
_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$")


def _parse_value(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    return raw.split(" #", 1)[0].strip()  # inline comment after an unquoted value


def read_env_file(path: Path = ENV_FILE) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text("utf-8").splitlines():
            if line.lstrip().startswith("#"):
                continue
            m = _LINE.match(line)
            if m:
                values[m.group(1)] = _parse_value(m.group(2))
    return values


def load_env() -> None:
    """Create .env from the example on first run, then load it into os.environ."""
    with _lock:
        if not ENV_FILE.exists() and EXAMPLE_FILE.exists():
            ENV_FILE.write_text(EXAMPLE_FILE.read_text("utf-8"), "utf-8")
        for k, v in read_env_file().items():
            os.environ.setdefault(k, v)


def write_env(updates: dict[str, str]) -> None:
    """Update or append keys in .env, keeping comments and other lines intact."""
    with _lock:
        lines = ENV_FILE.read_text("utf-8").splitlines() if ENV_FILE.exists() else []
        done: set[str] = set()
        for i, line in enumerate(lines):
            m = _LINE.match(line)
            if m and not line.lstrip().startswith("#") and m.group(1) in updates:
                key = m.group(1)
                lines[i] = f"{key}={_quote(updates[key])}"
                done.add(key)
        for key, value in updates.items():
            if key not in done:
                lines.append(f"{key}={_quote(value)}")
        ENV_FILE.write_text("\n".join(lines).rstrip() + "\n", "utf-8")
        for key, value in updates.items():
            os.environ[key] = value


def _quote(v: str) -> str:
    v = str(v)
    return f'"{v}"' if (" " in v or "#" in v) else v


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)
