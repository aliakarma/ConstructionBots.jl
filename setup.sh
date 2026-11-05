#!/usr/bin/env bash
# One-command setup on Linux: Julia, the LDraw parts, RVO2, the Julia packages, the Jupyter kernel and the Python
# environment for the dashboard and JupyterLab. Safe to run again. macOS has not been tested: see notebooks/SETUP.md.
#     bash setup.sh
set -euo pipefail
cd "$(dirname "$0")"
repo="$PWD"
version="$(sed -n 's/^julia_version = "\(.*\)"/\1/p' Manifest.toml)"

for tool in git curl g++ cmake make; do
    command -v "$tool" > /dev/null || { echo "Please install $tool first, for example: sudo apt install git curl g++ cmake make"; exit 1; }
done

echo "=== Julia $version"
find_julia() {
    local found
    found="$(ls -d "$HOME"/.julia/juliaup/julia-"$version"+*/bin/julia 2> /dev/null | head -n 1 || true)"
    if [ -z "$found" ] && command -v julia > /dev/null && julia --version | grep -qF "$version"; then
        found="$(command -v julia)"
    fi
    echo "$found"
}
julia_bin="$(find_julia)"
if [ -z "$julia_bin" ]; then
    # The shell profile stays as it is: the launchers and the dashboard find a juliaup installation themselves.
    curl -fsSL https://install.julialang.org | sh -s -- --yes --default-channel "$version" --add-to-path no
    julia_bin="$(find_julia)"
fi
[ -n "$julia_bin" ] || { echo "Julia $version could not be installed."; exit 1; }
echo "$julia_bin"

echo "=== Conda (for Python 3.7)"
if ! command -v conda > /dev/null; then
    for prefix in "$HOME/miniforge3" "$HOME/miniconda3" "$HOME/anaconda3"; do
        [ -x "$prefix/bin/conda" ] && export PATH="$prefix/bin:$PATH" && break
    done
fi
if ! command -v conda > /dev/null; then
    installer="$(mktemp)"
    curl -fsSL -o "$installer" "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"
    bash "$installer" -b -p "$HOME/miniforge3"
    rm -f "$installer"
    export PATH="$HOME/miniforge3/bin:$PATH"
fi

echo "=== RVO2 and the LDraw parts library"
bash scripts/setup_rvo2.sh

echo "=== Julia packages and the Jupyter kernel (the slowest step: 10-30 minutes the first time)"
PYTHON="$(conda run -n lego_rvo2 python -c 'import sys; print(sys.executable)')"
export PYTHON   # also stops PyCall's build from downloading its own Miniconda
"$julia_bin" scripts/setup_julia.jl

echo "=== Python environment for the dashboard and JupyterLab"
venv_ok() { "$1" -c 'import sys, ensurepip; sys.exit(sys.version_info[:2] < (3, 11))' 2> /dev/null; }
venv=dashboard/.venv
if [ -x "$venv/bin/python" ] && ! venv_ok "$venv/bin/python"; then rm -rf "$venv"; fi
if [ ! -x "$venv/bin/python" ]; then
    base=""
    for candidate in python3.13 python3.12 python3.11 python3; do
        if command -v "$candidate" > /dev/null && venv_ok "$candidate"; then base="$candidate"; break; fi
    done
    if [ -z "$base" ]; then
        conda env list | grep -q '^constructionlab_python ' || conda create -y -n constructionlab_python --override-channels -c conda-forge python=3.13
        base="$(conda run -n constructionlab_python python -c 'import sys; print(sys.executable)')"
    fi
    "$base" -m venv "$venv"
fi
"$venv/bin/python" -m pip install -r dashboard/requirements.txt -r notebooks/requirements.txt

echo "=== Checking the installation with a real simulation"
"$julia_bin" --project="$repo" scripts/verify_install.jl

touch "$venv/.setup-complete"   # the launchers look for this
echo
echo "Setup finished. Start the dashboard with: sh dashboard/start_dashboard.sh"
echo "Start the notebook with: sh notebooks/start_notebook.sh"
