# =============================================================================
# notebook_helpers.jl
#
# Support code for notebooks/ConstructionBots_Experiment_Lab.ipynb.
#
# Notebook users never need to edit this file. It translates the friendly
# settings in the notebook into the keyword arguments of the simulator's public
# entry point `ConstructionBots.run_lego_demo`, validates them, runs
# experiments, and records / displays / exports results.
#
# The simulation itself always comes from the repository's `src/` code; nothing
# here re-implements simulator logic.
#
# Load with (after activating the repository project):
#     include("notebooks/notebook_helpers.jl"); using .ExperimentLab
# =============================================================================
module ExperimentLab

using ConstructionBots
using Random
using Dates
using TOML
using Printf
using PyCall
using LDrawParser
using Sockets
using Base64
import MeshCat
import ProgressMeter
import HiGHS
import GLPK
import Gurobi

export ExperimentConfig, make_config, check_settings, batch_folder, lab_setup, check_environment, validate_config,
    run_experiment, run_batch, preset_configs, with_seeds,
    show_run, show_results, show_summary, show_paired, show_plan_vs_simulation, show_models, show_options, show_visuals,
    show_comparison,
    chart_metric, chart_convergence, chart_schedule, export_csv, read_csv, open_in_browser, show_animation,
    MODEL_INFO, ASSIGNMENT_METHODS, SOLVERS, MOVEMENT_PROFILES, CSV_COLUMNS

# -----------------------------------------------------------------------------
# Registries: friendly names  ->  the simulator's actual arguments
# -----------------------------------------------------------------------------

"""
Model registry. `symbol` is the key used by `ConstructionBots.get_project_params`
(see src/project_params.jl). Part / assembly counts and the reference run times
are copied from the comments in src/project_params.jl and scripts/demos.jl
(the authors' hardware; configuration not stated) and are only a rough guide.
"""
const MODEL_INFO = [
    # friendly name,             symbol,                   parts, assemblies, reference time, size class
    ("Tractor",                  :tractor,                 20,    8,   "about 2 s",       :small),
    ("Colored 8x8",              :colored_8x8,             33,    1,   "about 4 s",       :small),
    ("TIE Fighter (mini)",       :tie_fighter,             44,    4,   "about 7 s",       :small),
    ("X-Wing (mini)",            :x_wing_mini,             61,    12,  "about 9 s",       :small),
    ("Imperial Shuttle (mini)",  :imperial_shuttle,        84,    5,   "about 13 s",      :medium),
    ("Quad Nested",              :quad_nested,             85,    21,  "about 26 s",      :medium),
    ("AT-TE Walker (mini)",      :at_te_walker,            100,   22,  "about 23 s",      :medium),
    ("X-Wing + TIE (mini)",      :x_wing_tie_mini,         105,   17,  "about 26 s",      :medium),
    ("X-Wing",                   :x_wing,                  309,   28,  "about 3 min",     :large),
    ("Passenger Plane",          :passenger_plane,         326,   28,  "about 4 min",     :large),
    ("Imperial Star Destroyer",  :imperial_star_destroyer, 418,   11,  "about 5 min",     :large),
    ("Kings Castle",             :kings_castle,            761,   70,  "about 21 min",    :very_large),
    ("AT-AT",                    :at_at,                   1105,  2,   "not recorded",    :very_large),
    ("Heavily Nested",           :heavily_nested,          1757,  508, "about 62 min",    :very_large),
    ("Saturn V",                 :saturn_v,                1845,  306, "about 163 min",   :very_large),
]

"""
Task-assignment methods (the `assignment_mode` argument of `run_lego_demo`). The rules and
metaheuristics other than Greedy are in src/assignment_algorithms.jl.
"""
const ASSIGNMENT_METHODS = [
    # friendly name,               symbol,                       uses solver?, description, family
    ("Greedy",                   :greedy,                    false,
     "Rule: the task that a robot team can finish earliest goes first (the repository's " *
     "GreedyOrderedAssignment). Fast; the recommended baseline.", "Heuristic rule"),
    ("Greedy with travel",       :greedy_with_travel,        false,
     "Rule: Greedy, except that each robot's finish time includes its earlier travel. This is the decoder the " *
     "metaheuristics use, so it shows what they gain from the decoder alone.", "Heuristic rule"),
    ("Most complex first",       :most_complex_first,        false,
     "Rule: the task that needs the largest robot team (then has the most LEGO parts) goes first.",
     "Heuristic rule"),
    ("Nearest station first",    :nearest_station_first,     false,
     "Rule: the task whose pick-up station the free robots reach soonest goes first (travel time only, " *
     "ignoring when the robots become free).", "Heuristic rule"),
    ("MILP",                     :milp,                      true,
     "Mixed-integer linear program solved by an optimization solver, stopped at the time limit.",
     "Exact optimization"),
    ("Greedy + MILP warm start", :milp_w_greedy_warm_start,  true,
     "Runs Greedy first and gives its answer to the MILP solver as a starting point.", "Exact optimization"),
    ("Genetic algorithm",        :genetic_algorithm,         false,
     "Metaheuristic: evolves a population of task-priority orders (selection, crossover, mutation).",
     "Metaheuristic"),
    ("Particle swarm",           :particle_swarm,            false,
     "Metaheuristic: a swarm of task-priority orders moves towards the best ones found (PSO).",
     "Metaheuristic"),
    ("Simulated annealing",      :simulated_annealing,       false,
     "Metaheuristic: changes one task-priority order step by step, sometimes accepting a worse one early on.",
     "Metaheuristic"),
    ("Random search",            :random_search,             false,
     "Control for the metaheuristics: the same budget of candidates, drawn at random with no search operators.",
     "Metaheuristic"),
]

"""Short names that are also accepted for ASSIGNMENT_METHOD."""
const ASSIGNMENT_ALIASES = Dict("ga" => "Genetic algorithm", "pso" => "Particle swarm",
    "particleswarmoptimizer" => "Particle swarm", "particleswarmoptimization" => "Particle swarm",
    "sa" => "Simulated annealing", "mcf" => "Most complex first", "nsf" => "Nearest station first",
    "warmstart" => "Greedy + MILP warm start", "milpwarmstart" => "Greedy + MILP warm start",
    "rs" => "Random search", "random" => "Random search", "greedytravel" => "Greedy with travel")

const SEARCH_MODES = (:genetic_algorithm, :particle_swarm, :simulated_annealing, :random_search)
_is_search(sym) = sym in SEARCH_MODES

"""Fixed colour per assignment method, used by every chart."""
const METHOD_COLORS = Dict(
    "Greedy" => "#4e79a7", "Most complex first" => "#76b7b2", "Nearest station first" => "#59a14f",
    "MILP" => "#b07aa1", "Greedy + MILP warm start" => "#9c755f", "Genetic algorithm" => "#f28e2b",
    "Particle swarm" => "#e15759", "Simulated annealing" => "#edc948", "Greedy with travel" => "#86bcb6",
    "Random search" => "#bab0ac")
_method_color(name, i=1) = get(METHOD_COLORS, string(name), ("#4e79a7", "#f28e2b", "#e15759", "#76b7b2",
                                                            "#59a14f", "#edc948", "#b07aa1", "#9c755f")[mod1(i, 8)])

"""Optimization solvers (the `milp_optimizer` argument). Only used by MILP methods."""
const SOLVERS = [
    # friendly name, symbol,   free?,  description
    ("HiGHS",  :highs,  true,  "Open-source (MIT licence). Recommended default."),
    ("GLPK",   :glpk,   true,  "Open-source (GPL-3.0). Cannot be used with 'Greedy + MILP warm start'."),
    ("Gurobi", :gurobi, false, "Commercial. Needs your own valid Gurobi licence (free academic licences exist)."),
]

"""
Movement profiles: presets for the three movement / collision-avoidance flags
of `run_lego_demo` (`rvo_flag`, `tangent_bug_flag`, `dispersion_flag`).
"""
const MOVEMENT_PROFILES = [
    # friendly name,          rvo,   tangent bug, dispersion, description
    ("Recommended",           true,  true,  true,
     "RVO2 + Tangent Bug + Dispersion all on (the configuration of the repository's hosted demos)."),
    ("No RVO2",               false, true,  true,
     "Turns off RVO2 reciprocal collision avoidance. Note: in this version of the code the dispersion " *
     "velocity adjustment is only applied while RVO2 is on, so dispersion has little effect here."),
    ("No Tangent Bug",        true,  false, true,
     "Robots head straight for their goal instead of steering around construction sites."),
    ("No Dispersion",         true,  true,  false,
     "Ablation only: the simulator itself warns that RVO2 on + dispersion off is not recommended."),
    ("No avoidance methods",  false, false, false,
     "All three modules off: robots move straight to their goals and may pass through each other."),
]

const SIZE_TEXT = Dict(:small => "small", :medium => "medium", :large => "large", :very_large => "very large")

# Lookup helpers --------------------------------------------------------------

_norm(s) = lowercase(replace(strip(string(s)), r"[\s_\-\(\)\+]+" => ""))

function _lookup(table, name, what)
    key = _norm(name)
    table === ASSIGNMENT_METHODS && (key = _norm(get(ASSIGNMENT_ALIASES, key, key)))
    for row in table
        if _norm(row[1]) == key || _norm(row[2]) == key
            return row
        end
    end
    valid = join(["\"$(r[1])\"" for r in table], ", ")
    throw(ConfigError("Unknown $what \"$name\". Valid choices are: $valid."))
end

"""Raised for any invalid notebook setting. The message is written for the user."""
struct ConfigError <: Exception
    msg::String
end
Base.showerror(io::IO, e::ConfigError) = print(io, "Settings problem: ", e.msg)

# -----------------------------------------------------------------------------
# Experiment settings
# -----------------------------------------------------------------------------

"""
    ExperimentConfig(; kwargs...)

One experiment, described with friendly names. Every field has a default.
`movement = "Custom"` uses the three `custom_*` flags instead of a preset.
"""
Base.@kwdef struct ExperimentConfig
    model::String = "Tractor"
    num_robots::Union{Nothing,Int} = nothing        # nothing = model default
    assignment::String = "Greedy"
    solver::String = "HiGHS"
    movement::String = "Recommended"
    custom_rvo::Bool = true
    custom_tangent_bug::Bool = true
    custom_dispersion::Bool = true
    seed::Int = 1
    optimizer_time_limit_s::Int = 60                # MILP solver, or metaheuristic search
    search_iterations::Int = 25                     # metaheuristics: iterations (generations)
    search_population::Int = 16                     # metaheuristics: population / swarm size
    simulate_top_plans::Int = 0                     # metaheuristics: choose among Greedy and this many best plans by simulating them
    save_animation::Bool = false
    smooth_animation::Bool = false                  # run_lego_demo `update_anim_at_every_step`
    save_results::Bool = true
    reuse_results::Bool = true                      # return an identical earlier run instead of simulating again
    allow_large_models::Bool = false
    max_steps::Int = 100000                         # run_lego_demo default
    max_iters_no_progress::Int = 10000              # run_lego_demo default
    label::String = ""
end

"""
    make_config(; MODEL, NUMBER_OF_ROBOTS, ...) -> ExperimentConfig

Build a configuration from the notebook's setting variables, turning type
mistakes (for example `NUMBER_OF_ROBOTS = "10"` or `SAVE_RESULTS = "yes"`)
into a plain-English message instead of a Julia type error. The full
validation happens in `validate_config`.
"""
function make_config(; model, num_robots=nothing, assignment="Greedy", solver="HiGHS", movement="Recommended",
                     seed=1, optimizer_time_limit_s=60, search_iterations=25, search_population=16,
                     simulate_top_plans=0, save_animation=false, save_results=true, reuse_results=true,
                     custom_rvo=true, custom_tangent_bug=true, custom_dispersion=true, smooth_animation=false,
                     allow_large_models=false, max_steps=100000, max_iters_no_progress=10000, label="")
    text(name, x) = x isa AbstractString ? String(x) :
                    throw(ConfigError("$name must be text in double quotes, e.g. \"Tractor\". You entered: $(repr(x))."))
    flag(name, x) = x isa Bool ? x :
                    throw(ConfigError("$name must be true or false (no quotes). You entered: $(repr(x))."))
    whole(name, x) = (x isa Integer || (x isa AbstractFloat && isinteger(x))) ? Int(x) :
                     throw(ConfigError("$name must be a whole number without quotes, e.g. 10. You entered: $(repr(x))."))
    robots = num_robots === nothing ? nothing : whole("NUMBER_OF_ROBOTS", num_robots)
    cfg = ExperimentConfig(;
        model=text("MODEL", model), num_robots=robots, assignment=text("ASSIGNMENT_METHOD", assignment),
        solver=text("SOLVER", solver), movement=text("MOVEMENT_PROFILE", movement),
        seed=whole("RANDOM_SEED", seed), optimizer_time_limit_s=whole("TIME_LIMIT_SECONDS", optimizer_time_limit_s),
        search_iterations=whole("SEARCH_ITERATIONS", search_iterations),
        search_population=whole("SEARCH_POPULATION", search_population),
        simulate_top_plans=whole("SIMULATE_TOP_PLANS", simulate_top_plans),
        save_animation=flag("SAVE_ANIMATION", save_animation), save_results=flag("SAVE_RESULTS", save_results),
        reuse_results=flag("REUSE_PREVIOUS_RESULTS", reuse_results),
        custom_rvo=flag("CUSTOM_RVO2", custom_rvo), custom_tangent_bug=flag("CUSTOM_TANGENT_BUG", custom_tangent_bug),
        custom_dispersion=flag("CUSTOM_DISPERSION", custom_dispersion),
        smooth_animation=flag("SMOOTH_ANIMATION", smooth_animation),
        allow_large_models=flag("ALLOW_LARGE_MODELS", allow_large_models),
        max_steps=whole("MAX_SIMULATION_STEPS", max_steps),
        max_iters_no_progress=whole("MAX_STEPS_WITHOUT_PROGRESS", max_iters_no_progress), label=text("label", label))
    return cfg
end

