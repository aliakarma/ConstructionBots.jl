#!/usr/bin/env bash
# Builds the sisl fork of RVO2 in a Python 3.7 conda environment and points PyCall at it, and downloads the LDraw
# parts library. Used by CI, and works as a setup script on Linux. On Windows, follow notebooks/SETUP.md instead.
#     bash scripts/setup_rvo2.sh [ENV_NAME]
set -euo pipefail

env_name="${1:-lego_rvo2}"
ldraw_dir="${LDRAW_DIR:-$HOME/Documents/ldraw}"

eval "$(conda shell.bash hook)"
conda env list | grep -q "^$env_name " || conda create -y -n "$env_name" python=3.7
conda activate "$env_name"
pip install cython==0.29.36
src_dir="$(mktemp -d)"
git clone --depth 1 https://github.com/sisl/Python-RVO2.git "$src_dir/Python-RVO2"
(cd "$src_dir/Python-RVO2" && python setup.py build && python setup.py install)
python -c "import rvo2; assert hasattr(rvo2.PyRVOSimulator, 'setAgentAlpha'), 'not the sisl fork of RVO2'"
echo "PyCall should use: $(command -v python)"
if [ -n "${GITHUB_ENV:-}" ]; then
    echo "PYTHON=$(command -v python)" >> "$GITHUB_ENV"
fi

if [ ! -d "$ldraw_dir/parts" ]; then
    mkdir -p "$(dirname "$ldraw_dir")"
    curl -fsSL https://library.ldraw.org/library/updates/complete.zip -o "$src_dir/ldraw.zip"
    python -m zipfile -e "$src_dir/ldraw.zip" "$(dirname "$ldraw_dir")"
fi
rm -rf "$src_dir"
