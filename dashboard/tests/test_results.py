"""Run records, progress and solver parsing, CSV export."""
import csv
import io

from simulation.results import (apply_recorded_status, load_run, list_runs, parse_progress, parse_solver_log,
                                save_export, to_csv_bytes, unique_export_path)
from simulation.tomlio import dumps, read_toml, write_toml_atomic

HIGHS_TIME_LIMIT = """Running HiGHS 1.15.1
MIP start solution is feasible, objective value is 14.725
Solving report
  Status            Time limit reached
  Primal bound      37.9
  Dual bound        7.825
  Gap               79.35% (tolerance: 0.01%)
  P-D integral      12.4536172317
  Solution status   feasible
                    37.9 (objective)
  Timing            30.02
"""
HIGHS_OPTIMAL = """Model status        : Optimal
Solving report
  Status            Optimal
  Primal bound      14.725
  Dual bound        14.725
  Gap               0% (tolerance: 0.01%)
  Solution status   feasible
  Timing            2.1
"""


def test_toml_roundtrip(tmp_path):
    d = {"a": 1, "b": 2.5, "c": "quote \" and \\ backslash\nnewline", "d": True, "e": [1, 2], "inf": float("inf"),
         "skip": None, "t": {"x": "y", "n": {"deep": 3}}}
    p = write_toml_atomic(tmp_path / "x.toml", d)
    back = read_toml(p)
    assert back["c"] == d["c"] and back["t"]["n"]["deep"] == 3 and back["inf"] == float("inf")
    assert "skip" not in back
    assert "skip" not in dumps(d)


def test_progress_phases_and_task_counts():
    p = parse_progress("Constructing model spec...done!\nAssigning robots...", "")
    assert p.phase == "Assigning tasks to robots" and p.fraction is None
    err = "Simulating...  14%|███ \n   step_num: 86\n   n_closed: 79\n    n_total: 289\n" \
          "Simulating...  33%|███\n   step_num: 172\n   n_closed: 127\n    n_total: 289\n"
    p = parse_progress("Animating preprocessing step...done", err)
    assert p.phase == "Simulating robot motion" and (p.closed, p.total, p.sim_step) == (127, 289, 172)
    assert abs(p.fraction - 127 / 289) < 1e-9
    assert parse_progress("", "").phase.startswith("Loading the LEGO model")


def test_solver_log_parsing():
    r = parse_solver_log(HIGHS_TIME_LIMIT, "highs")
    assert r.termination == "time_limit" and r.gap_percent == 79.35 and r.primal_bound == 37.9
    assert r.warm_start_objective == 14.725 and "not proven optimal" in r.label
    assert parse_solver_log(HIGHS_OPTIMAL, "highs").termination == "optimal"
    assert parse_solver_log("INTEGER OPTIMAL SOLUTION FOUND", "glpk").termination == "optimal"
    assert parse_solver_log("TIME LIMIT EXCEEDED; SEARCH TERMINATED", "glpk").termination == "time_limit"
    assert parse_solver_log("Time limit reached\nBest objective 3.0e+01, best bound 2.0e+01, gap 33.3333%",
                            "gurobi").gap_percent == 33.3333
    assert parse_solver_log("", "highs").termination == ""


def test_recorded_solver_status_replaces_the_log():
    r = apply_recorded_status(parse_solver_log("", "gurobi"), {"solver_termination_status": "TIME_LIMIT",
                              "solver_objective": 12.5, "solver_bound": 8.0, "solver_gap": 0.36})
    assert (r.termination, r.primal_bound, r.dual_bound) == ("time_limit", 12.5, 8.0)
    assert r.short == "time limit, gap 36.0%"
    none = apply_recorded_status(parse_solver_log("", "highs"), {"solver_termination_status": "TIME_LIMIT",
                                                                 "solver_primal_status": "NO_SOLUTION"})
    assert none.termination == "no_solution"
    assert apply_recorded_status(parse_solver_log(HIGHS_OPTIMAL, "highs"), {}).termination == "optimal"


def _make_run(paths, run_id, state, makespan=None, model="Tractor", assignment="Greedy", seed=1):
    d = paths.runs / run_id
    d.mkdir(parents=True)
    write_toml_atomic(d / "config.toml", {
        "run_id": run_id, "created_at": "2026-10-18T10:00:00",
        "settings": {"model_key": "tractor", "seed": seed, "save_animation": False, "max_steps": 100000},
        "resolved": {"label": f"{model} | {assignment}", "model_name": model, "num_robots": 10,
                     "assignment_label": assignment, "assignment_key": assignment.lower(), "solver_key": "",
                     "solver_label": "not used", "movement_label": "Recommended", "rvo": True, "tangent_bug": True,
                     "dispersion": True},
        "run_lego_demo_arguments": {"num_robots": 10}})
    write_toml_atomic(d / "status.toml", {"run_id": run_id, "state": state, "detail": "x"})
    res = {"run_id": run_id}
    if makespan is not None:
        res["makespan_s"] = makespan
    write_toml_atomic(d / "result.toml", res)
    return d


def test_records_and_csv_never_count_failures_as_zero(tmp_paths):
    _make_run(tmp_paths, "20261018-100000-tractor-greedy-aaaa", "success", 21.1)
    _make_run(tmp_paths, "20261018-100100-tractor-greedy-bbbb", "failed")
    (tmp_paths.runs / "not a run").mkdir()           # ignored: invalid name
    (tmp_paths.runs / "20261018-x-empty").mkdir()    # ignored: no config
    runs = list_runs(tmp_paths)
    assert [r.state for r in runs] == ["success", "failed"] or {r.state for r in runs} == {"success", "failed"}
    data = to_csv_bytes(runs, tmp_paths)
    assert data.startswith("﻿".encode("utf-8"))
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    failed = next(r for r in rows if r["status"] == "Failed")
    assert failed["makespan_sim_s"] == ""           # empty, not 0
    ok = next(r for r in rows if r["status"] == "Completed")
    assert ok["makespan_sim_s"] == "21.1"
    assert all(not r["run_folder"].startswith(("C:", "/")) for r in rows)   # no absolute paths in exports


def test_exports_are_never_overwritten(tmp_paths):
    _make_run(tmp_paths, "20261018-100000-tractor-greedy-aaaa", "success", 21.1)
    runs = list_runs(tmp_paths)
    p1 = save_export(runs, tmp_paths, "history")
    p2 = save_export(runs, tmp_paths, "history")
    assert p1 != p2 and p1.exists() and p2.exists()
    assert unique_export_path(tmp_paths, "history") not in (p1, p2)


def test_load_run_rejects_bad_folders(tmp_paths):
    assert load_run(tmp_paths.runs / "../escape") is None
    assert load_run(tmp_paths.runs / "does-not-exist") is None