"""
    check_settings(cfg) -> cfg

Validate and print a plain-English summary of what will be run. Stops the
notebook with a clear "Settings problem" message if a setting is invalid.
"""
function check_settings(cfg::ExperimentConfig)
    v = validate_config(cfg)
    rows = Any[
        ["Model", v.model, "$(v.n_parts) parts, file LDraw_files/$(v.ldraw_file), scale $(v.model_scale)"],
        ["Number of robots", v.num_robots, v.robots_source],
        ["Assignment method", v.assignment, "$(v.family); run_lego_demo(assignment_mode = :$(v.assignment_mode))"],
        ["Solver", v.solver, v.uses_solver ? "milp_optimizer = :$(v.milp_optimizer), time limit $(v.optimizer_time_limit_s) s" :
                             "$(v.assignment) does not use an optimization solver"],
        ["Movement profile", v.movement,
         "rvo_flag = $(v.rvo_flag), tangent_bug_flag = $(v.tangent_bug_flag), dispersion_flag = $(v.dispersion_flag)"],
        ["Random seed", v.seed, "rng = MersenneTwister($(v.seed)); sets the robots' starting positions"],
        ["Save animation", v.save_animation, v.smooth_animation ? "smooth (every step; slower)" : "updated at task completions"],
        ["Save results", v.save_results, v.save_results ? "new folder under $(_display_path(joinpath(results_root(), "runs")))" :
                                          "nothing is kept on disk"],
        ["Reuse earlier results", cfg.reuse_results, cfg.reuse_results ?
            "an earlier run with identical settings and code is returned instead of simulating again" :
            "every run is simulated again"],
    ]
    if v.is_search
        insert!(rows, 5, ["Search budget", "$(v.search_iterations) × $(v.search_population)",
            "metaheuristic_iterations = $(v.search_iterations), metaheuristic_population = $(v.search_population); " *
            "stops early at optimizer_time_limit = $(v.optimizer_time_limit_s) s"])
    end
    _display_table(["Setting", "Value", "Passed to the simulator as"], rows; title="Settings are valid")
    for w in v.warnings
        println("Note: ", w)
    end
    return cfg
end

"""Folder of the batch that produced `records` (or `nothing`)."""
function batch_folder(records)
    records === nothing && return nothing
    ids = unique(skipmissing([get(r, :batch_id, missing) for r in records]))
    isempty(ids) && return nothing
    return joinpath(results_root(), "batches", string(first(ids)))
end

"""Copy of `cfg` with some fields replaced: `modify(cfg; seed=2)`."""
function modify(cfg::ExperimentConfig; kwargs...)
    fields = Dict{Symbol,Any}(f => getfield(cfg, f) for f in fieldnames(ExperimentConfig))
    for (k, v) in kwargs
        haskey(fields, k) || throw(ConfigError("ExperimentConfig has no setting called `$k`."))
        fields[k] = v
    end
    return ExperimentConfig(; fields...)
end

"""
    validate_config(cfg) -> NamedTuple

Check every setting and translate it into the simulator's real arguments.
Throws `ConfigError` with a plain-English explanation if something is wrong.
Returns `(; ..., warnings)`.
"""
function validate_config(cfg::ExperimentConfig)
    warnings = String[]
    root = repo_root()

    # Model
    mrow = _lookup(MODEL_INFO, cfg.model, "model")
    model_name, model_sym, n_parts, n_asm, ref_time, size_class = mrow
    params = try
        get_project_params(model_sym)
    catch
        throw(ConfigError("Model \"$model_name\" is not registered in src/project_params.jl of this checkout."))
    end
    model_file = joinpath(root, "LDraw_files", params[:file_name])
    if !isfile(model_file)
        throw(ConfigError("The model file for \"$model_name\" was not found at\n    $model_file\n" *
                          "Restore the LDraw_files folder of the repository (e.g. `git checkout -- LDraw_files`)."))
    end
    if size_class in (:large, :very_large) && !cfg.allow_large_models
        throw(ConfigError("\"$model_name\" is a $(SIZE_TEXT[size_class]) model ($n_parts parts; reference run " *
                          "time $ref_time, and far longer with MILP). To run it on purpose, set " *
                          "ALLOW_LARGE_MODELS = true in the Advanced settings cell."))
    end

    # Robots
    num_robots = cfg.num_robots === nothing ? params[:num_robots] : cfg.num_robots
    robots_source = cfg.num_robots === nothing ? "model default" : "user setting"
    if !(num_robots isa Integer) || num_robots < 1
        throw(ConfigError("NUMBER_OF_ROBOTS must be `nothing` (use the model default of $(params[:num_robots])) " *
                          "or a whole number of at least 1. You entered: $(repr(cfg.num_robots))."))
    end
    if num_robots > 500
        throw(ConfigError("NUMBER_OF_ROBOTS = $num_robots is above this notebook's safety limit of 500."))
    end

    # Assignment and solver
    arow = _lookup(ASSIGNMENT_METHODS, cfg.assignment, "assignment method")
    assignment_name, assignment_sym, uses_solver, _ = arow
    srow = _lookup(SOLVERS, cfg.solver, "solver")
    solver_name, solver_sym, _, _ = srow
    if !uses_solver
        solver_name = "not used"
    else
        if solver_sym == :glpk && assignment_sym == :milp_w_greedy_warm_start
            throw(ConfigError("GLPK cannot be combined with \"Greedy + MILP warm start\". The simulator's own " *
                              "warning (src/full_demo.jl) says GLPK is not implemented through JuMP to support " *
                              "warm starts, so the greedy starting point would be ignored. Use SOLVER = \"HiGHS\" " *
                              "(free) or \"Gurobi\" (licensed)."))
        end
        ok, why = solver_status(solver_sym)
        ok || throw(ConfigError("Solver $solver_name is not usable on this computer: $why"))
    end
    if cfg.optimizer_time_limit_s < 1
        throw(ConfigError("TIME_LIMIT_SECONDS must be a whole number of seconds, at least 1."))
    end
    is_search = _is_search(assignment_sym)
    if is_search
        1 <= cfg.search_iterations <= 1000 ||
            throw(ConfigError("SEARCH_ITERATIONS must be a whole number from 1 to 1000. You entered: $(cfg.search_iterations)."))
        2 <= cfg.search_population <= 500 ||
            throw(ConfigError("SEARCH_POPULATION must be a whole number from 2 to 500. You entered: $(cfg.search_population)."))
        if size_class != :small
            push!(warnings, "Metaheuristics build the whole schedule once per candidate " *
                            "($(cfg.search_iterations) × $(cfg.search_population) candidates); on a $(SIZE_TEXT[size_class]) " *
                            "model the search will probably stop at the $(cfg.optimizer_time_limit_s) s time limit.")
        end
    end
    0 <= cfg.simulate_top_plans <= 50 ||
        throw(ConfigError("SIMULATE_TOP_PLANS must be a whole number from 0 to 50. You entered: $(cfg.simulate_top_plans)."))
    if cfg.simulate_top_plans > 0 && !is_search
        throw(ConfigError("SIMULATE_TOP_PLANS only works with a metaheuristic, because only a search has several plans to " *
                          "choose from. Set it to 0 for \"$assignment_name\"."))
    end
    if (uses_solver || is_search) && cfg.optimizer_time_limit_s > 3600
        push!(warnings, "The optimizer time limit is over one hour per run.")
    end

    # Movement
    if _norm(cfg.movement) == "custom"
        movement_name = "Custom"
        rvo, tb, disp = cfg.custom_rvo, cfg.custom_tangent_bug, cfg.custom_dispersion
    else
        prow = _lookup(MOVEMENT_PROFILES, cfg.movement, "movement profile")
        movement_name, rvo, tb, disp = prow[1], prow[2], prow[3], prow[4]
    end
    if rvo && !disp
        push!(warnings, "RVO2 is on but dispersion is off. The simulator warns that this is not recommended.")
    end
    if !rvo && disp
        push!(warnings, "Dispersion is on but RVO2 is off. In this version of the code the dispersion velocity " *
                        "adjustment is applied only while RVO2 is on.")
    end
    # rvo2 is needed even when rvo_flag = false (src/route_planning.jl always builds an RVO simulator).
    rvo_ok, rvo_why = rvo2_status()
    rvo_ok || throw(ConfigError("The Python module `rvo2` cannot be imported, and the simulator needs it for " *
                                "every run (even with RVO2 off). $rvo_why See notebooks/SETUP.md, step 3."))

    # Other
    cfg.seed >= 0 || throw(ConfigError("RANDOM_SEED must be a whole number of 0 or more."))
    cfg.max_steps >= 1 || throw(ConfigError("MAX_SIMULATION_STEPS must be at least 1."))
    cfg.max_iters_no_progress >= 1 || throw(ConfigError("MAX_STEPS_WITHOUT_PROGRESS must be at least 1."))
    if cfg.smooth_animation && !cfg.save_animation
        push!(warnings, "SMOOTH_ANIMATION has no effect because SAVE_ANIMATION is false.")
    end
    if cfg.save_animation && !cfg.save_results
        push!(warnings, "SAVE_ANIMATION is true but SAVE_RESULTS is false: the animation is written to a " *
                        "temporary folder that is deleted after the run, so it cannot be viewed.")
    end

    return (
        model=model_name, model_symbol=model_sym, model_file=model_file, ldraw_file=params[:file_name],
        project_name=params[:project_name], model_scale=Float64(params[:model_scale]),
        default_robots=params[:num_robots], num_robots=Int(num_robots), robots_source=robots_source,
        size_class=size_class, n_parts=n_parts,
        assignment=assignment_name, assignment_mode=assignment_sym, uses_solver=uses_solver,
        family=arow[5], is_search=is_search, search_iterations=cfg.search_iterations,
        simulate_top_plans=cfg.simulate_top_plans,
        search_population=cfg.search_population, solver=solver_name, milp_optimizer=solver_sym,
        movement=movement_name, rvo_flag=rvo, tangent_bug_flag=tb, dispersion_flag=disp,
        seed=cfg.seed, optimizer_time_limit_s=cfg.optimizer_time_limit_s,
        save_animation=cfg.save_animation, smooth_animation=cfg.smooth_animation,
        save_results=cfg.save_results, max_steps=cfg.max_steps,
        max_iters_no_progress=cfg.max_iters_no_progress, label=cfg.label, warnings=warnings,
    )
end

# -----------------------------------------------------------------------------
# Environment
# -----------------------------------------------------------------------------

const LAB_STATE = Dict{Symbol,Any}()   # repo root, results folder, solver and rvo2 status

"""Normalized absolute path; on Windows the drive letter is upper-cased (VS Code often uses a lower-case one)."""
function _canon(p::AbstractString)
    q = normpath(abspath(p))
    if Sys.iswindows() && length(q) >= 2 && q[2] == ':'
        q = uppercase(q[1:1]) * q[2:end]
    end
    return String(rstrip(q, ['\\', '/']))
end
_samepath(a, b) = Sys.iswindows() ? lowercase(_canon(a)) == lowercase(_canon(b)) : _canon(a) == _canon(b)

repo_root() = get(LAB_STATE, :repo_root) do
    _canon(joinpath(dirname(pathof(ConstructionBots)), ".."))
end
results_root() = get(LAB_STATE, :results_root) do
    joinpath(repo_root(), "results", "notebook_lab")
end

"""Is the Python module rvo2 importable through PyCall?  -> (ok, explanation)"""
function rvo2_status()
    haskey(LAB_STATE, :rvo2) && return LAB_STATE[:rvo2]
    res = try
        m = pyimport("rvo2")
        (true, "rvo2 found at $(m.__file__)")
    catch e
        (false, "PyCall uses $(PyCall.python), which has no working `rvo2` module.")
    end
    res[1] && (LAB_STATE[:rvo2] = res)   # only cache success, so a fixed install is picked up
    return res
end

"""Can this solver be created right now? -> (ok, explanation)"""
function solver_status(sym::Symbol)
    key = Symbol(:solver_, sym)
    haskey(LAB_STATE, key) && return LAB_STATE[key]
    res = try
        if sym == :highs
            HiGHS.Optimizer(); (true, "HiGHS $(pkgversion(HiGHS)) is ready.")
        elseif sym == :glpk
            GLPK.Optimizer(); (true, "GLPK.jl $(pkgversion(GLPK)) is ready.")
        elseif sym == :gurobi
            redirect_stdout(devnull) do
                Gurobi.Env()
            end
            (true, "Gurobi licence found.")
        else
            (false, "unknown solver")
        end
    catch e
        # Gurobi messages embed user name, host name and host ID; never show or save those.
        msg = replace(sprint(showerror, e), r"\s*\(user [^)]*\)" => "")
        if sym == :gurobi
            (false, "no valid Gurobi licence was found (Gurobi.jl reported: " *
                    "$(first(split(msg, '\n'))[1:min(end, 160)])). Gurobi is optional: use HiGHS, or see " *
                    "notebooks/SETUP.md, 'Optional: Gurobi'.")
        else
            (false, first(split(msg, '\n')))
        end
    end
    LAB_STATE[key] = res
    return res
end

"""
    lab_setup(; repo_root, ldraw_library=nothing, results_folder=nothing)

Called once by the notebook's setup cell. Records paths and optionally points
LDrawParser at a non-default parts library.
"""
function lab_setup(; repo_root::AbstractString, ldraw_library=nothing, results_folder=nothing)
    LAB_STATE[:repo_root] = _canon(repo_root)
    LAB_STATE[:results_root] = results_folder === nothing ?
                               joinpath(_canon(repo_root), "results", "notebook_lab") : _canon(results_folder)
    if ldraw_library !== nothing
        LDrawParser.set_part_library_dir!(normpath(ldraw_library))
    end
    # In Jupyter, ProgressMeter's default refresh clears the *whole* cell output (including this
    # notebook's progress messages); append mode keeps everything visible.
    _in_notebook() && ProgressMeter.ijulia_behavior(:append)
    return nothing
end

