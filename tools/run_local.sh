#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "WiFiSense local launcher"
echo "Project: $PROJECT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is required. Install Python 3 and retry."
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Creating project virtual environment..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -r requirements.txt

if lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "ERROR: Port 8000 is already in use:"
  lsof -nP -iTCP:8000 -sTCP:LISTEN
  echo "Stop the identified WiFiSense process yourself, then rerun this script."
  echo "No process was killed and no database files were changed."
  exit 2
fi

mkdir -p data
echo "Starting WiFiSense at http://127.0.0.1:8000"
echo "SQLite database is preserved at: $PROJECT_DIR/data/wifisense.db"
exec python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
