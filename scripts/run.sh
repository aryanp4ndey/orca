#!/usr/bin/env bash
# ============================================================
#  ORCA - start the backend on macOS or Linux
#      ./scripts/run.sh
# ============================================================
set -euo pipefail
cd "$(dirname "$0")/.."

echo
echo "  ORCA - Marine EcOsystem Reasoning with Collaborative Agents"
echo "  SIH26176 · ISRO · Team DRISHTI"
echo

command -v python3 >/dev/null 2>&1 || {
  echo "  [X] python3 was not found. Install Python 3.11 or newer."; exit 1; }

if [ ! -d ".venv" ]; then
  echo "  [1/3] Creating a virtual environment (one time only)..."
  python3 -m venv .venv
else
  echo "  [1/3] Virtual environment already exists."
fi

echo "  [2/3] Installing dependencies..."
./.venv/bin/python -m pip install --quiet --upgrade pip
./.venv/bin/python -m pip install --quiet -r backend/requirements.txt

echo "  [3/3] Starting the server..."
echo
echo "  ============================================================"
echo "    OPEN THIS IN YOUR BROWSER:   http://localhost:8000/app/"
echo "  ============================================================"
echo
echo "    That is the ORCA app."
echo "    http://localhost:8000/docs is the API console, not the app."
echo
echo "  Press Ctrl+C to stop."
echo

cd backend
exec ../.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
