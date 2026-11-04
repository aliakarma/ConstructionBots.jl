"""Shared fixtures. Tests never touch results/dashboard: they work in temporary folders."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from simulation.catalog import catalog_from_registry  # noqa: E402
from simulation.paths import REPO_ROOT, Paths  # noqa: E402
from simulation.tomlio import write_toml_atomic  # noqa: E402

REGISTRY = {
    "source": "src/project_params.jl",
    "models": [
        {"index": 4, "key": "tractor", "project_name": "tractor", "file_name": "tractor.mpd", "model_scale": 0.008,
         "default_robots": 10, "file_exists": True, "reference_parts": 20, "reference_assemblies": 8,
         "reference_time": "2 sec"},
        {"index": 9, "key": "at_te_walker", "project_name": "at_te_walker", "file_name": "20009-1 - AT-TE Walker - Mini.mpd",
         "model_scale": 0.008, "default_robots": 35, "file_exists": True, "reference_parts": 100,
         "reference_assemblies": 22, "reference_time": "23 sec"},
        {"index": 10, "key": "x_wing", "project_name": "x_wing", "file_name": "7140-1 - X-wing Fighter.mpd",
         "model_scale": 0.004, "default_robots": 50, "file_exists": True, "reference_parts": 309,
         "reference_assemblies": 28, "reference_time": "3 min"},
        {"index": 99, "key": "missing_model", "project_name": "missing_model", "file_name": "missing.mpd",
         "model_scale": 0.008, "default_robots": 5, "file_exists": False, "reference_parts": 10,
         "reference_assemblies": 1, "reference_time": "1 sec"},
    ],
}

ENV_OK = {"rvo2": "ok", "solver_highs": "ok", "solver_glpk": "ok", "solver_gurobi": "unavailable"}


@pytest.fixture
def catalog():
    return catalog_from_registry(REGISTRY)


@pytest.fixture
def tmp_paths(tmp_path, monkeypatch) -> Paths:
    root = tmp_path / "results"
    monkeypatch.setenv("CONSTRUCTIONLAB_RESULTS_DIR", str(root))
    p = Paths(repo=REPO_ROOT, results_root=root)
    p.ensure()
    # A cached registry newer than src/project_params.jl, so no Julia process is needed.
    write_toml_atomic(p.cache / "registry.toml", REGISTRY)
    future = max(os.path.getmtime(REPO_ROOT / "src" / "project_params.jl"),
                 os.path.getmtime(REPO_ROOT / "LDraw_files")) + 10
    os.utime(p.cache / "registry.toml", (future, future))
    return p
