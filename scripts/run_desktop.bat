@echo off
setlocal

cd /d "%~dp0..\apps\desktop"
echo [desktop] installing deps if needed...
call npm install
echo [desktop] starting electron app...
call npm run dev

endlocal
