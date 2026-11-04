"""Real simulations through the real engine and Julia worker, then the pages that show them.

Needs Julia, the LDraw library and rvo2, so it only runs on request:
    CONSTRUCTIONLAB_REAL_TESTS=1 python -m pytest tests/test_real_simulation.py
"""
import os
import time

import pytest
from streamlit.testing.v1 import AppTest

from conftest import DASHBOARD, ENV_OK
from simulation.compare import find_groups, paired_comparison
from simulation.engine import EngineManager
from simulation.results import list_runs, load_run, to_csv_bytes
from simulation.validation import RunConfig, validate
from test_app import _render_page

pytestmark = pytest.mark.skipif(not os.environ.get("CONSTRUCTIONLAB_REAL_TESTS"),
                                reason="set CONSTRUCTIONLAB_REAL_TESTS=1 to run real simulations")


def _resolved(catalog, **kw):
    v = validate(RunConfig(**kw), catalog, ENV_OK)
    assert v.ok, v.errors
    return v.resolved


def test_real_runs_are_recorded_compared_and_shown(tmp_paths, catalog, monkeypatch):
    search = dict(assignment="random_search", search_iterations=2, search_population=4)
    plain = dict(save_animation=False)
    eng = EngineManager(tmp_paths)
    try:
        ids = eng.submit([
            _resolved(catalog, seed=1, save_animation=True),
            _resolved(catalog, seed=2, **plain),
            _resolved(catalog, seed=1, **search, **plain),
            _resolved(catalog, seed=2, **search, **plain),
            _resolved(catalog, assignment="milp_w_greedy_warm_start", optimizer_time_limit_s=5, **plain),
            _resolved(catalog, num_robots=2, **plain),
        ])
        deadline = time.time() + 1500
        while time.time() < deadline:
            records = [load_run(tmp_paths.runs / rid) for rid in ids]
            if all(r.is_final for r in records):
                break
            time.sleep(3)
    finally:
        eng.shutdown()

    greedy, greedy2, rs1, rs2, milp, too_few = records
    assert [r.state for r in records] == ["success"] * 5 + ["failed"], [r.detail for r in records]

    for r in records[:5]:
        assert r.metric("makespan_s") > 0
        assert r.metric("robot_min_gap_m") is not None
        assert r.result["robot_overlap_steps"] >= 0 and r.result["position_swaps"] >= 0
        assert len(r.source_hash) == 12
    assert greedy.metric("makespan_s") == 22.75  # Greedy, Tractor, seed 1 is reproducible (see docs/EXPERIMENTS.md)
    assert greedy.animation_path is not None
    assert not rs1.result["search_timed_out"]
    assert rs1.result["search_evaluations"] > 0
    assert too_few.result["failure_kind"] == "too_few_robots" and "needs 4" in too_few.detail
    rep = milp.solver_report()
    assert rep.termination in ("optimal", "time_limit") and rep.dual_bound is not None

    runs = list_runs(tmp_paths)
    assert b"robot_min_gap_m" in to_csv_bytes(runs, tmp_paths)
    groups = find_groups([greedy, greedy2, rs1, rs2], "assignment")
    assert len(groups) == 1 and len(groups[0].levels) == 2
    [p] = paired_comparison(groups[0].runs, "assignment", "Greedy")
    assert p.n_pairs == 2 and p.level.startswith("Random search (2 × 4")

    # The pages with real records: nothing may raise
    monkeypatch.chdir(DASHBOARD)
    for page in ("overview", "compare", "history", "analytics"):
        at = AppTest.from_function(_render_page, args=(str(DASHBOARD), page), default_timeout=120)
        at.run()
        assert not at.exception, (page, at.exception)