"""
    check_environment(; solvers=[:highs, :glpk, :gurobi]) -> Vector of (item, ok, detail)

Run every installation check and display the result as a table.
Returns `true` when everything required for the default experiment is ready.
"""
function check_environment(; show=true)
    rows = Tuple{String,Symbol,String}[]   # item, :ok / :warn / :fail, detail
    add(item, status, detail) = push!(rows, (item, status, detail))

    add("Julia", VERSION >= v"1.10" ? :ok : :fail, "version $VERSION")
    proj = Base.active_project()
    root = repo_root()
    same = proj !== nothing && _samepath(dirname(proj), root)
    add("Active Julia project", same ? :ok : :fail,
        same ? proj : "Active project is $(repr(proj)), expected $(joinpath(root, "Project.toml")).")
    add("ConstructionBots package", :ok, "version $(pkgversion(ConstructionBots)) loaded from $(dirname(pathof(ConstructionBots)))")
    version = ConstructionBots.code_version()
    add("Code version", :ok, "source hash $(version[:SourceHash]), commit $(version[:GitCommit])" *
                             (version[:GitDirty] ? " with uncommitted changes in src/" : ""))

    # Models
    missing_models = String[]
    for (name, sym, _...) in MODEL_INFO
        p = get_project_params(sym)
        isfile(joinpath(root, "LDraw_files", p[:file_name])) || push!(missing_models, name)
    end
    add("Model files (LDraw_files/)", isempty(missing_models) ? :ok : :fail,
        isempty(missing_models) ? "all $(length(MODEL_INFO)) registered models found" :
        "missing: " * join(missing_models, ", "))

    # LDraw parts library
    lib = normpath(LDrawParser.get_part_library_dir())
    parts_dir = joinpath(lib, "parts")
    if isdir(parts_dir)
        n = count(f -> endswith(lowercase(f), ".dat"), readdir(parts_dir))
        add("LDraw Parts Library", n > 1000 ? :ok : :warn, "$lib ($n part files)")
    else
        add("LDraw Parts Library", :fail, "not found at $lib. Download it (notebooks/SETUP.md, step 2) " *
                                          "or set LDRAW_LIBRARY_OVERRIDE in the setup cell.")
    end

    # Python / RVO2
    add("Python used by PyCall", :ok, "$(PyCall.python) (Python $(PyCall.pyversion))")
    ok, why = rvo2_status()
    add("Python module rvo2", ok ? :ok : :fail, ok ? why : why * " Needed for every run; see notebooks/SETUP.md, step 3.")

    # Solvers
    for (name, sym, free, _) in SOLVERS
        ok, why = solver_status(sym)
        status = ok ? :ok : (free ? :fail : :warn)
        add("Solver: $name", status, why * (free ? "" : (ok ? "" : " (optional)")))
    end

    # Results folder
    rr = results_root()
    writable = try
        mkpath(rr)
        probe = joinpath(rr, ".write_test_$(getpid())")
        write(probe, "ok"); rm(probe)
        true
    catch
        false
    end
    add("Results folder", writable ? :ok : :fail, writable ? "$rr (writable)" : "$rr is not writable")

    if show
        _display_table(["Check", "Status", "Details"],
            [[r[1], Dict(:ok => "OK", :warn => "WARNING", :fail => "PROBLEM")[r[2]], r[3]] for r in rows];
            title="Environment check")
    end
    required_ok = all(r -> r[2] != :fail || startswith(r[1], "Solver: GLPK"), rows)
    return required_ok
end

# -----------------------------------------------------------------------------
# Running experiments
# -----------------------------------------------------------------------------

"""Columns written to every results CSV, in this order."""
const CSV_COLUMNS = [
    :run_id, :started_at, :status, :status_detail, :label, :batch_id,
    :model, :model_file, :model_scale, :num_robots, :robots_source,
    :assignment_method, :assignment_mode, :solver, :movement_profile,
    :rvo_flag, :tangent_bug_flag, :dispersion_flag, :random_seed, :optimizer_time_limit_s,
    :makespan_s, :optimistic_makespan_s, :robot_min_gap_m, :robot_overlap_steps, :min_gap_m, :overlap_steps,
    :position_swaps, :max_speed_mps, :assignment_time_s, :pre_execution_runtime_s,
    :execution_runtime_s, :total_wall_time_s, :valid_milp_solution, :num_objects, :num_assemblies,
    :includes_one_time_compilation, :run_folder, :stats_file, :animation_file, :error_message,
    :assignment_family, :search_iterations, :search_population, :search_evaluations, :search_timed_out,
    :search_kept_greedy, :selected_plan, :solver_status, :solver_gap, :solver_bound, :source_hash, :git_commit,
]

"""Per-run data kept in result.toml (and reused with a run) but not in the CSV files."""
const EXTRA_RESULT_KEYS = (:search_history, :assignment_plan, :top_plan_makespans)

const _COMPILED_PATHS = Set{Any}()     # code paths already run in this Julia session

_path_key(v) = (v.assignment_mode, v.uses_solver ? v.milp_optimizer : :none, v.rvo_flag, v.tangent_bug_flag,
                v.dispersion_flag, v.save_animation)

function _new_run_id(v)
    stamp = Dates.format(now(), "yyyymmdd-HHMMSS-sss")
    tag = string(v.model_symbol, "_", v.assignment_mode)
    v.uses_solver && (tag *= "-" * string(v.milp_optimizer))
    return string(stamp, "_", tag, "_", randstring(RandomDevice(), 'a':'z', 4))
end

function _empty_record(cfg::ExperimentConfig)
    rec = Dict{Symbol,Any}(c => missing for c in CSV_COLUMNS)
    rec[:started_at] = Dates.format(now(), "yyyy-mm-dd HH:MM:SS")
    rec[:model] = cfg.model
    rec[:assignment_method] = cfg.assignment
    rec[:solver] = cfg.solver
    rec[:movement_profile] = cfg.movement
    rec[:random_seed] = cfg.seed
    rec[:optimizer_time_limit_s] = cfg.optimizer_time_limit_s
    rec[:label] = cfg.label
    return rec
end

_finite(x) = (x isa Real && isfinite(x)) ? Float64(x) : missing

# Reusing earlier results ------------------------------------------------------

"""
    _result_cache_key(v) -> String or missing

Text that identifies everything that changes a simulated result: model, robots, assignment method, solver and its
time limit, movement flags, seed, step limits, and the code version. Two runs with the same key give the same result
(for the MILP methods, within the same time limit, which is not exactly reproducible). The code version is the hash
of the simulator's source files and package versions, so any change to them means nothing is reused.
"""
function _result_cache_key(v)
    return join(["source=" * ConstructionBots.SOURCE_HASH, "julia=" * string(VERSION),
                 "ldraw=" * string(v.ldraw_file), "project=" * string(v.project_name),
                 "scale=" * string(v.model_scale), "robots=" * string(v.num_robots),
                 "assignment=" * string(v.assignment_mode),
                 "solver=" * string(v.uses_solver ? v.milp_optimizer : :none),
                 "time_limit=" * string(v.uses_solver || v.is_search ? v.optimizer_time_limit_s : 0),
                 "search=" * (v.is_search ? "$(v.search_iterations)x$(v.search_population)" : "none"),
                 "simulate_top_plans=$(v.simulate_top_plans)",
                 "rvo=$(v.rvo_flag)", "tangent_bug=$(v.tangent_bug_flag)", "dispersion=$(v.dispersion_flag)",
                 "seed=$(v.seed)", "max_steps=$(v.max_steps)", "max_no_progress=$(v.max_iters_no_progress)"], " | ")
end

"""Absolute path for a path stored in a result file (those are relative to the repository). `""` stays `""`."""
_resolve_path(p::AbstractString) = isempty(p) ? "" : (isabspath(p) ? p : joinpath(repo_root(), p))

"""
    _find_reusable_run(key; need_animation) -> Dict or nothing

The newest earlier run with this key that finished (status success or incomplete) and whose folder still exists.
With `need_animation`, that run must also have saved an animation file.
"""
function _find_reusable_run(key::AbstractString; need_animation::Bool)
    for f in reverse(_find_files(joinpath(results_root(), "runs"), "result.toml"))
        d = try
            TOML.parsefile(f)
        catch
            continue
        end
        get(d, "cache_key", "") == key || continue
        get(d, "status", "") in ("success", "incomplete") || continue
        isdir(_resolve_path(get(d, "run_folder", ""))) || continue
        need_animation && !isfile(_resolve_path(get(d, "animation_file", ""))) && continue
        return d
    end
    return nothing
end

"""Fill `rec` with the stored result of an earlier run. Keeps this run's id, start time, batch and label."""
function _apply_reuse!(rec, earlier::AbstractDict, earlier_run_id)
    for c in (CSV_COLUMNS..., EXTRA_RESULT_KEYS...)
        c in (:run_id, :started_at, :batch_id, :label) && continue
        val = get(earlier, string(c), "")
        val == "" || (rec[c] = val)     # "" is how an empty cell is stored
    end
    rec[:status_detail] = "reused the saved result of run $earlier_run_id; nothing was simulated again"
    rec[:total_wall_time_s] = 0.0
    rec[:includes_one_time_compilation] = false
    return rec
end

