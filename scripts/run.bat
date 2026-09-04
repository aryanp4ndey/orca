@echo off
REM ============================================================
REM  ORCA - start the backend on Windows
REM  Double-click this file, or run it from Command Prompt.
REM ============================================================
setlocal

cd /d "%~dp0\.."

echo.
echo   ORCA - Marine EcOsystem Reasoning with Collaborative Agents
echo   SIH26176 . ISRO . Team DRISHTI
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo   [X] Python was not found on your PATH.
  echo       Install Python 3.11 or newer from https://www.python.org/downloads/
  echo       and tick "Add python.exe to PATH" during installation.
  pause
  exit /b 1
)

if not exist ".venv" (
  echo   [1/3] Creating a virtual environment ^(one time only^)...
  python -m venv .venv
) else (
  echo   [1/3] Virtual environment already exists.
)

echo   [2/3] Installing dependencies...
call .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
call .venv\Scripts\python.exe -m pip install --quiet -r backend\requirements.txt
if errorlevel 1 (
  echo   [X] Dependency installation failed. Check your internet connection.
  pause
  exit /b 1
)

echo   [3/3] Starting the server...
echo.
echo   ============================================================
echo     OPEN THIS IN YOUR BROWSER:   http://localhost:8000/app/
echo   ============================================================
echo.
echo     That is the ORCA app.
echo     http://localhost:8000/docs is the API console, not the app.
echo.
echo   Press Ctrl+C here to stop.
echo.

cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000

pause
