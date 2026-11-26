@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [docqa] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 exit /b 1
)

echo [docqa] Installing dependencies...
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install -q -e .
if errorlevel 1 exit /b 1

if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo [docqa] Created .env from .env.example (mock provider, no API key needed)
)

echo [docqa] Starting API on http://127.0.0.1:8000 (docs: /docs)
".venv\Scripts\python.exe" -m docqa.cli serve %*