"""
    run_experiment(cfg::ExperimentConfig; batch_id=missing, verbose=true) -> Dict

Validate `cfg`, run `ConstructionBots.run_lego_demo`, and return one result
record. Never throws for an ordinary failure: the record's `:status` is one of

- "success"    the simulated project was completed;
- "incomplete" the simulation ran but stopped before the project was finished
               (step limit or no progress); completion time is left empty;
- "failed"     an error occurred (the message is in `:error_message`);
- "rejected"   the settings were invalid, nothing was run.

With `reuse_results = true` (the default), an earlier run with the same settings and code version is returned
instead of simulating again. Its record says so in `:status_detail`, has `:total_wall_time_s = 0`, and points to the
earlier run's folder.

Pressing the notebook's Interrupt button is passed through (InterruptException).
"""
function run_experiment(cfg::ExperimentConfig; batch_id=missing, verbose::Bool=true, show_simulator_log::Bool=false)
    rec = _empty_record(cfg)
    rec[:batch_id] = batch_id
    v = try
        validate_config(cfg)
    catch e
        e isa ConfigError || rethrow()
        rec[:run_id] = "rejected-" * Dates.format(now(), "yyyymmdd-HHMMSS-sss")
        rec[:status] = "rejected"
        rec[:status_detail] = "invalid settings; nothing was run"
        rec[:error_message] = e.msg
        verbose && println("NOT RUN. ", e.msg)
        return rec
    end
    for w in v.warnings
        verbose && println("Note: ", w)
    end

    run_id = _new_run_id(v)
    rec[:run_id] = run_id
    rec[:model] = v.model
    rec[:model_file] = v.ldraw_file
    rec[:model_scale] = v.model_scale
    rec[:num_robots] = v.num_robots
    rec[:robots_source] = v.robots_source
    rec[:assignment_method] = v.assignment
    rec[:assignment_mode] = string(v.assignment_mode)
    rec[:assignment_family] = v.family
    rec[:solver] = v.solver
    rec[:movement_profile] = v.movement
    rec[:rvo_flag] = v.rvo_flag
    rec[:tangent_bug_flag] = v.tangent_bug_flag
    rec[:dispersion_flag] = v.dispersion_flag
    rec[:optimizer_time_limit_s] = v.uses_solver || v.is_search ? v.optimizer_time_limit_s : missing
    rec[:search_iterations] = v.is_search ? v.search_iterations : missing
    rec[:search_population] = v.is_search ? v.search_population : missing
    if isempty(cfg.label)   # descriptive default label (no seed, so repeated trials group together)
        rec[:label] = string(v.model, ", ", v.num_robots, " robots | ", v.assignment,
                             v.uses_solver ? " + " * v.solver : "", " | ", v.movement)
    end
    key = _path_key(v)
    rec[:includes_one_time_compilation] = !(key in _COMPILED_PATHS)

    # Reuse: an identical earlier run is returned instead of simulating again.
    cache_key = _result_cache_key(v)
    rec[:cache_key] = cache_key          # stored in result.toml only, so later runs can find this one
    if cfg.reuse_results
        earlier = _find_reusable_run(cache_key; need_animation=v.save_animation)
        if earlier !== nothing
            earlier_id = get(earlier, "run_id", "?")
            _apply_reuse!(rec, earlier, earlier_id)
            if verbose
                println("Run $run_id")
                println("  Reused the saved result of run $earlier_id (same settings and code). Nothing was simulated.")
                println("  Status: ", uppercase(rec[:status]), " (", rec[:status_detail], ")")
            end
            v.save_results && _append_csv(joinpath(results_root(), "all_runs.csv"), [rec])
            return rec
        end
    end

    # Output folder: a new, never-reused folder per run. When results are not
    # saved, the simulator still needs a folder, so a temporary one is used.
    if v.save_results
        run_dir = joinpath(results_root(), "runs", run_id)
        ispath(run_dir) && error("Refusing to reuse existing folder $run_dir")
        mkpath(run_dir)
        rec[:run_folder] = run_dir
    else
        run_dir = mktempdir(; prefix="cb_lab_")
    end
    sim_dir = joinpath(run_dir, "simulator_output")

    if v.save_results
        _write_toml(joinpath(run_dir, "effective_config.toml"), _effective_config(cfg, v, run_id))
    end

    if verbose
        println("Run $run_id")
        println("  Model: $(v.model) ($(v.num_robots) robots, $(v.robots_source)) | Assignment: $(v.assignment)",
                v.uses_solver ? " with $(v.solver), time limit $(v.optimizer_time_limit_s) s" : "",
                v.is_search ? " ($(v.search_iterations) iterations × $(v.search_population), at most " *
                              "$(v.optimizer_time_limit_s) s)" : "",
                " | Movement: $(v.movement) | Seed: $(v.seed)")
        rec[:includes_one_time_compilation] &&
            println("  First run of this configuration type in this session: expect up to a few minutes of one-time compilation.")
    end

    log_path = joinpath(run_dir, "simulator_log.txt")
    if verbose && !show_simulator_log
        println("  Running. The simulator's detailed console output goes to ",
                v.save_results ? _display_path(log_path) : "a temporary file",
                " (set SHOW_SIMULATOR_LOG = true to see it here).")
        v.uses_solver && println("  Task assignment with $(v.solver) may use the full $(v.optimizer_time_limit_s) s time limit.")
    end

    t0 = time()
    stats = nothing
    try
        _, stats = _with_log(show_simulator_log, log_path) do
            ConstructionBots.run_lego_demo(;
                ldraw_file=v.ldraw_file,
                project_name=v.project_name,
                model_scale=v.model_scale,
                num_robots=v.num_robots,
                assignment_mode=v.assignment_mode,
                milp_optimizer=v.milp_optimizer,
                optimizer_time_limit=v.optimizer_time_limit_s,
                metaheuristic_iterations=v.search_iterations,
                metaheuristic_population=v.search_population,
                simulate_top_plans=v.simulate_top_plans,
                rvo_flag=v.rvo_flag,
                tangent_bug_flag=v.tangent_bug_flag,
                dispersion_flag=v.dispersion_flag,
                rng=Random.MersenneTwister(v.seed),
                max_steps=v.max_steps,
                max_num_iters_no_progress=v.max_iters_no_progress,
                open_animation_at_end=false,           # never launch a browser automatically
                save_animation=v.save_animation,
                save_animation_along_the_way=false,
                update_anim_at_every_step=v.smooth_animation,
                anim_active_agents=v.save_animation,
                anim_active_areas=v.save_animation,
                base_results_path=run_dir,
                results_path=sim_dir,
                write_results=v.save_results,
                overwrite_results=false,
                look_for_previous_milp_solution=false, # never reuse solutions from other runs
                save_milp_solution=false,
                stop_after_task_assignment=false,
            )
        end
        push!(_COMPILED_PATHS, key)
    catch e
        if e isa InterruptException
            rec[:status] = "interrupted"
            rec[:status_detail] = "stopped by the user during the run"
            rec[:total_wall_time_s] = round(time() - t0; digits=2)
            _finish_record!(rec, v, run_dir)
            rethrow()
        end
        rec[:status] = "failed"
        msg = sprint(showerror, e)
        # The solver path was compiled even though no solution was found.
        e isa ConstructionBots.NoSolutionError && push!(_COMPILED_PATHS, key)
        if e isa ConstructionBots.NoSolutionError
            rec[:status_detail] = "the assignment solver found no feasible solution within the time limit"
        elseif e isa ConstructionBots.NoAssignmentError
            rec[:status_detail] = "no valid task assignment was found: $(e.msg) Try more robots."
        else
            rec[:status_detail] = "the simulator raised an error"
        end
        rec[:error_message] = first(sprint(showerror, e), 2000)
        if v.save_results
            open(joinpath(run_dir, "error.txt"), "w") do io
                showerror(io, e, catch_backtrace())
            end
        end
    end
    rec[:total_wall_time_s] = round(time() - t0; digits=2)

    if stats !== nothing
        rec[:makespan_s] = _finite(get(stats, :Makespan, missing))
        rec[:optimistic_makespan_s] = _finite(get(stats, :OptimisticMakespan, missing))
        rec[:assignment_time_s] = _finite(get(stats, :AssignmentTime, missing))
        rec[:robot_min_gap_m] = _finite(get(stats, :RobotMinGap, missing))
        rec[:robot_overlap_steps] = get(stats, :RobotOverlapSteps, missing)
        rec[:min_gap_m] = _finite(get(stats, :MinGap, missing))
        rec[:overlap_steps] = get(stats, :OverlapSteps, missing)
        rec[:position_swaps] = get(stats, :PositionSwaps, missing)
        rec[:max_speed_mps] = _finite(get(stats, :MaxSpeed, missing))
        rec[:solver_status] = get(stats, :TerminationStatus, missing)
        rec[:solver_gap] = _finite(get(stats, :RelativeGap, missing))
        rec[:solver_bound] = _finite(get(stats, :ObjectiveBound, missing))
        rec[:source_hash] = get(stats, :SourceHash, missing)
        rec[:git_commit] = string(get(stats, :GitCommit, "unknown"), get(stats, :GitDirty, false) ? "+dirty" : "")
        rec[:search_kept_greedy] = get(stats, :SearchKeptGreedy, missing)
        rec[:selected_plan] = get(stats, :SelectedPlan, missing)
        # The simulator's figure covers only the final rerun of the chosen plan; the total time covers all of it.
        v.simulate_top_plans > 0 && (rec[:assignment_time_s] = missing)
        rec[:top_plan_makespans] = get(stats, :TopPlanMakespans, missing)
        rec[:pre_execution_runtime_s] = _finite(get(stats, :PreExecutionRuntime, missing))
        rec[:execution_runtime_s] = _finite(get(stats, :ExecutionRuntime, missing))
        rec[:valid_milp_solution] = v.uses_solver ? get(stats, :ValidMILPSolution, missing) : missing
        rec[:search_evaluations] = get(stats, :SearchEvaluations, missing)
        rec[:search_timed_out] = get(stats, :SearchTimedOut, missing)
        rec[:search_history] = get(stats, :SearchHistory, missing)
        rec[:assignment_plan] = get(stats, :AssignmentPlan, missing)
        rec[:num_objects] = get(stats, :numobjects, missing)
        rec[:num_assemblies] = get(stats, :numassemblies, missing)
        if rec[:makespan_s] === missing
            rec[:status] = "incomplete"
            rec[:status_detail] = "the simulation stopped before the project was finished " *
                                  "(no progress for $(v.max_iters_no_progress) steps, or the $(v.max_steps)-step limit)"
        else
            rec[:status] = "success"
            rec[:status_detail] = "project completed"
        end
    end
    _finish_record!(rec, v, run_dir)
    v.save_results || rm(run_dir; recursive=true, force=true)
    if verbose
        println("  Status: ", uppercase(rec[:status]), " (", rec[:status_detail], ") after ",
                rec[:total_wall_time_s], " s of computer time.")
        rec[:error_message] !== missing && println("  Error: ", first(split(rec[:error_message], '\n')))
        if get(rec, :animation_objects, missing) !== missing
            println("  Animation: ", rec[:animation_objects], " moving objects, ", rec[:animation_keyframes],
                    " keyframes", rec[:animation_objects] == 0 ? " (NO MOVEMENT RECORDED)" : "",
                    ". View it with show_animation(...).")
        end
    end
    return rec
end

"""Path relative to the repository when it is inside it, otherwise absolute."""
function _display_path(p)
    rel = relpath(_canon(p), repo_root())
    return startswith(rel, "..") ? _canon(p) : rel
end

function _finish_record!(rec, v, run_dir)
    if v.save_results
        stats_files = _find_files(joinpath(run_dir, "simulator_output"), "stats.toml")
        anim_files = _find_files(joinpath(run_dir, "simulator_output"), "visualization.html")
        rec[:stats_file] = isempty(stats_files) ? missing : _display_path(stats_files[1])
        rec[:animation_file] = isempty(anim_files) ? missing : _display_path(anim_files[1])
        if !isempty(anim_files)
            # What the file really contains (an existing HTML file can still hold an empty animation).
            info = _animation_info(anim_files[1])
            rec[:animation_objects] = info.moving
            rec[:animation_keyframes] = info.keyframes
            rec[:animation_duration_s] = info.duration_s
        end
        rec[:run_folder] = _display_path(run_dir)
        _write_toml(joinpath(run_dir, "result.toml"), rec)
        _append_csv(joinpath(results_root(), "all_runs.csv"), [rec])
    end
    return rec
end

"""Run `f()`, sending standard output to `path` unless `show` is true."""
function _with_log(f, show::Bool, path)
    show && return f()
    return open(path, "w") do io
        redirect_stdout(f, io)
    end
end

_find_files(dir, suffix) = isdir(dir) ?
    sort([joinpath(r, f) for (r, _, fs) in walkdir(dir) for f in fs if endswith(f, suffix)]) : String[]

function _effective_config(cfg, v, run_id)
    d = Dict{String,Any}(
        "run_id" => run_id,
        "created_at" => Dates.format(now(), "yyyy-mm-dd HH:MM:SS"),
        "notebook_settings" => Dict(string(f) => _tomlable(getfield(cfg, f)) for f in fieldnames(ExperimentConfig)),
        "run_lego_demo_arguments" => Dict(
            "ldraw_file" => v.ldraw_file, "project_name" => v.project_name, "model_scale" => v.model_scale,
            "num_robots" => v.num_robots, "assignment_mode" => string(v.assignment_mode),
            "milp_optimizer" => string(v.milp_optimizer), "optimizer_time_limit" => v.optimizer_time_limit_s,
            "metaheuristic_iterations" => v.search_iterations, "metaheuristic_population" => v.search_population,
            "simulate_top_plans" => v.simulate_top_plans,
            "rvo_flag" => v.rvo_flag, "tangent_bug_flag" => v.tangent_bug_flag,
            "dispersion_flag" => v.dispersion_flag, "rng" => "MersenneTwister($(v.seed))",
            "max_steps" => v.max_steps, "max_num_iters_no_progress" => v.max_iters_no_progress,
            "save_animation" => v.save_animation, "update_anim_at_every_step" => v.smooth_animation,
            "write_results" => v.save_results, "look_for_previous_milp_solution" => false,
            "save_milp_solution" => false),
        "software" => software_versions(),
    )
    return d
end

"""Versions of the software that matter for reproducing a run."""
function software_versions()
    version = ConstructionBots.code_version()
    return Dict(
        "julia" => string(VERSION),
        "ConstructionBots" => string(pkgversion(ConstructionBots)),
        "source_hash" => version[:SourceHash],
        "git_commit" => version[:GitCommit],
        "src_has_uncommitted_changes" => version[:GitDirty],
        "HiGHS.jl" => string(pkgversion(HiGHS)),
        "GLPK.jl" => string(pkgversion(GLPK)),
        "Gurobi.jl" => string(pkgversion(Gurobi)),
        "LDrawParser" => string(pkgversion(LDrawParser)),
        "python" => string(PyCall.python),
        "python_version" => string(PyCall.pyversion),
        "ldraw_library" => LDrawParser.get_part_library_dir(),
        "os" => string(Sys.KERNEL, " ", Sys.MACHINE),
        "MeshCat.jl" => string(pkgversion(MeshCat)),
    )
end

_tomlable(x) = x === nothing ? "nothing (model default)" : x === missing ? "" : x
function _write_toml(path, d)
    clean = Dict{String,Any}(string(k) => (v isa AbstractDict ? Dict(string(a) => _tomlable(b) for (a, b) in v) :
                                           _tomlable(v)) for (k, v) in d)
    open(path, "w") do io
        TOML.print(io, clean; sorted=true)
    end
end

# -----------------------------------------------------------------------------
# Batches, presets, repeated trials
# -----------------------------------------------------------------------------

"""
    with_seeds(configs, seeds) -> Vector{ExperimentConfig}

Repeat every configuration once per seed. Competing methods get the same
(matched) seeds, so they start from the same robot positions.
"""
with_seeds(configs, seeds) = [modify(c; seed=s) for c in configs for s in seeds]

"""
    preset_configs(name; model="Tractor", num_robots=nothing, seed=1, time_limit=60, algorithms=[]) -> (configs, description)

Ready-made comparisons. Everything not being compared is held fixed. `"Custom"`
compares the assignment methods named in `algorithms`.
"""
function preset_configs(name::AbstractString; model="Tractor", num_robots=nothing, seed=1, time_limit=60,
                        save_animation=false, algorithms=String[], solver="HiGHS", search_iterations=25,
                        search_population=16)
    base = ExperimentConfig(; model=model, num_robots=num_robots, seed=seed, optimizer_time_limit_s=time_limit,
                            save_animation=save_animation, solver=solver, search_iterations=search_iterations,
                            search_population=search_population)
    methods(rows) = [modify(base; assignment=a[1], label=a[1]) for a in rows]
    key = _norm(name)
    if key in ("a", "baseline")
        return ([modify(base; label="Baseline")],
                "Preset A (Baseline): $model, Greedy assignment, Recommended movement.")
    elseif key in ("b", "assignmentcomparison", "assignment")
        cs = methods(filter(a -> a[1] == "Greedy" || a[3], ASSIGNMENT_METHODS))
        return (cs, "Preset B (Greedy vs MILP): Greedy vs MILP vs Greedy + MILP warm start. " *
                    "MILP methods use $solver. Model, robots, seed and movement are identical.")
    elseif key in ("f", "heuristics", "rules", "heuristicrules")
        cs = methods(filter(a -> a[5] == "Heuristic rule", ASSIGNMENT_METHODS))
        return (cs, "Preset F (Heuristic rules): Greedy vs Greedy with travel vs Most complex first vs Nearest station first. " *
                    "Model, robots, seed and movement are identical.")
    elseif key in ("g", "metaheuristics", "metaheuristic")
        cs = methods(filter(a -> a[1] in ("Greedy", "Greedy with travel") || a[5] == "Metaheuristic", ASSIGNMENT_METHODS))
        return (cs, "Preset G (Metaheuristics benchmark): Genetic algorithm vs Particle swarm vs Simulated " *
                    "annealing, with Greedy and Greedy with travel as references and Random search as the control. " *
                    "Every search gets the same budget " *
                    "($search_iterations iterations × $search_population candidates, at most $time_limit s).")
    elseif key in ("h", "all", "allalgorithms")
        return (methods(ASSIGNMENT_METHODS),
                "Preset H (All algorithms): every assignment method, MILP methods with $solver.")
    elseif key == "custom"
        isempty(algorithms) && throw(ConfigError("The \"Custom\" comparison needs a list of algorithms, e.g. " *
                                                 "ALGORITHMS_TO_COMPARE = [\"Greedy\", \"Genetic algorithm\"]."))
        rows = [_lookup(ASSIGNMENT_METHODS, a, "assignment method") for a in algorithms]
        return (methods(unique(rows)), "Custom comparison: " * join(unique(first.(rows)), " vs ") * ". " *
                    "Model, robots, seed and movement are identical.")
    elseif key in ("c", "solvercomparison", "solver")
        cs = [modify(base; assignment="MILP", solver=s[1], label="MILP + " * s[1]) for s in SOLVERS]
        return (cs, "Preset C (Solver comparison): the MILP method with each solver. Unavailable solvers " *
                    "(e.g. Gurobi without a licence) are recorded as 'skipped'. Everything else is identical.")
    elseif key in ("d", "movementablation", "movement")
        cs = [modify(base; movement=p[1], label=p[1]) for p in MOVEMENT_PROFILES]
        return (cs, "Preset D (Movement ablation): Greedy assignment, each movement profile. Only the " *
                    "RVO2 / Tangent Bug / Dispersion flags change (see the 'Flags' columns).")
    elseif key in ("e", "scaling")
        default_n = get_project_params(_lookup(MODEL_INFO, "Tractor", "model")[2])[:num_robots]
        cs = [modify(base; model="Tractor", num_robots=n, label="Tractor, $n robots") for n in (6, default_n, 14)]
        push!(cs, modify(base; model="X-Wing (mini)", num_robots=nothing, label="X-Wing (mini), default robots"))
        return (cs, "Preset E (Scaling): Tractor with 6 / $default_n / 14 robots, then the larger " *
                    "X-Wing (mini) model with its default robot count. Greedy + Recommended throughout.")
    end
    throw(ConfigError("Unknown preset \"$name\". Choose one of: \"Custom\", \"A\" (Baseline), \"B\" (Greedy vs MILP), " *
                      "\"C\" (Solver comparison), \"D\" (Movement ablation), \"E\" (Scaling), \"F\" (Heuristic rules), " *
                      "\"G\" (Metaheuristics), \"H\" (All algorithms)."))
