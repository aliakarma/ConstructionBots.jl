"""Settings validation and translation into run_lego_demo arguments."""
from dataclasses import replace

from conftest import ENV_OK
from simulation.catalog import ASSIGNMENT_METHODS, ASSIGNMENT_TAGS
from simulation.validation import RunConfig, expand_study, parse_int_list, validate


def test_default_tractor_run_is_valid(catalog):
    v = validate(RunConfig(), catalog, ENV_OK)
    assert v.ok, v.errors
    r = v.resolved
    assert r.num_robots == 10 and r.robots_source == "model default"
    assert r.solver is None                       # Greedy uses no solver
    args = r.demo_arguments()
    assert args["ldraw_file"] == "tractor.mpd"
    assert args["assignment_mode"] == ":greedy"
    assert (args["rvo_flag"], args["tangent_bug_flag"], args["dispersion_flag"]) == (True, True, True)
    assert args["rng"] == "MersenneTwister(1)"
    assert args["look_for_previous_milp_solution"] is False and args["overwrite_results"] is False


def test_job_request_carries_exact_flags(catalog):
    c = RunConfig(assignment="milp", solver="highs", movement="no_rvo2", seed=7, num_robots=12,
                  optimizer_time_limit_s=30)
    v = validate(c, catalog, ENV_OK)
    job = v.resolved.job_request("run-1", "/tmp/run-1")
    assert job["assignment_mode"] == "milp" and job["milp_optimizer"] == "highs"
    assert (job["rvo_flag"], job["tangent_bug_flag"], job["dispersion_flag"]) == (False, True, True)
    assert job["seed"] == 7 and job["num_robots"] == 12 and job["optimizer_time_limit"] == 30


def test_every_assignment_method_runs_without_a_solver_except_milp(catalog):
    for o in ASSIGNMENT_METHODS:
        v = validate(RunConfig(assignment=o.key, solver="highs"), catalog, ENV_OK)
        assert v.ok, (o.key, v.errors)
        assert (v.resolved.solver is not None) == o.uses_solver
        assert o.key in ASSIGNMENT_TAGS and o.family


def test_metaheuristic_budget_is_passed_and_checked(catalog):
    v = validate(RunConfig(assignment="particle_swarm", search_iterations=7, search_population=9,
                           optimizer_time_limit_s=20), catalog, ENV_OK)
    job = v.resolved.job_request("run-1", "/tmp/run-1")
    assert job["assignment_mode"] == "particle_swarm" and job["optimizer_time_limit"] == 20
    assert (job["metaheuristic_iterations"], job["metaheuristic_population"]) == (7, 9)
    for bad in ({"search_iterations": 0}, {"search_population": 1}, {"optimizer_time_limit_s": 0}):
        assert not validate(RunConfig(assignment="genetic_algorithm", **bad), catalog, ENV_OK).ok, bad
    # The budget is ignored by methods that do not search.
    assert validate(RunConfig(assignment="greedy", search_population=1), catalog, ENV_OK).ok


def test_robot_count_limits(catalog):
    for bad in (0, -3, 501, 2.5, True):
        v = validate(RunConfig(num_robots=bad), catalog, ENV_OK)
        assert not v.ok, bad
    assert validate(RunConfig(num_robots=500), catalog, ENV_OK).ok
    v = validate(RunConfig(num_robots=4), catalog, ENV_OK)
    assert v.ok and any("Fewer robots" in w for w in v.warnings)


def test_unknown_model_and_missing_file(catalog):
    assert "not a model" in validate(RunConfig(model_key="nope"), catalog, ENV_OK).errors[0]
    v = validate(RunConfig(model_key="missing_model"), catalog, ENV_OK)
    assert not v.ok and any("missing" in e for e in v.errors)


def test_glpk_warm_start_is_rejected(catalog):
    v = validate(RunConfig(assignment="milp_w_greedy_warm_start", solver="glpk"), catalog, ENV_OK)
    assert not v.ok and any("GLPK cannot be combined" in e for e in v.errors)
    assert validate(RunConfig(assignment="milp", solver="glpk"), catalog, ENV_OK).ok


def test_gurobi_unlicensed_is_rejected_and_never_substituted(catalog):
    v = validate(RunConfig(assignment="milp", solver="gurobi"), catalog, ENV_OK)
    assert not v.ok and any("never replaces" in e for e in v.errors)
    # Not checked yet: allowed, with a warning that the engine will check the licence.
    v = validate(RunConfig(assignment="milp", solver="gurobi"), catalog, {"rvo2": "ok"})
    assert v.ok and any("licence has not been checked" in w for w in v.warnings)
    # Greedy ignores the solver setting entirely.
    assert validate(RunConfig(assignment="greedy", solver="gurobi"), catalog, ENV_OK).ok


