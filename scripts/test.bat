@echo off
setlocal
cd /d "%~dp0\.."
if not exist ".venv" ( echo Run scripts\run.bat once first. & pause & exit /b 1 )
call .venv\Scripts\python.exe -m pip install --quiet -r backend\requirements-dev.txt
cd backend
..\.venv\Scripts\python.exe -m pytest
pause