end

"""
    run_batch(configs; name="batch", warm_up=true, verbose=true) -> Vector{Dict}

Run configurations one after another (never in parallel). Prints progress,
writes `summary.csv` into a new batch folder, and returns all records,
including failed / skipped ones.

To stop a batch between runs: create an empty file called `STOP` in the batch
folder (its path is printed at the start), or use the notebook's Interrupt
button (the run in progress is then recorded as "interrupted").

`warm_up=true` first runs each distinct type of configuration once on the
Tractor model (MILP time limit capped at 30 s), untimed and unsaved, so one-time
compilation does not inflate the computer-time measurements of the real runs.
The `includes_one_time_compilation` flag is a per-session approximation.
"""
function run_batch(configs::AbstractVector{ExperimentConfig}; name::AbstractString="batch", warm_up::Bool=true,
                   verbose::Bool=true, show_simulator_log::Bool=false)
    batch_id = string(Dates.format(now(), "yyyymmdd-HHMMSS"), "_", replace(_norm(name), r"[^a-z0-9]" => ""),
                      "_", randstring(RandomDevice(), 'a':'z', 4))
    batch_dir = joinpath(results_root(), "batches", batch_id)
    mkpath(batch_dir)
    stop_file = joinpath(batch_dir, "STOP")
    n = length(configs)
    println("Batch $batch_id: $n run(s). Results folder:\n  $batch_dir")
    println("To stop after the current run, create an empty file named STOP in that folder.\n")

    records = Dict{Symbol,Any}[]
    if warm_up
        _warm_up(configs, verbose)
    end
    t_batch = time()
    for (i, cfg) in enumerate(configs)
        if isfile(stop_file)
            for c in configs[i:end]
                r = _empty_record(c)
                r[:run_id] = "not-run-$(i)"; r[:batch_id] = batch_id
                r[:status] = "skipped"; r[:status_detail] = "batch stopped by the user (STOP file) before this run"
                push!(records, r)
            end
            println("STOP file found: remaining $(n - i + 1) run(s) were not started.")
            break
        end
        println("─"^78)
        println("Run $i of $n: ", isempty(cfg.label) ? "" : "[$(cfg.label)] ",
                "$(cfg.model) | $(cfg.assignment)",
                _uses_solver(cfg) ? " + $(cfg.solver)" : "", " | $(cfg.movement) | seed $(cfg.seed)")
        # Optional solvers that are unavailable are skipped, not failed.
        if _uses_solver(cfg) && _norm(cfg.solver) == "gurobi" && !solver_status(:gurobi)[1]
            r = _empty_record(cfg)
            r[:run_id] = "skipped-" * Dates.format(now(), "yyyymmdd-HHMMSS-sss"); r[:batch_id] = batch_id
            r[:status] = "skipped"; r[:status_detail] = "Gurobi has no valid licence on this computer"
            r[:error_message] = solver_status(:gurobi)[2]
            push!(records, r)
            println("  SKIPPED: Gurobi has no valid licence on this computer.")
            continue
        end
        rec = try
            run_experiment(cfg; batch_id=batch_id, verbose=verbose, show_simulator_log=show_simulator_log)
        catch e
            e isa InterruptException || rethrow()
            r = _empty_record(cfg); r[:batch_id] = batch_id
            r[:run_id] = "interrupted-$(i)"; r[:status] = "interrupted"
            r[:status_detail] = "stopped by the user during the run"
            push!(records, r)
            println("\nInterrupted. Runs completed before the interruption are kept.")
            break
        end
        push!(records, rec)
        @printf("  Elapsed batch time: %.1f s\n", time() - t_batch)
    end
    println("─"^78)
    summary_path = joinpath(batch_dir, "summary.csv")
    export_csv(records, summary_path)
    _write_toml(joinpath(batch_dir, "batch_info.toml"), Dict(
        "batch_id" => batch_id, "name" => name, "runs" => length(records), "warm_up" => warm_up,
        "software" => software_versions()))
    counts = Dict{String,Int}()
    for r in records
        counts[r[:status]] = get(counts, r[:status], 0) + 1
    end
    println("Batch finished. ", join(["$v $k" for (k, v) in sort(collect(counts))], ", "), ".")
    println("Summary table: $summary_path")
    LAB_STATE[:last_batch_dir] = batch_dir
    return records
end

_uses_solver(cfg) = try
    _lookup(ASSIGNMENT_METHODS, cfg.assignment, "assignment method")[3]
catch
    false
end

function _warm_up(configs, verbose)
    seen = Set{Any}()
    todo = ExperimentConfig[]
    for c in configs
        v = try
            validate_config(c)
        catch
            continue
        end
        key = _path_key(v)
        (key in _COMPILED_PATHS || key in seen) && continue
        v.uses_solver && v.milp_optimizer == :gurobi && !solver_status(:gurobi)[1] && continue
        push!(seen, key)
        push!(todo, modify(c; model="Tractor", num_robots=nothing, save_results=false, reuse_results=false,
                           label="warm-up", optimizer_time_limit_s=min(c.optimizer_time_limit_s, 30),
                           search_iterations=2, search_population=4, allow_large_models=false))
    end
    isempty(todo) && return
    println("Warm-up: $(length(todo)) untimed, unsaved Tractor run(s) to compile the code first. ",
            "These are not part of the results.")
    for (i, c) in enumerate(todo)
        t = time()
        r = redirect_stdout(devnull) do
            run_experiment(c; verbose=false)
        end
        @printf("  warm-up %d/%d (%s, %s, %s): %s, %.0f s\n", i, length(todo), c.assignment,
                _uses_solver(c) ? c.solver : "no solver", c.movement, r[:status], time() - t)
    end
    println()
end

# -----------------------------------------------------------------------------
# Display: tables, summaries, charts
# -----------------------------------------------------------------------------

# True wherever cell output can show HTML: Jupyter / JupyterLab / VS Code with the IJulia kernel, and VS Code's
# own Julia notebooks (which do not load IJulia). A plain terminal only has TextDisplay / REPLDisplay.
_in_notebook() = any(d -> !(d isa TextDisplay) && displayable(d, MIME("text/html")), Base.Multimedia.displays)

_esc(s) = replace(string(s), "&" => "&amp;", "<" => "&lt;", ">" => "&gt;")

_fmt(x::Missing) = "—"
_fmt(x::Bool) = x ? "on" : "off"
_fmt(x::AbstractFloat) = isfinite(x) ? (abs(x) >= 100 ? @sprintf("%.1f", x) : @sprintf("%.2f", x)) : "—"
_fmt(x) = string(x)
_unit(x, u) = x === missing ? "—" : string(_fmt(x), " ", u)
_gap(x) = x === missing ? "—" : @sprintf("%.3f m", x)   # a gap of -0.004 m is an overlap: two decimals would hide it

function _display_table(header, rows; title=nothing, note=nothing)
    if _in_notebook()
        io = IOBuffer()
        title === nothing || print(io, "<h4 style='margin-bottom:4px'>", _esc(title), "</h4>")
        print(io, "<table style='border-collapse:collapse;font-size:13px'><thead><tr>")
        for h in header
            print(io, "<th style='text-align:left;border-bottom:2px solid #888;padding:3px 8px'>", _esc(h), "</th>")
        end
        print(io, "</tr></thead><tbody>")
        for r in rows
            print(io, "<tr>")
            for c in r
                s = _esc(_fmt(c))
                style = s in ("OK", "SUCCESS") ? "color:#1a7f37;font-weight:bold" :
                        s in ("PROBLEM", "FAILED", "REJECTED", "INCOMPLETE", "INTERRUPTED") ? "color:#cf222e;font-weight:bold" :
                        s in ("WARNING", "SKIPPED") ? "color:#9a6700;font-weight:bold" : ""
                print(io, "<td style='text-align:left;border-bottom:1px solid #ddd;padding:3px 8px;$style'>", s, "</td>")
            end
            print(io, "</tr>")
        end
        print(io, "</tbody></table>")
        note === nothing || print(io, "<p style='font-size:12px;color:#555'>", _esc(note), "</p>")
        display(HTML(String(take!(io))))
    else
        title === nothing || println("\n== ", title, " ==")
        widths = [maximum(length(_fmt(x)) for x in vcat([header[j]], [r[j] for r in rows])) for j in eachindex(header)]
        widths = min.(widths, 70)
        line(cells) = println(join([rpad(first(_fmt(c), 70), widths[j]) for (j, c) in enumerate(cells)], " | "))
        line(header)
        println(join(["-"^w for w in widths], "-+-"))
        foreach(line, rows)
        note === nothing || println(note)
    end
    return nothing
end

"""List the available models with their size and default robot count."""
function show_models()
    rows = [[name, SIZE_TEXT[sz], parts, asm, get_project_params(sym)[:num_robots], t,
             sz in (:large, :very_large) ? "needs ALLOW_LARGE_MODELS" : ""]
            for (name, sym, parts, asm, t, sz) in MODEL_INFO]
    _display_table(["MODEL", "Size", "Parts", "Assemblies", "Default robots", "Reference time*", ""], rows;
        title="Available models",
        note="*Run times noted in the source code comments (authors' hardware, Greedy-style runs). " *
             "MILP methods and smooth animations take longer.")
end

"""List assignment methods, solvers and movement profiles."""
function show_options()
    _display_table(["ASSIGNMENT_METHOD", "Family", "Uses a solver?", "What it does"],
        [[a[1], a[5], a[3] ? "yes" : "no", a[4]] for a in ASSIGNMENT_METHODS]; title="Assignment methods (who does which task)",
        note="Short names also work: \"GA\", \"PSO\", \"SA\", \"MCF\", \"NSF\". Metaheuristics use SEARCH_ITERATIONS, " *
             "SEARCH_POPULATION and the time limit; MILP methods use SOLVER and the time limit.")
    _display_table(["SOLVER", "Cost", "Notes"],
        [[s[1], s[3] ? "free" : "licence required", s[4]] for s in SOLVERS]; title="Solvers (only used by MILP methods)")
    _display_table(["MOVEMENT_PROFILE", "RVO2", "Tangent Bug", "Dispersion", "Notes"],
        [[p[1], p[2], p[3], p[4], p[5]] for p in MOVEMENT_PROFILES]; title="Movement profiles (how robots move)")
end

