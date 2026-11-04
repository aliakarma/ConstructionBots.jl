"""Fair comparisons: grouping by one factor, never averaging failures."""
import math
from pathlib import Path

from simulation.compare import (bootstrap_ci, deduplicate, differences, find_groups, holm_adjust, level_of,
                                paired_comparison, sign_flip_p, spearman, summarize)
from simulation.results import RunRecord


def rec(run_id, assignment="Greedy", solver="", robots=10, seed=1, movement="Recommended", state="success",
        makespan=20.0, anim=False):
    return RunRecord(
        run_id=run_id, folder=Path("."), state=state,
        settings={"model_key": "tractor", "seed": seed, "optimizer_time_limit_s": 60, "max_steps": 100000,
                  "max_iters_no_progress": 10000, "save_animation": anim},
        resolved={"model_name": "Tractor", "num_robots": robots, "assignment_label": assignment,
                  "solver_key": solver.lower(), "solver_label": solver or "not used", "movement_label": movement,
                  "rvo": True, "tangent_bug": True, "dispersion": True, "label": run_id},
        result={"makespan_s": makespan} if state == "success" else {})


def test_assignment_groups_hold_everything_else_fixed():
    runs = [rec("a1", seed=1), rec("a2", seed=2), rec("m1", "MILP", "HiGHS", seed=1, makespan=40),
            rec("m2", "MILP", "HiGHS", seed=2, state="failed"),
            rec("other", "MILP", "HiGHS", robots=14)]           # different robot count: another group
    groups = find_groups(runs, "assignment")
    assert len(groups) == 1
    g = groups[0]
    assert {r.run_id for r in g.runs} == {"a1", "a2", "m1", "m2"}
    assert g.levels == ["Greedy", "MILP + HiGHS (60 s)"]


def test_summary_counts_failures_but_never_averages_them():
    runs = [rec("m1", "MILP", "HiGHS", makespan=40, seed=1), rec("m2", "MILP", "HiGHS", state="failed", seed=2),
            rec("m3", "MILP", "HiGHS", makespan=44, seed=3)]
    [s] = summarize(runs, "assignment")
    assert (s.n_success, s.n_other, s.mean, s.min, s.max) == (2, 1, 42.0, 40.0, 44.0)
    assert s.other_states == "1 failed"
    assert abs(s.sd - 2.8284271) < 1e-6


def test_robot_scaling_and_repeated_trials_groups():
    runs = [rec("r6", robots=6), rec("r10", robots=10), rec("r14", robots=14)]
    [g] = find_groups(runs, "num_robots")
    assert g.levels == ["6", "10", "14"]
    trials = [rec(f"s{i}", seed=i) for i in range(1, 4)]
    [g] = find_groups(trials, "seed")
    assert len(g.levels) == 3


def test_differences_flags_uncontrolled_comparisons_and_timing_settings():
    sim, timing = differences([rec("a"), rec("b", "MILP", "HiGHS", robots=14, anim=True)])
    assert "Assignment" in sim and "Robots" in sim and "Solver" in sim
    assert timing == ["3D animation recording"]
    assert differences([rec("a"), rec("b")]) == ([], [])


def test_cancelled_and_rejected_runs_are_not_comparable():
    runs = [rec("a"), rec("b", "MILP", "HiGHS", state="canceled"), rec("c", "MILP", "Gurobi", state="rejected")]
    assert find_groups(runs, "assignment") == []


def test_step_limits_separate_configurations_and_labels():
    from simulation.compare import config_key
    a = rec("a")
    b = rec("b")
    b.settings["max_steps"] = 100
    assert config_key(a) != config_key(b)
    assert "max 100 steps" in b.label and "max" not in a.label


def _search(run_id, iterations, seed=1, makespan=20.0):
    r = rec(run_id, "Genetic algorithm", seed=seed, makespan=makespan)
    r.settings.update(search_iterations=iterations, search_population=16)
    r.resolved["assignment_key"] = "genetic_algorithm"
    return r


def test_search_budgets_are_different_methods():
    runs = [_search("small", 5), _search("large", 25)]
    assert level_of(runs[0], "assignment") == "Genetic algorithm (5 × 16, 60 s)"
    assert level_of(runs[1], "assignment") == "Genetic algorithm (25 × 16, 60 s)"
    assert [s.n_success for s in summarize(runs, "assignment")] == [1, 1]   # never pooled into one mean


def test_repeats_of_one_seed_count_once():
    runs = [rec("old", makespan=30.0), rec("new", makespan=30.0), rec("other", seed=2, makespan=10.0)]
    runs[0].created_at, runs[1].created_at, runs[2].created_at = "2026-01-01", "2026-01-02", "2026-01-01"
    assert [r.run_id for r in deduplicate(runs)] == ["new", "other"]
    [s] = summarize(runs, "assignment")
    assert (s.n_runs, s.mean) == (2, 20.0)


def test_runs_from_different_code_are_not_compared():
    a, b = rec("a"), rec("b", "MILP", "HiGHS")
    a.result["software"] = {"source_hash": "aaa"}
    b.result["software"] = {"source_hash": "bbb"}
    assert find_groups([a, b], "assignment") == []
    assert differences([a, rec("c")])[0] == ["Code version"]


def test_statistics_match_known_values():
    assert sign_flip_p([1.0, 2.0, 3.0, 4.0, 5.0]) == 2 / 32
    assert sign_flip_p([1.0, -1.0]) == 1.0
    assert sign_flip_p([0.0, 0.0]) == 1.0
    assert sign_flip_p([1.0] * 20) < 1e-4       # sampled, not exact
    assert all(math.isclose(a, b) for a, b in zip(holm_adjust([0.01, 0.04, 0.03]), [0.03, 0.06, 0.06]))
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == -1
    assert math.isnan(spearman([1, 1, 1], [1, 2, 3]))
    assert bootstrap_ci([1.0, 2.0]) == (None, None)
    low, high = bootstrap_ci([1.0, 2.0, 3.0, 4.0, 5.0])
    assert 1 <= low < 3 < high <= 5


def test_paired_comparison_uses_only_seeds_where_both_succeeded():
    runs = [rec(f"g{s}", seed=s, makespan=v) for s, v in ((1, 10.0), (2, 12.0), (3, 14.0), (4, 9.0))]
    runs += [rec(f"m{s}", "MILP", "HiGHS", seed=s, makespan=v) for s, v in ((1, 9.0), (2, 10.0), (3, 11.0))]
    runs.append(rec("m4", "MILP", "HiGHS", seed=4, state="failed"))
    [p] = paired_comparison(runs, "assignment", "Greedy")
    assert (p.n_pairs, p.wins, p.losses) == (3, 3, 0)
    assert p.mean_gain == 2.0 and p.effect_size == 2.0
    assert p.p_value == p.p_holm == 2 / 8


def test_summary_reports_the_safety_record():
    runs = [rec("a", seed=1), rec("b", seed=2), rec("c", seed=3)]
    for r, gap, steps in zip(runs, (0.2, -0.1, 0.1), (0, 3, 0)):
        r.result.update(robot_min_gap_m=gap, robot_overlap_steps=steps, position_swaps=1)
    [s] = summarize(runs, "assignment")
    assert (s.runs_with_overlap, s.min_robot_gap, s.total_swaps) == (1, -0.1, 3)
    assert s.success_rate == 1.0
    assert s.ci_low is not None and s.ci_high is not None
