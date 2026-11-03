#!/usr/bin/env sh
# ConstructionLab launcher for macOS / Linux:  sh dashboard/start_dashboard.sh
# The first time, it creates a private Python environment in dashboard/.venv and installs the dashboard's packages.
set -e
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
  echo "Creating the dashboard's Python environment (one time only)..."
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
fi
echo "Starting ConstructionLab (normally at http://localhost:8501). Press Ctrl+C to stop."
exec .venv/bin/python -m streamlit run app.py --server.headless false