"""Show one run's result as a readable table with units."""
function show_run(rec)
    status = uppercase(string(rec[:status]))
    rows = Any[
        ["Status", status, rec[:status_detail]],
        ["Run ID", rec[:run_id], ""],
        ["Model", rec[:model], "$(_fmt(rec[:num_robots])) robots ($(_fmt(rec[:robots_source])))"],
        ["Assignment method", rec[:assignment_method], "$(_fmt(rec[:assignment_family])); solver: $(_fmt(rec[:solver]))"],
        ["Movement profile", rec[:movement_profile],
         "RVO2 $(_fmt(rec[:rvo_flag])), Tangent Bug $(_fmt(rec[:tangent_bug_flag])), Dispersion $(_fmt(rec[:dispersion_flag]))"],
        ["Random seed", rec[:random_seed], ""],
        ["Completion time (makespan)", _unit(rec[:makespan_s], "s"), "SIMULATED time until the model was fully built"],
        ["Planned completion time", _unit(rec[:optimistic_makespan_s], "s"),
         "SIMULATED; the schedule's estimate after assignment, ignoring traffic (\"OptimisticMakespan\")"],
        ["Smallest gap between robots", _gap(rec[:robot_min_gap_m]),
         "SAFETY; the closest two free robots came, surface to surface. Negative means they overlapped"],
        ["Steps with overlapping robots", _fmt(rec[:robot_overlap_steps]),
         "SAFETY; $(_fmt(rec[:overlap_steps])) when transport teams count too (as bounding circles, so conservative)"],
        ["Position swaps", _fmt(rec[:position_swaps]), "SAFETY; times two robots instantly exchanged positions (a teleport)"],
        ["Top speed", _unit(rec[:max_speed_mps], "m/s"), "fastest agent, leaving out position swaps; the limit is 4 m/s"],
        ["Assignment time", _unit(rec[:assignment_time_s], "s"), "COMPUTER time spent assigning tasks"],
        ["Preparation time", _unit(rec[:pre_execution_runtime_s], "s"),
         "COMPUTER time from loading the model to finishing assignment (\"PreExecutionRuntime\")"],
        ["Execution time", _unit(rec[:execution_runtime_s], "s"),
         "COMPUTER time spent simulating the robots (\"ExecutionRuntime\")"],
        ["Total computer time", _unit(rec[:total_wall_time_s], "s"),
         rec[:includes_one_time_compilation] === true ? "includes one-time compilation (first run of this kind)" : ""],
        ["Valid MILP solution", _fmt(rec[:valid_milp_solution]), "only for MILP methods"],
        ["Solver outcome", _fmt(rec[:solver_status]), rec[:solver_status] === missing ? "only for MILP methods" :
         "gap $(rec[:solver_gap] === missing ? "—" : @sprintf("%.1f %%", 100 * rec[:solver_gap])), lower bound " *
         "$(_fmt(rec[:solver_bound])). This is the best found in the time limit, not necessarily the optimum"],
        ["Search", rec[:search_evaluations] === missing ? "—" : "$(rec[:search_evaluations]) schedules evaluated",
         rec[:search_evaluations] === missing ? "only for metaheuristics" :
         "budget $(_fmt(rec[:search_iterations])) iterations × $(_fmt(rec[:search_population]))" *
         (rec[:search_timed_out] === true ? "; STOPPED AT THE TIME LIMIT" : "; finished within the time limit")],
        ["Plan chosen by simulation", get(rec, :selected_plan, missing) === missing ? "—" :
         (rec[:selected_plan] == 0 ? "Greedy's plan" : "search plan $(rec[:selected_plan])"),
         get(rec, :top_plan_makespans, missing) === missing ? "only with SIMULATE_TOP_PLANS above 0" :
         "simulated times, Greedy's first: " * join(_fmt.(rec[:top_plan_makespans]), ", ")],
        ["Code version", _fmt(get(rec, :source_hash, missing)), "commit $(_fmt(get(rec, :git_commit, missing)))"],
        ["Results folder", _fmt(rec[:run_folder]), ""],
        ["Animation file", _fmt(rec[:animation_file]),
         get(rec, :animation_objects, missing) === missing ? "" :
         "$(rec[:animation_objects]) moving objects, $(rec[:animation_keyframes]) keyframes; view with show_animation(...)"],
    ]
    rec[:error_message] !== missing && push!(rows, ["Error message", first(string(rec[:error_message]), 600), ""])
    _display_table(["Item", "Value", "Meaning / units"], rows; title="Result of this run")
end

const _TABLE_COLS = [
    (:label, "Label"), (:status, "Status"), (:model, "Model"), (:num_robots, "Robots"),
    (:assignment_method, "Assignment"), (:solver, "Solver"), (:movement_profile, "Movement"),
    (:random_seed, "Seed"), (:makespan_s, "Completion time [sim s]"),
    (:optimistic_makespan_s, "Planned [sim s]"), (:robot_min_gap_m, "Robot gap [m]"),
    (:robot_overlap_steps, "Overlap steps"), (:position_swaps, "Swaps"), (:assignment_time_s, "Assignment [cpu s]"),
    (:execution_runtime_s, "Execution [cpu s]"), (:total_wall_time_s, "Total [cpu s]"),
]

"""Show many runs as one table (one row per run, failures included)."""
function show_results(records; title="Results")
    _display_table([c[2] for c in _TABLE_COLS],
        [[c[1] == :status ? uppercase(string(r[c[1]])) :
          c[1] == :robot_min_gap_m && get(r, c[1], missing) !== missing ? @sprintf("%.3f", r[c[1]]) :
          get(r, c[1], missing) for c in _TABLE_COLS] for r in records];
        title=title,
        note="sim s = simulated seconds (robot time).  cpu s = real seconds of computer time.  Robot gap < 0 means " *
             "two robots overlapped; a faster time with overlaps is not a better result.  " *
             "— = not available (for example because the run failed or the method does not use a solver).")
end

function _group_label(r, by)
    parts = String[]
    for k in by
        push!(parts, string(_fmt(r[k])))
    end
    return join(parts, " | ")
end

_mean(x) = sum(x) / length(x)
_std(x) = length(x) < 2 ? missing : sqrt(sum((xi - _mean(x))^2 for xi in x) / (length(x) - 1))

"""The newest run of each label and seed: a repeat is the same experiment, not more evidence."""
function _deduplicated(records)
    newest = Dict{Any,Any}()
    for r in records
        newest[(r[:label], r[:random_seed], get(r, :source_hash, missing))] = r
    end
    return [r for r in records if any(x -> x === r, values(newest))]
end

"""
    show_summary(records; by=[:label]) -> Vector of NamedTuples

Group runs (e.g. repeated seeds) and report the success rate and, over successful runs only, the mean with its 95 %
bootstrap confidence interval, the standard deviation, min and max, and the safety record. Failures are counted,
never averaged in; repeats of the same seed count once.
"""
function show_summary(records; by=[:label], metric=:makespan_s)
    groups = Dict{String,Vector{Any}}()
    order = String[]
    for r in _deduplicated(records)
        g = _group_label(r, by)
        haskey(groups, g) || (groups[g] = Any[]; push!(order, g))
        push!(groups[g], r)
    end
    out = []
    for g in order
        rs = groups[g]
        ok = [r for r in rs if r[:status] == "success" && r[metric] !== missing]
        vals = [Float64(r[metric]) for r in ok]
        nfail = length(rs) - length(ok)
        ci = bootstrap_ci(vals)
        overlaps = [r[:robot_overlap_steps] for r in ok if get(r, :robot_overlap_steps, missing) !== missing]
        gaps = [r[:robot_min_gap_m] for r in ok if get(r, :robot_min_gap_m, missing) !== missing]
        swaps = [r[:position_swaps] for r in ok if get(r, :position_swaps, missing) !== missing]
        push!(out, (group=g, n_success=length(vals), n_not_success=nfail,
                    mean=isempty(vals) ? missing : _mean(vals), ci_low=ci[1], ci_high=ci[2],
                    std=isempty(vals) ? missing : _std(vals),
                    min=isempty(vals) ? missing : minimum(vals), max=isempty(vals) ? missing : maximum(vals),
                    runs_with_overlap=isempty(overlaps) ? missing : count(>(0), overlaps),
                    min_gap=isempty(gaps) ? missing : minimum(gaps), swaps=isempty(swaps) ? missing : sum(swaps)))
    end
    _display_table([join(string.(by), " | "), "Successful runs", "Other runs", "Mean", "95 % CI low", "95 % CI high",
                    "Std. dev.", "Min", "Max", "Runs with overlap", "Smallest robot gap [m]", "Swaps"],
        [[o.group, "$(o.n_success) of $(o.n_success + o.n_not_success)", o.n_not_success, o.mean, o.ci_low, o.ci_high,
          o.std, o.min, o.max, o.runs_with_overlap, o.min_gap, o.swaps] for o in out];
        title="Summary of $(metric) (successful runs only)",
        note="The interval is a bootstrap of the mean over seeds; it needs at least 3 successful runs. To compare " *
             "two methods, use show_paired, which compares them seed by seed.")
    return out
end

"""
    show_paired(records; baseline="Greedy", metric=:makespan_s) -> Vector of pairs

Every configuration against the baseline, seed by seed, on the seeds where both succeeded: mean gain with a 95 %
bootstrap interval, effect size, wins and losses, and a sign-flip test Holm-corrected over the configurations. A
positive gain means faster than the baseline. The baseline is matched by label, or by its assignment method.
"""
function show_paired(records; baseline="Greedy", metric=:makespan_s)
    records === nothing && return println("Run the comparison first.")
    ok = [r for r in _deduplicated(records) if r[:status] == "success" && r[metric] !== missing]
    labels = unique(string.(getindex.(ok, :label)))
    base = [r for r in ok if string(r[:label]) == baseline || string(r[:assignment_method]) == baseline]
    if isempty(base)
        return println("show_paired: no successful run of \"$baseline\" among these records.")
    end
    base_label = string(base[1][:label])
    times = Dict(l => Dict(r[:random_seed] => Float64(r[metric]) for r in ok if string(r[:label]) == l) for l in labels)
    results = paired_comparison(times[base_label], [l => times[l] for l in labels if l != base_label])
    _display_table(["Configuration", "Matched seeds", "Mean gain", "95 % CI low", "95 % CI high", "Effect size dz",
                    "Wins", "Losses", "p (sign-flip)", "p (Holm)"],
        [[l, r.n, r.mean_gain, r.ci_low, r.ci_high, r.effect_size, r.wins, r.losses, _fmt_p(r.p), _fmt_p(r.p_holm)]
         for (l, r) in results];
        title="Against $base_label, seed by seed: $metric",
        note="Positive gain = faster than $base_label. Below 6 matched seeds the test cannot reach p < 0.05 at all. " *
             "Compare methods on simulated completion time together with the safety columns.")
    return results
end
_fmt_p(p) = p === missing ? missing : @sprintf("%.4f", p)

"""
    show_plan_vs_simulation(records)

How well the planned completion time predicts the simulated one (Spearman rank correlation), over all successful
runs and within each configuration. The within-configuration number is the one that says whether a search's better
plans carry over to the simulation; the overall one is often driven by the worst methods.
"""
function show_plan_vs_simulation(records)
    records === nothing && return println("Run the comparison first.")
    ok = [r for r in _deduplicated(records) if r[:status] == "success" && r[:makespan_s] !== missing && r[:optimistic_makespan_s] !== missing]
    corr(rs) = length(rs) < 3 ? missing : spearman([r[:optimistic_makespan_s] for r in rs], [r[:makespan_s] for r in rs])
    rows = Any[["All runs together", length(ok), corr(ok)]]
    for l in unique(string.(getindex.(ok, :label)))
        rs = [r for r in ok if string(r[:label]) == l]
        push!(rows, [l, length(rs), corr(rs)])
    end
    _display_table(["Runs", "n", "Spearman (planned vs simulated)"], rows; title="Does the plan predict the simulation?",
                   note="1 = better plans always simulate faster; 0 = no relation. It needs at least 3 runs.")
    return nothing
end

"""
    chart_metric(records, metric; group_by=:label, title, ylabel, save_to=nothing)

Bar chart of the mean of `metric` per group (successful runs only), with
min-max range whiskers when a group has several runs. Groups without any
successful run are drawn as an empty slot labelled with their status.
"""
function chart_metric(records, metric::Symbol; group_by=:label, title=string(metric),
                      ylabel=string(metric), save_to=nothing)
    labels = String[]
    for r in records
        g = _fmt(r[group_by])
        g in labels || push!(labels, g)
    end
    means = Union{Missing,Float64}[]; lo = Union{Missing,Float64}[]; hi = Union{Missing,Float64}[]
    notes = String[]
    colors = String[]
    for (i, g) in enumerate(labels)
        rs = [r for r in records if _fmt(r[group_by]) == g]
        push!(colors, _method_color(rs[1][:assignment_method], i))
        vals = [Float64(r[metric]) for r in rs if r[:status] == "success" && r[metric] !== missing]
        if isempty(vals)
            push!(means, missing); push!(lo, missing); push!(hi, missing)
            push!(notes, uppercase(join(unique(string.(getindex.(rs, :status))), "/")))
        else
            push!(means, _mean(vals)); push!(lo, minimum(vals)); push!(hi, maximum(vals))
            push!(notes, length(vals) > 1 ? "n=$(length(vals))" : "")
        end
    end
    svg = _bar_svg(labels, means, lo, hi, notes; title=title, ylabel=ylabel, colors=colors)
    _show_svg(svg, save_to, () -> println("[chart] ", title, ": ",
                                          join(["$l=$(_fmt(m))" for (l, m) in zip(labels, means)], ", ")))
    return nothing
end

"""Display an SVG chart (or call `text_fallback` outside a notebook) and optionally save it as a new file."""
function _show_svg(svg, save_to, text_fallback)
    if save_to !== nothing
        ispath(save_to) && error("Refusing to overwrite existing chart file $save_to")
        mkpath(dirname(abspath(save_to)))
        write(save_to, svg)
    end
    _in_notebook() ? display(HTML(svg)) : text_fallback()
end

function _bar_svg(labels, means, lo, hi, notes; title, ylabel, colors=fill("#4e79a7", length(labels)))
    n = length(labels)
    W = max(420, 110 * n + 120); H = 360
    left, right, top, bottom = 80, 20, 40, 110
    pw, ph = W - left - right, H - top - bottom
    vmax = maximum(skipmissing(vcat(means, hi)); init=0.0)
    vmax = vmax <= 0 ? 1.0 : vmax * 1.15
    step = 10.0^floor(log10(vmax / 5)); nt = vmax / step
    step *= nt > 10 ? 2 : (nt < 4 ? 0.5 : 1)
    y(v) = top + ph - ph * v / vmax
    io = IOBuffer()
    print(io, """<svg xmlns="http://www.w3.org/2000/svg" width="$W" height="$H" font-family="sans-serif" font-size="12">""")
    print(io, """<rect width="$W" height="$H" fill="white"/>""")
    print(io, """<text x="$(W/2)" y="22" text-anchor="middle" font-size="15" font-weight="bold">$(_esc(title))</text>""")
    t = 0.0
    while t <= vmax + 1e-9
        print(io, """<line x1="$left" x2="$(W-right)" y1="$(y(t))" y2="$(y(t))" stroke="#e5e5e5"/>""")
        print(io, """<text x="$(left-6)" y="$(y(t)+4)" text-anchor="end" fill="#444">$(_fmt(t))</text>""")
        t += step
    end
    print(io, """<text transform="translate(18,$(top+ph/2)) rotate(-90)" text-anchor="middle" fill="#222">$(_esc(ylabel))</text>""")
    slot = pw / max(n, 1); bw = min(70, slot * 0.6)
    for i in 1:n
        cx = left + slot * (i - 0.5)
        if means[i] === missing
            print(io, """<text x="$cx" y="$(top+ph-8)" text-anchor="middle" fill="#cf222e" font-weight="bold">$(_esc(notes[i]))</text>""")
        else
            print(io, """<rect x="$(cx-bw/2)" y="$(y(means[i]))" width="$bw" height="$(top+ph-y(means[i]))" fill="$(colors[i])"/>""")
            if hi[i] > lo[i]
                print(io, """<line x1="$cx" x2="$cx" y1="$(y(lo[i]))" y2="$(y(hi[i]))" stroke="#222" stroke-width="1.5"/>""")
                for v in (lo[i], hi[i])
                    print(io, """<line x1="$(cx-6)" x2="$(cx+6)" y1="$(y(v))" y2="$(y(v))" stroke="#222" stroke-width="1.5"/>""")
                end
            end
            print(io, """<text x="$cx" y="$(y(hi[i])-6)" text-anchor="middle" fill="#222">$(_fmt(means[i])) $(_esc(notes[i]))</text>""")
        end
        # wrap long labels onto up to three lines
        words = split(labels[i]); lines = String[""]
        for w in words
            if length(lines[end]) + length(w) + 1 > 16 && !isempty(lines[end])
                push!(lines, String(w))
            else
                lines[end] = isempty(lines[end]) ? String(w) : lines[end] * " " * w
            end
        end
        for (k, l) in enumerate(lines[1:min(end, 4)])
            print(io, """<text x="$cx" y="$(top+ph+16+14*(k-1))" text-anchor="middle" fill="#222">$(_esc(l))</text>""")
        end
    end
    print(io, """<line x1="$left" x2="$(W-right)" y1="$(top+ph)" y2="$(top+ph)" stroke="#222"/>""")
    print(io, "</svg>")
    return String(take!(io))
