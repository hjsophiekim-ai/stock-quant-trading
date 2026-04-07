@echo off
setlocal

cd /d "%~dp0.."
echo [backend] starting uvicorn on http://127.0.0.1:8000
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload

endlocal
