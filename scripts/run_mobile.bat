@echo off
setlocal

cd /d "%~dp0..\apps\mobile"
echo [mobile] installing deps if needed...
call npm install
echo [mobile] starting expo dev server...
call npm run dev

endlocal