end

"""A tick step of 1, 2 or 5 × 10^k giving about `n` ticks between lo and hi."""
function _tick_step(lo, hi, n=6)
    span = hi > lo ? hi - lo : 1.0
    step = 10.0^floor(log10(span / n))
    return step * (span / step > 5n ? 5 : span / step > 2n ? 2 : 1)
end

_records(r) = r isa AbstractDict ? [r] : collect(r)
_has_history(r) = get(r, :search_history, missing) isa AbstractVector && !isempty(r[:search_history])
_has_plan(r) = get(r, :assignment_plan, missing) isa AbstractVector && !isempty(r[:assignment_plan])

"""Label of each record, with the seed added where several records share a label."""
function _labels_with_seed(recs)
    ls = [string(r[:label]) for r in recs]
    return [count(==(l), ls) > 1 ? "$l (seed $(_fmt(r[:random_seed])))" : l for (l, r) in zip(ls, recs)]
end

"""
    chart_convergence(records; title, save_to=nothing)

Line chart of how each metaheuristic run improved its planned completion time, iteration by
iteration (iteration 0 is the starting point: Greedy's task order). Other runs in `records`
with a planned completion time are drawn as dashed reference lines.
"""
function chart_convergence(records; title="Search progress: best planned completion time per iteration",
                           save_to=nothing)
    recs = _records(records)
    labels = _labels_with_seed(recs)
    series = [(l, Float64.(r[:search_history]), _method_color(r[:assignment_method], i))
              for (i, (l, r)) in enumerate(zip(labels, recs)) if _has_history(r)]
    refs = [(l, Float64(r[:optimistic_makespan_s]), _method_color(r[:assignment_method], i))
            for (i, (l, r)) in enumerate(zip(labels, recs))
            if !_has_history(r) && r[:optimistic_makespan_s] isa Real && isfinite(r[:optimistic_makespan_s])]
    if isempty(series)
        println("No search progress to draw: only the metaheuristics (Genetic algorithm, Particle swarm, ",
                "Simulated annealing) record it.")
        return nothing
    end
    vals = filter(isfinite, vcat([s[2] for s in series]..., [r[2] for r in refs]))
    lo, hi = minimum(vals), maximum(vals)
    pad = max((hi - lo) * 0.12, 0.05 * hi, 1e-6)
    lo, hi = max(0.0, lo - pad), hi + pad
    nx = maximum(length(s[2]) for s in series) - 1
    W, H, left, right, top, bottom = 780, 380, 70, 230, 42, 52
    pw, ph = W - left - right, H - top - bottom
    x(i) = left + pw * (nx == 0 ? 0.5 : i / nx)
    y(v) = top + ph - ph * (v - lo) / (hi - lo)
    io = IOBuffer()
    print(io, """<svg xmlns="http://www.w3.org/2000/svg" width="$W" height="$H" font-family="sans-serif" font-size="12">""",
          """<rect width="$W" height="$H" fill="white"/>""",
          """<text x="$left" y="22" font-size="15" font-weight="bold" fill="#222">$(_esc(title))</text>""")
    ys = _tick_step(lo, hi)
    t = ceil(lo / ys) * ys
    while t <= hi + 1e-9
        print(io, """<line x1="$left" x2="$(left+pw)" y1="$(y(t))" y2="$(y(t))" stroke="#e5e5e5"/>""",
              """<text x="$(left-6)" y="$(y(t)+4)" text-anchor="end" fill="#444">$(_fmt(t))</text>""")
        t += ys
    end
    xs = max(1, round(Int, _tick_step(0, max(nx, 1), 8)))
    for i in 0:xs:nx
        print(io, """<text x="$(x(i))" y="$(top+ph+16)" text-anchor="middle" fill="#444">$i</text>""")
    end
    print(io, """<line x1="$left" x2="$(left+pw)" y1="$(top+ph)" y2="$(top+ph)" stroke="#222"/>""",
          """<text x="$(left+pw/2)" y="$(H-12)" text-anchor="middle" fill="#222">iteration (0 = start: Greedy and its task order)</text>""",
          """<text transform="translate(18,$(top+ph/2)) rotate(-90)" text-anchor="middle" fill="#222">planned completion [simulated s]</text>""")
    legend = Tuple{String,String,String}[]
    for (l, v, c) in refs
        print(io, """<line x1="$left" x2="$(left+pw)" y1="$(y(v))" y2="$(y(v))" stroke="$c" stroke-width="1.5" stroke-dasharray="6 4"><title>$(_esc(l)): $(_fmt(v)) s</title></line>""")
        push!(legend, ("dash", c, "$l: $(_fmt(v)) s"))
    end
    for (l, h, c) in series
        pts = join(["$(x(i-1)),$(y(v))" for (i, v) in enumerate(h) if isfinite(v)], " ")
        print(io, """<polyline points="$pts" fill="none" stroke="$c" stroke-width="2.5"><title>$(_esc(l))</title></polyline>""")
        for (i, v) in enumerate(h)
            isfinite(v) && print(io, """<circle cx="$(x(i-1))" cy="$(y(v))" r="2.6" fill="$c"><title>$(_esc(l)), iteration $(i-1): $(_fmt(v)) s</title></circle>""")
        end
        push!(legend, ("line", c, "$l: $(_fmt(h[1])) → $(_fmt(h[end])) s"))
    end
    for (k, (kind, c, text)) in enumerate(legend)
        ly = top + 8 + 34 * (k - 1)
        lx = left + pw + 16
        print(io, """<line x1="$lx" x2="$(lx+22)" y1="$ly" y2="$ly" stroke="$c" stroke-width="$(kind == "line" ? 3 : 1.5)" $(kind == "dash" ? "stroke-dasharray=\"6 4\"" : "")/>""")
        words = split(text); lines = String[""]
        for w in words
            length(lines[end]) + length(w) + 1 > 26 && !isempty(lines[end]) ? push!(lines, String(w)) :
                (lines[end] = isempty(lines[end]) ? String(w) : lines[end] * " " * w)
        end
        for (j, s) in enumerate(lines[1:min(end, 2)])
            print(io, """<text x="$(lx+28)" y="$(ly+4+13*(j-1))" fill="#222">$(_esc(s))</text>""")
        end
    end
    print(io, """<text x="$left" y="$(top-6)" fill="#666" font-size="11">Lower is better. The vertical axis does not start at zero.</text>""", "</svg>")
    _show_svg(String(take!(io)), save_to, () -> foreach(s -> println("[search] ", s[1], ": ", join(_fmt.(s[2]), " → ")), series))
    return nothing
end

"""
    chart_schedule(records; save_to=nothing, max_robots=40)

Planned schedule (Gantt chart) of each run: one row per robot, a light bar while the robot
travels to its next task and a solid bar while its team carries the cargo (blue: a single
part, orange: a sub-assembly). Several runs share one time axis, so their schedules can be
compared directly. These are the planned times right after task assignment; the simulation
itself takes longer because of traffic.
"""
function chart_schedule(records; save_to=nothing, max_robots::Integer=40)
    recs = filter(_has_plan, _records(records))
    if isempty(recs)
        println("No planned schedule to draw (the run stopped before task assignment finished, or was saved by ",
                "an older version of this notebook).")
        return nothing
    end
    labels = _labels_with_seed(recs)
    tmax = maximum(Float64(p["finish"]) for r in recs for p in r[:assignment_plan])
    tmax = tmax > 0 ? tmax : 1.0
    W, left, right, top, rowh = 900, 92, 20, 50, 15
    pw = W - left - right
    x(t) = left + pw * t / tmax
    body = IOBuffer(); y0 = 0
    for (r, label) in zip(recs, labels)
        plan = r[:assignment_plan]
        robots = sort(unique(Int(id) for p in plan for id in p["robots"]))
        shown = robots[1:min(end, max_robots)]
        row = Dict(id => k for (k, id) in enumerate(shown))
        ph = rowh * length(shown)
        planned = r[:optimistic_makespan_s] isa Real ? " · planned completion $(_fmt(r[:optimistic_makespan_s])) s" : ""
        print(body, """<text x="12" y="$(y0+20)" font-size="14" font-weight="bold" fill="#222">Planned schedule: $(_esc(label))</text>""",
              """<text x="12" y="$(y0+37)" fill="#555">$(length(plan)) transport tasks · $(length(robots)) robots$planned$(length(shown) < length(robots) ? " · first $(length(shown)) robots shown" : "")</text>""")
        for (k, id) in enumerate(shown)
            yy = y0 + top + rowh * (k - 1)
            isodd(k) && print(body, """<rect x="$left" y="$yy" width="$pw" height="$rowh" fill="#f6f7f8"/>""")
            print(body, """<text x="$(left-6)" y="$(yy+rowh-4)" text-anchor="end" fill="#444" font-size="11">robot $id</text>""")
        end
        for p in plan, (id, dep) in zip(p["robots"], p["departures"])
            k = get(row, Int(id), 0); k == 0 && continue
            yy = y0 + top + rowh * (k - 1) + 2
            s, f = Float64(p["start"]), Float64(p["finish"])
            tip = _esc("robot $id → $(p["cargo"]): sets off $(_fmt(Float64(dep))) s, team forms $(_fmt(s)) s, delivered $(_fmt(f)) s")
            dep < s && print(body, """<rect x="$(x(dep))" y="$yy" width="$(x(s)-x(dep))" height="$(rowh-4)" fill="#c9d1d4"><title>$tip</title></rect>""")
            print(body, """<rect x="$(x(s))" y="$yy" width="$(max(x(f)-x(s), 1.0))" height="$(rowh-4)" fill="$(p["is_assembly"] === true ? "#f28e2b" : "#4e79a7")"><title>$tip</title></rect>""")
        end
        axis_y = y0 + top + ph
        ts = _tick_step(0, tmax, 10); t = 0.0
        while t <= tmax + 1e-9
            print(body, """<line x1="$(x(t))" x2="$(x(t))" y1="$(y0+top)" y2="$axis_y" stroke="#000" stroke-opacity="0.08"/>""",
                  """<text x="$(x(t))" y="$(axis_y+14)" text-anchor="middle" fill="#444" font-size="11">$(_fmt(t))</text>""")
            t += ts
        end
        print(body, """<line x1="$left" x2="$(left+pw)" y1="$axis_y" y2="$axis_y" stroke="#222"/>""")
        y0 = axis_y + 34
    end
    H = y0 + 24
    lx = W - 470
    svg = """<svg xmlns="http://www.w3.org/2000/svg" width="$W" height="$H" font-family="sans-serif" font-size="12">""" *
          """<rect width="$W" height="$H" fill="white"/>""" * String(take!(body)) *
          """<text x="$(left+pw/2)" y="$(H-26)" text-anchor="middle" fill="#222">planned time [simulated s]</text>""" *
          """<rect x="$lx" y="$(H-16)" width="14" height="10" fill="#c9d1d4"/><text x="$(lx+19)" y="$(H-7)" fill="#222">travelling to the task</text>""" *
          """<rect x="$(lx+160)" y="$(H-16)" width="14" height="10" fill="#4e79a7"/><text x="$(lx+179)" y="$(H-7)" fill="#222">carrying a part</text>""" *
          """<rect x="$(lx+290)" y="$(H-16)" width="14" height="10" fill="#f28e2b"/><text x="$(lx+309)" y="$(H-7)" fill="#222">carrying an assembly</text></svg>"""
    _show_svg(svg, save_to, () -> foreach(((r, l),) -> println("[schedule] ", l, ": ", length(r[:assignment_plan]),
                                                               " tasks, last delivery at ",
                                                               _fmt(maximum(Float64(p["finish"]) for p in r[:assignment_plan])), " s"),
                                          zip(recs, labels)))
    return nothing
end

"""Path that does not exist yet: `path`, or `path` with _2, _3, ... before the extension."""
function _new_file(path)
    base, ext = splitext(path)
    k = 1
    while ispath(path)
        k += 1
        path = "$(base)_$k$ext"
    end
    return path
end

"""
    show_visuals(run; animation=true)

Everything about one run: the result table, its planned schedule, the search progress
(metaheuristics only) and the 3-D animation, if one was saved.
"""
function show_visuals(rec; animation::Bool=true)
    rec === nothing && return println("Run an experiment first.")
    show_run(rec)
    chart_schedule(rec)
    _has_history(rec) && chart_convergence(rec)
    animation && show_animation(rec)
    return nothing
end