def test_rvo2_missing_blocks_every_run(catalog):
    env = dict(ENV_OK, rvo2="fail")
    for movement in ("recommended", "none"):
        assert not validate(RunConfig(movement=movement), catalog, env).ok


def test_movement_profiles_and_safety_notes(catalog):
    v = validate(RunConfig(movement="none"), catalog, ENV_OK)
    assert v.ok and v.resolved.movement.unsafe
    assert any("does not reward or penalize safety" in w for w in v.warnings)
    v = validate(RunConfig(movement="no_dispersion"), catalog, ENV_OK)
    assert any("not recommended" in w for w in v.warnings)
    v = validate(RunConfig(movement="no_rvo2"), catalog, ENV_OK)
    assert any("only while RVO2 is on" in w for w in v.warnings)
    v = validate(RunConfig(movement="custom", custom_rvo=True, custom_tangent_bug=False, custom_dispersion=True),
                 catalog, ENV_OK)
    assert v.ok and v.resolved.movement.key == "no_tangent_bug"   # a custom combination that matches a preset
    v = validate(RunConfig(movement="custom", custom_rvo=False, custom_tangent_bug=True, custom_dispersion=False),
                 catalog, ENV_OK)
    assert v.resolved.movement.key == "custom"


def test_large_model_needs_confirmation(catalog):
    assert not validate(RunConfig(model_key="x_wing"), catalog, ENV_OK).ok
    assert validate(RunConfig(model_key="x_wing", confirm_large=True, live_preview="off"), catalog, ENV_OK).ok


def test_limits_and_live_preview(catalog):
    assert not validate(RunConfig(max_steps=5), catalog, ENV_OK).ok
    assert not validate(RunConfig(optimizer_time_limit_s=0, assignment="milp"), catalog, ENV_OK).ok
    v = validate(RunConfig(), catalog, ENV_OK)
    assert v.ok and v.resolved.timeout_min == 0                  # default: no wall-clock limit
    assert validate(RunConfig(timeout_min=0), catalog, ENV_OK).resolved.timeout_min == 0
    assert validate(RunConfig(timeout_min=30), catalog, ENV_OK).resolved.timeout_min == 30
    assert not validate(RunConfig(timeout_min=-1), catalog, ENV_OK).ok
    assert not validate(RunConfig(timeout_min=10_081), catalog, ENV_OK).ok
    v = validate(RunConfig(save_animation=False, live_preview="frequent"), catalog, ENV_OK)
    assert v.resolved.demo_arguments()["save_animation_along_the_way"] is False   # no animation, no snapshots
    v = validate(RunConfig(live_preview="normal", smooth_animation=True), catalog, ENV_OK)
    assert v.resolved.live_interval == 300   # smooth animations snapshot less often


def test_parse_int_list():
    assert parse_int_list("1, 2, 5-7", 0, 100, 50) == ([1, 2, 5, 6, 7], None)
    assert parse_int_list("3 3 3", 0, 100, 50)[0] == [3]
    assert parse_int_list("7-5", 0, 100, 50)[1]
    assert parse_int_list("abc", 0, 100, 50)[1]
    assert parse_int_list("1-100", 0, 1000, 50)[1]
    assert parse_int_list("", 0, 100, 50)[1]


def test_study_changes_only_one_factor_with_matched_seeds(catalog):
    base = RunConfig(movement="no_tangent_bug", num_robots=12, optimizer_time_limit_s=30)
    runs = expand_study(base, "assignment", ["greedy", "milp", "milp_w_greedy_warm_start"], [1, 2], "b1")
    assert len(runs) == 6
    assert {r.assignment for r in runs} == {"greedy", "milp", "milp_w_greedy_warm_start"}
    for a in ("greedy", "milp"):
        assert sorted(r.seed for r in runs if r.assignment == a) == [1, 2]
    for r in runs:
        assert (r.movement, r.num_robots, r.optimizer_time_limit_s, r.batch_id) == ("no_tangent_bug", 12, 30, "b1")
    robots = expand_study(replace(base, num_robots=None), "num_robots", [6, 10], [1], "b2")
    assert [r.num_robots for r in robots] == [6, 10]
    seeds = expand_study(base, "seed", [], [1, 2, 3], "b3")
    assert [r.seed for r in seeds] == [1, 2, 3]
