@echo off
setlocal
cd /d "%~dp0\.."
if not exist ".venv" ( echo Run scripts\run.bat once first. & pause & exit /b 1 )
cd backend
..\.venv\Scripts\python.exe -m app.tools.demo %*
pause
