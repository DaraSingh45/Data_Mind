#!/usr/bin/env bash
# Data Mind launcher for macOS / Linux
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
if [ ! -d backend/.venv ]; then
  echo "Creating virtual environment…"
  $PY -m venv backend/.venv
fi
source backend/.venv/bin/activate
echo "Installing Python packages (first run takes a few minutes)…"
pip install -q --upgrade pip
pip install -q -r backend/requirements.txt
if [ ! -d frontend/dist ] && command -v npm >/dev/null 2>&1; then
  echo "Building the interface…"
  (cd frontend && npm install --silent && npm run build)
fi
cd backend && python run.py "$@"
