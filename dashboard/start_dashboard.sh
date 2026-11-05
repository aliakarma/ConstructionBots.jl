#!/usr/bin/env sh
# ConstructionLab launcher for Linux:  sh dashboard/start_dashboard.sh
# The first time, it installs everything (see setup.sh).
set -e
cd "$(dirname "$0")"
[ -f ".venv/.setup-complete" ] || bash ../setup.sh
echo "Starting ConstructionLab (normally at http://localhost:8501). Press Ctrl+C to stop."
exec .venv/bin/python -m streamlit run app.py --server.headless false