"""
    show_comparison(records; folder=batch_folder(records))

Results table; bar charts of completion time, planned completion time and assignment
computer time; the metaheuristics' search progress; and every run's planned schedule on one
time axis. The charts are also saved as .svg files in `folder` (the batch folder).
"""
function show_comparison(records; folder=batch_folder(records))
    records === nothing && return println("Run the comparison first.")
    show_results(records; title="Comparison results")
    length(unique(r[:random_seed] for r in records)) > 1 && show_paired(records)
    file(name) = folder === nothing ? nothing : _new_file(joinpath(folder, name))
    chart_metric(records, :makespan_s; title="Completion time in the simulation (lower is better)",
                 ylabel="Completion time [simulated s]", save_to=file("chart_completion_time.svg"))
    chart_metric(records, :optimistic_makespan_s; title="Planned completion time right after assignment (lower is better)",
                 ylabel="Planned completion [simulated s]", save_to=file("chart_planned_completion.svg"))
    chart_metric(records, :assignment_time_s; title="Computer time spent on task assignment",
                 ylabel="Assignment time [computer s]", save_to=file("chart_assignment_time.svg"))
    any(_has_history, records) && chart_convergence(records; save_to=file("chart_search_progress.svg"))
    chart_schedule(records; save_to=file("chart_schedules.svg"))
    folder === nothing || println("Charts saved in ", folder)
    return nothing
end

# -----------------------------------------------------------------------------
# CSV export / import (no extra packages needed)
# -----------------------------------------------------------------------------

_csv_cell(x::Missing) = ""
_csv_cell(x::Bool) = x ? "true" : "false"
_csv_cell(x::AbstractFloat) = isfinite(x) ? string(x) : ""
function _csv_cell(x)
    s = string(x)
    return any(c -> c in (',', '"', '\n', '\r'), s) ? "\"" * replace(s, "\"" => "\"\"") * "\"" : s
end

"""
    export_csv(records, path; overwrite=false)

Write records to a CSV file with the columns in `CSV_COLUMNS`. Empty cells mean
"not available". Refuses to replace an existing file unless `overwrite=true`.
"""
function export_csv(records, path::AbstractString; overwrite::Bool=false)
    if ispath(path) && !overwrite
        error("The file $path already exists. Choose a new file name, or pass overwrite=true on purpose.")
    end
    mkpath(dirname(abspath(path)))
    open(path, "w") do io
        println(io, join(string.(CSV_COLUMNS), ","))
        for r in records
            println(io, join([_csv_cell(get(r, c, missing)) for c in CSV_COLUMNS], ","))
        end
    end
    return path
end

function _append_csv(path, records)
    if isfile(path) && readline(path) != join(string.(CSV_COLUMNS), ",")
        # Written by an older notebook version with other columns: keep it under a new name.
        mv(path, replace(path, r"\.csv$" => "_before_" * Dates.format(now(), "yyyymmdd-HHMMSS") * ".csv"))
    end
    new = !isfile(path)
    mkpath(dirname(path))
    open(path, "a") do io
        new && println(io, join(string.(CSV_COLUMNS), ","))
        for r in records
            println(io, join([_csv_cell(get(r, c, missing)) for c in CSV_COLUMNS], ","))
        end
    end
end

"""
    read_csv(path) -> Vector{Dict{Symbol,Any}}

Read a CSV written by `export_csv` back into records (numbers parsed, empty
cells become `missing`).
"""
function read_csv(path::AbstractString)
    text = read(path, String)
    rows = Vector{Vector{String}}()
    row = String[]; field = IOBuffer(); inq = false; i = 1
    chars = collect(text)
    while i <= length(chars)
        c = chars[i]
        if inq
            if c == '"'
                if i < length(chars) && chars[i+1] == '"'
                    print(field, '"'); i += 1
                else
                    inq = false
                end
            else
                print(field, c)
            end
        elseif c == '"'
            inq = true
        elseif c == ','
            push!(row, String(take!(field)))
        elseif c == '\n'
            push!(row, String(take!(field))); push!(rows, row); row = String[]
        elseif c != '\r'
            print(field, c)
        end
        i += 1
    end
    (position(field) > 0 || !isempty(row)) && (push!(row, String(take!(field))); push!(rows, row))
    header = Symbol.(rows[1])
    parse_cell(s) = isempty(s) ? missing : s == "true" ? true : s == "false" ? false :
                    something(tryparse(Int, s), tryparse(Float64, s), s)
    return [Dict{Symbol,Any}(h => parse_cell(v) for (h, v) in zip(header, r)) for r in rows[2:end]]
end

# -----------------------------------------------------------------------------
# Animations: content check and viewer
# -----------------------------------------------------------------------------

_keyvalue(v) = v isa MeshCat.MsgPack.Extension ? collect(reinterpret(Float32, v.data)) : v

"""
    _animation_info(path) -> (objects, moving, keyframes, duration_s, size_mb)

Decode the `set_animation` command that MeshCat's `static_html` embeds in a
saved animation file. `moving` counts objects whose position changes over
time; a file showing only the final scene has `moving == 0`.
"""
function _animation_info(path)
    text = read(path, String)
    size_mb = round(filesize(path) / 1e6; digits=1)
    for m in Iterators.reverse(collect(eachmatch(r"base64,([A-Za-z0-9+/=]+)", text)))
        bytes = base64decode(m.captures[1])
        findfirst(b"set_animation", bytes) === nothing && continue
        cmd = MeshCat.MsgPack.unpack(bytes)
        (cmd isa AbstractDict && get(cmd, "type", "") == "set_animation") || continue
        objects = 0; moving = 0; keyframes = 0; duration = 0.0
        for entry in cmd["animations"]
            objects += 1
            clip = entry["clip"]
            fps = get(clip, "fps", 30)
            moved = false
            for tr in clip["tracks"]
                keys = tr["keys"]
                keyframes += length(keys)
                isempty(keys) || (duration = max(duration, maximum(k["time"] for k in keys) / fps))
                if tr["name"] == ".position" && length(keys) > 1
                    first_val = _keyvalue(keys[1]["value"])
                    moved |= any(k -> _keyvalue(k["value"]) != first_val, keys)
                end
            end
            moving += moved
        end
        return (objects=objects, moving=moving, keyframes=keyframes, duration_s=round(duration; digits=1), size_mb=size_mb)
    end
    return (objects=0, moving=0, keyframes=0, duration_s=0.0, size_mb=size_mb)
end

# A small read-only web server inside this Julia session shows saved animations
# in the notebook. It listens on 127.0.0.1 only, answers GET requests only, and
# serves only files registered by `show_animation` (looked up by run ID, never
# by a path taken from the request). It stops when the kernel stops.
const _VIEWER = Dict{Symbol,Any}()
const _VIEWER_FILES = Dict{String,Tuple{String,String}}()   # id => (absolute path, description)
const _VIEWER_LOCK = ReentrantLock()

_html_esc(s) = replace(string(s), "&" => "&amp;", "<" => "&lt;", ">" => "&gt;", "\"" => "&quot;", "'" => "&#39;")

function _viewer_response(status, body, ctype="text/plain; charset=utf-8")
    HTTP = MeshCat.HTTP
    return HTTP.Response(status, ["Content-Type" => ctype, "Cache-Control" => "no-store",
                                  "X-Content-Type-Options" => "nosniff"], body)
end

function _viewer_handler(req)
    req.method == "GET" || return _viewer_response(405, "GET only")
    target = String(MeshCat.HTTP.URI(req.target).path)
    m = match(r"^/(view|anim)/([A-Za-z0-9][A-Za-z0-9._-]{0,159})$", target)
    m === nothing && return _viewer_response(404, "not found")
    kind, id = m.captures
    entry = lock(() -> get(_VIEWER_FILES, id, nothing), _VIEWER_LOCK)
    entry === nothing && return _viewer_response(404, "unknown animation (run show_animation again)")
    path, desc = entry
    isfile(path) || return _viewer_response(404, "the animation file no longer exists")
    if kind == "anim"
        return _viewer_response(200, read(path), "text/html; charset=utf-8")
    end
    page = _player_page(desc, "src=\"/anim/$id\"",
                        "<a href=\"/anim/$id\" target=\"_blank\" rel=\"noopener\" style=\"font-size:12px\">raw file</a>")
    return _viewer_response(200, page, "text/html; charset=utf-8")
end

_player_page(desc, scene_attr, raw_link) = replace(read(joinpath(@__DIR__, "animation_player.html"), String),
    "__TITLE__" => _html_esc(desc), "__SCENE__" => scene_attr, "__RAW_LINK__" => raw_link)

"""Animations up to this size are embedded in the notebook output by default (see `show_animation`)."""
const INLINE_ANIMATION_MAX_MB = 30

function _viewer_port()
    srv = get(_VIEWER, :server, nothing)
    if srv !== nothing && isopen(srv)
        return _VIEWER[:port]
    end
    port = MeshCat.find_open_port(Sockets.ip"127.0.0.1", 8790, 200)
    _VIEWER[:server] = MeshCat.HTTP.serve!(_viewer_handler, Sockets.ip"127.0.0.1", port; verbose=false)
    _VIEWER[:port] = port
    return port
end

_viewer_id(s) = (id = replace(string(s), r"[^A-Za-z0-9._-]" => "-"); occursin(r"^[A-Za-z0-9]", id) ? first(id, 160) : "a" * first(id, 159))

"""
    show_animation(run; height=560, inline=automatic) -> path or URL

Show the 3-D animation of a run inside the notebook, with Play / Pause, a time
slider, speed and a camera reset. `run` is a result record (for example
`LAST_RUN`, or `COMPARISON_RESULTS[2]`) or the path of a saved
`*_visualization.html` file. The file is first checked: the table above the
viewer says how many objects move in it.

`inline=true` (the default for files up to $INLINE_ANIMATION_MAX_MB MB) copies the
animation into the cell output. It works in Jupyter, JupyterLab and VS Code,
needs no server, and keeps working after a kernel restart, but the saved
notebook grows by the file's size (clear the outputs before sharing it).
`inline=false` (the default for larger files) serves the viewer from this Julia
session at http://127.0.0.1 (this computer only) and shows a link to open it in
a browser tab; run the cell again after a kernel restart. The saved file itself
never needs a server: MeshCat writes the viewer program and all scene data into it.
"""
function show_animation(run; height::Integer=560, inline::Union{Nothing,Bool}=nothing,
                        embed::Union{Nothing,Bool}=nothing)   # `embed`: older name of `inline`
    if run isa AbstractDict
        f = get(run, :animation_file, missing)
        if f === missing
            println("No animation file for run ", get(run, :run_id, "?"), ": ",
                    get(run, :status, "") in ("success", "incomplete") ?
                    "SAVE_ANIMATION was false for it (or SAVE_RESULTS was false)." :
                    "the run did not finish (status $(uppercase(string(get(run, :status, "?")))).")
            return nothing
        end
        id = _viewer_id(get(run, :run_id, basename(f)))
        desc = string(get(run, :run_id, ""), " | ", get(run, :model, ""), ", ", _fmt(get(run, :num_robots, missing)),
                      " robots | ", get(run, :assignment_method, ""), " | ", get(run, :movement_profile, ""),
                      " | seed ", _fmt(get(run, :random_seed, missing)))
    else
        f = string(run)
        id = _viewer_id(splitext(basename(f))[1])
        desc = basename(f)
    end
    path = isabspath(f) ? f : joinpath(repo_root(), f)
    isfile(path) || error("Animation file not found: $path")
    info = _animation_info(path)
    _display_table(["Item", "Value"], Any[
            ["Run", desc], ["File", _display_path(path)], ["File size", "$(info.size_mb) MB"],
            ["Moving objects (robots, parts, transport teams)", info.moving],
            ["Animated objects / keyframes", "$(info.objects) / $(info.keyframes)"],
            ["Animation length", "$(info.duration_s) s at 30 frames per second (1 frame = 1 simulation step)"]];
        title="Animation check")
    if info.moving == 0
        println("WARNING: this file contains no recorded movement (only the final scene). Files saved before ",
                "the fix in src/ look like this; run the experiment again to get a moving animation.")
    end
    inline = something(inline, embed, info.size_mb <= INLINE_ANIMATION_MAX_MB)
    if inline && _in_notebook()
        page = _player_page(desc, "data-b64=\"" * base64encode(read(path)) * "\"", "")
        display(HTML("""<iframe srcdoc="$(_html_esc(page))" style="width:100%;height:$(height)px;border:1px solid #ccc;border-radius:6px"></iframe>
            <div style="font-size:12px;color:#555">Animation of run <code>$(_esc(id))</code>, embedded in this output
            ($(info.size_mb) MB; it needs no server and survives a kernel restart). The file is
            $(_esc(_display_path(path))); it can also be opened directly in a web browser.</div>"""))
        return path
    elseif !inline && info.size_mb > INLINE_ANIMATION_MAX_MB
        println("This animation is $(info.size_mb) MB, too large to embed in the notebook, so it is served by this ",
                "Julia session instead (or open the file directly in a browser).")
    end
    port = _viewer_port()
    lock(() -> (_VIEWER_FILES[id] = (path, desc)), _VIEWER_LOCK)
    url = "http://127.0.0.1:$port/view/$id"
    if _in_notebook()
        display(HTML("""<iframe src="$url" style="width:100%;height:$(height)px;border:1px solid #ccc;border-radius:6px"></iframe>
            <div style="font-size:12px;color:#555">Viewer for run <code>$(_esc(id))</code> ·
            <a href="$url" target="_blank" rel="noopener">open in a new browser tab</a> · served by this Julia
            session on this computer only; after a kernel restart, run this cell again.</div>"""))
    else
        println("Open the animation viewer at: ", url)
    end
    return url
end

# -----------------------------------------------------------------------------
# Misc
# -----------------------------------------------------------------------------

"""Open a saved animation (or any file) in the default web browser."""
function open_in_browser(path::AbstractString)
    p = isabspath(path) ? path : joinpath(repo_root(), path)
    isfile(p) || error("File not found: $p")
    if Sys.iswindows()
        run(`cmd /c start "" $p`)
    elseif Sys.isapple()
        run(`open $p`)
    else
        run(`xdg-open $p`)
    end
    return p
end

end # module
