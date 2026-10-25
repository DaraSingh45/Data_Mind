"""Filesystem layout. Everything Data Mind stores lives under DATA_DIR."""
from __future__ import annotations

import os
from pathlib import Path

from .env import load_env

load_env()  # backend/.env -> os.environ (before anything reads configuration)

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent
DATA_DIR = Path(os.environ.get("DATAMIND_DATA_DIR", BACKEND_DIR / "data")).resolve()
DATASETS_DIR = DATA_DIR / "datasets"
RUNS_DIR = DATA_DIR / "runs"
SAMPLES_DIR = DATA_DIR / "samples"
SETTINGS_FILE = DATA_DIR / "settings.json"
FRONTEND_DIST = PROJECT_DIR / "frontend" / "dist"
TRANSFORMERS_FILE = BACKEND_DIR / "datamind_transformers.py"

for d in (DATA_DIR, DATASETS_DIR, RUNS_DIR, SAMPLES_DIR):
    d.mkdir(parents=True, exist_ok=True)
