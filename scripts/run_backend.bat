@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

cd /d "%~dp0.."

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

if not exist ".env" (
  echo [WARN] .env not found. Copy env.paper.example to .env.paper, fill values, then copy to .env
  echo        See docs\quickstart_real_mock_trading.md
)

echo [backend] python=!PY!
echo [backend] uvicorn http://127.0.0.1:8000  ^| API docs http://127.0.0.1:8000/docs
"!PY!" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload

endlocal
