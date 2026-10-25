@echo off
REM Data Mind launcher for Windows
cd /d "%~dp0"
if not exist backend\.venv (
  echo Creating virtual environment...
  python -m venv backend\.venv
)
call backend\.venv\Scripts\activate.bat
echo Installing Python packages (first run takes a few minutes)...
python -m pip install -q --upgrade pip
pip install -q -r backend\requirements.txt
if not exist frontend\dist (
  where npm >nul 2>nul && (cd frontend && call npm install --silent && call npm run build && cd ..)
)
cd backend
python run.py %*
