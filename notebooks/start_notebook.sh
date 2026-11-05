#!/usr/bin/env sh
# Experiment Lab launcher for Linux:  sh notebooks/start_notebook.sh
# The first time, it installs everything (see setup.sh).
set -e
cd "$(dirname "$0")"
[ -f "../dashboard/.venv/.setup-complete" ] || bash ../setup.sh
exec ../dashboard/.venv/bin/python -m jupyter lab ConstructionBots_Experiment_Lab.ipynb
