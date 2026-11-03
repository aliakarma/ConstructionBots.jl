# =============================================================================
# ConstructionLab simulation worker
#
# Julia side of the ConstructionLab dashboard. It runs inside the repository's
# own Julia project (`julia --project=<repo>`) and calls the unmodified public
# entry point `ConstructionBots.run_lego_demo`. Nothing in this file
# re-implements planning, task assignment, scheduling or motion logic.
#
# Modes (first command-line argument):
#
#   registry --repo R --out F
#       Write the model registry of src/project_params.jl to F (TOML).
#       Does not load any package, so it takes about a second.
#
#   check --repo R --out F
#       Environment diagnostics (packages, LDraw library, PyCall/rvo2,
#       solvers, viewer assets) written to F (TOML).
#
#   serve --repo R --engine-dir E --runs-dir D --parent-pid P
#       Persistent simulation engine. Loads the simulator once, then waits for
#       job files (E/inbox/*.toml) and runs them one at a time. Each run writes
#       only inside its own run folder under D. The engine exits when the
#       dashboard process P is gone.
# =============================================================================

using TOML
using Dates

const MODE = isempty(ARGS) ? "" : ARGS[1]

function parse_options(args)
    opts = Dict{String,String}()
    i = 1
    while i <= length(args)
        a = args[i]
        if startswith(a, "--") && i < length(args)
            opts[a[3:end]] = args[i+1]
            i += 2
        else
            i += 1
        end
    end
    return opts
end
const OPTS = parse_options(ARGS[2:end])

"""Absolute, normalized path without a trailing separator."""
canon(p::AbstractString) = String(rstrip(normpath(abspath(p)), ['\\', '/']))
samepath(a, b) = Sys.iswindows() ? lowercase(canon(a)) == lowercase(canon(b)) : canon(a) == canon(b)

const REPO = canon(get(OPTS, "repo", joinpath(@__DIR__, "..", "..")))

"""Write `d` as TOML to `path` atomically (temp file + rename, retried for Windows sharing locks)."""
function write_toml_atomic(path::AbstractString, d::AbstractDict)
    tmp = string(path, ".tmp", getpid())
    open(tmp, "w") do io
        TOML.print(io, d; sorted=true)
    end
    for attempt in 1:40
        try
            mv(tmp, path; force=true)
            return path
        catch
            attempt == 40 && rethrow()
            Libc.systemsleep(0.05)
        end
    end
end

now_iso() = Dates.format(Dates.now(), "yyyy-mm-ddTHH:MM:SS")

# -----------------------------------------------------------------------------
# registry mode (no package loading)
# -----------------------------------------------------------------------------

"""Model registry from src/project_params.jl, plus the part/assembly counts and
reference run times the authors wrote in that file's comments."""
function read_registry(repo)
    file = joinpath(repo, "src", "project_params.jl")
    m = Module(:ProjectParamsRegistry)
    Base.include(m, file)
    projects = getfield(m, :projects)
    params = getfield(m, :project_parameters)
    notes = Dict{String,Dict{String,Any}}()
    for line in eachline(file)
        mm = match(r"^\s*(\d+)\s*=>\s*:(\w+)\s*,?\s*#\s*(\d+)\s*x\s*(\d+)\s*,\s*(.*?)\s*$", line)
        mm === nothing && continue
        notes[mm[2]] = Dict{String,Any}("reference_parts" => parse(Int, mm[3]),
            "reference_assemblies" => parse(Int, mm[4]), "reference_time" => String(mm[5]))
    end
    models = Dict{String,Any}[]
    for idx in sort(collect(keys(projects)))
        sym = projects[idx]
        p = params[sym]
        path = joinpath(repo, "LDraw_files", p[:file_name])
        d = Dict{String,Any}(
            "index" => idx, "key" => String(sym), "project_name" => String(p[:project_name]),
            "file_name" => String(p[:file_name]), "model_scale" => Float64(p[:model_scale]),
            "default_robots" => Int(p[:num_robots]), "file_exists" => isfile(path),
            "file_size" => isfile(path) ? filesize(path) : 0)
        merge!(d, get(notes, String(sym), Dict{String,Any}()))
        push!(models, d)
    end
    return Dict{String,Any}("source" => "src/project_params.jl", "generated_at" => now_iso(), "models" => models)
end

if MODE == "registry"
    write_toml_atomic(OPTS["out"], read_registry(REPO))
    exit(0)
end

if !(MODE in ("check", "serve"))
    println(stderr, "usage: julia --project=<repo> julia_worker.jl registry|check|serve [options]")
    exit(2)
end

# -----------------------------------------------------------------------------
# Packages (check and serve modes)
# -----------------------------------------------------------------------------

using ConstructionBots
using LDrawParser
using MeshCat
using PyCall
using Random
using Logging
import HiGHS
import GLPK
import Gurobi

if haskey(ENV, "CONSTRUCTIONLAB_LDRAW_DIR") && !isempty(ENV["CONSTRUCTIONLAB_LDRAW_DIR"])
    LDrawParser.set_part_library_dir!(normpath(ENV["CONSTRUCTIONLAB_LDRAW_DIR"]))
end

pkgver(m) = string(something(pkgversion(m), "unknown"))

# Gurobi messages can embed the user name, host name and host ID: keep only the error code.
function gurobi_status()
    try
        redirect_stdout(devnull) do
            Gurobi.Env()
        end
        return (true, "A valid Gurobi licence was found.")
    catch e
        msg = sprint(showerror, e)
        code = match(r"[Ee]rror\s+(\d+)", msg)
        known = Dict("10009" => "no Gurobi licence was found", "10032" => "the Gurobi licence has expired",
                     "10024" => "the Gurobi Web License Service rejected the licence")
        if code === nothing
            return (false, "Gurobi could not start (no licence details are shown for privacy).")
        end
        return (false, "Gurobi error $(code[1]): $(get(known, code[1], "the licence could not be validated")).")
    end
end

function solver_status(name::AbstractString)
    name == "gurobi" && return gurobi_status()
    try
        if name == "highs"
            HiGHS.Optimizer()
            return (true, "HiGHS.jl $(pkgver(HiGHS)) is ready.")
        elseif name == "glpk"
            GLPK.Optimizer()
            return (true, "GLPK.jl $(pkgver(GLPK)) is ready.")
        end
    catch e
        return (false, first(split(sprint(showerror, e), '\n')))
    end
    return (false, "Unknown solver.")
end

"""The simulator imports the sisl fork of RVO2 for every run (even with RVO2 switched off)."""
function rvo2_status()
    try
        rvo2 = pyimport("rvo2")
        sim = rvo2.PyRVOSimulator(0.025, 2.0, 5, 2.0, 1.0, 0.5, 4.0, (0.0, 0.0))
        a = sim.addAgent((0.0, 0.0))
        if !pybuiltin("hasattr")(sim, "setAgentAlpha")
            return (false, "The Python module rvo2 was found but it is not the sisl fork (setAgentAlpha is missing).")
        end
        sim.setAgentAlpha(a, 0.5)
        return (true, "rvo2 (sisl fork) imports and runs: $(rvo2.__file__)")
    catch e
        return (false, "PyCall uses $(PyCall.python), which cannot import a working rvo2 module.")
    end
end

# -----------------------------------------------------------------------------
# check mode
# -----------------------------------------------------------------------------

function check_mode(out)
    checks = Dict{String,Any}[]
    add(id, label, category, status, detail, action="") = push!(checks, Dict{String,Any}(
        "id" => id, "label" => label, "category" => category, "status" => status,
        "detail" => detail, "action" => action))

    add("julia", "Julia", "required", VERSION >= v"1.10" ? "ok" : "fail", "Julia $(VERSION)",
        VERSION >= v"1.10" ? "" : "Install Julia 1.10 (the version recorded in Manifest.toml).")
    proj = Base.active_project()
    same = proj !== nothing && samepath(dirname(proj), REPO)
    add("project", "Active Julia project", "required", same ? "ok" : "fail",
        same ? "The repository's Project.toml is active." : "Active project is $(repr(proj)).",
        same ? "" : "Start Julia with --project pointing at the repository folder.")
    has_manifest = isfile(joinpath(REPO, "Manifest.toml"))
    add("manifest", "Manifest.toml", "required", has_manifest ? "ok" : "warn",
        has_manifest ? "Present (exact package versions are pinned)." : "Missing; package versions were resolved freshly.",
        has_manifest ? "" : "Run `Pkg.instantiate()` in the repository project.")
    add("constructionbots", "ConstructionBots module", "required", "ok",
        "Version $(pkgver(ConstructionBots)) loaded from the repository's src folder.")

    reg = read_registry(REPO)
    missing_models = [m["key"] for m in reg["models"] if !m["file_exists"]]
    add("registry", "Model registry", "required", isempty(reg["models"]) ? "fail" : "ok",
        "$(length(reg["models"])) models registered in src/project_params.jl.")
    add("model_files", "Model files (LDraw_files)", "required", isempty(missing_models) ? "ok" : "fail",
        isempty(missing_models) ? "All registered model files are present." : "Missing: " * join(missing_models, ", "),
        isempty(missing_models) ? "" : "Restore the LDraw_files folder of the repository.")

    lib = normpath(LDrawParser.get_part_library_dir())
    parts_dir = joinpath(lib, "parts")
    if isdir(parts_dir)
        n = count(f -> endswith(lowercase(f), ".dat"), readdir(parts_dir))
        add("ldraw", "LDraw Parts Library", "required", n > 1000 ? "ok" : "warn", "$lib ($n part files)",
            n > 1000 ? "" : "The library looks incomplete; download the complete LDraw library.")
    else
        add("ldraw", "LDraw Parts Library", "required", "fail", "Not found at $lib.",
            "Download the complete library from library.ldraw.org and unzip it to Documents/ldraw, or set " *
            "CONSTRUCTIONLAB_LDRAW_DIR before starting the dashboard.")
    end

    add("pycall", "Python used by PyCall", "required", "ok", "$(PyCall.python) (Python $(PyCall.pyversion))")
    ok, why = rvo2_status()
    add("rvo2", "RVO2 collision-avoidance module", "required", ok ? "ok" : "fail", why,
        ok ? "" : "RVO2 must be importable by the Python that PyCall uses (which may differ from the Python " *
                  "running the dashboard). Follow notebooks/SETUP.md, step 3.")

    for (name, label, category) in (("highs", "Solver: HiGHS", "required"), ("glpk", "Solver: GLPK", "optional"),
                                     ("gurobi", "Solver: Gurobi", "optional"))
        ok, why = solver_status(name)
        add("solver_" * name, label, category, ok ? "ok" : (category == "required" ? "fail" : "unavailable"), why,
            ok ? "" : (name == "gurobi" ? "Gurobi is optional. Use HiGHS, or obtain your own licence (dashboard/README.md)." :
                       "Run `Pkg.instantiate()` in the repository project."))
    end

    viewer_js = try
        joinpath(MeshCat.VIEWER_ROOT(), "main.min.js")
    catch
        ""
    end
    add("meshcat", "MeshCat 3D viewer assets", "required", isfile(viewer_js) ? "ok" : "fail",
        isfile(viewer_js) ? "MeshCat.jl $(pkgver(MeshCat)); viewer bundle present (saved animations are self-contained)." :
        "The MeshCat viewer bundle is missing.", isfile(viewer_js) ? "" : "Run `Pkg.instantiate()` in the repository project.")

    report = Dict{String,Any}(
        "generated_at" => now_iso(), "julia_version" => string(VERSION),
        "constructionbots_version" => pkgver(ConstructionBots), "checks" => checks,
        "versions" => Dict{String,Any}("HiGHS.jl" => pkgver(HiGHS), "GLPK.jl" => pkgver(GLPK),
            "Gurobi.jl" => pkgver(Gurobi), "MeshCat.jl" => pkgver(MeshCat), "LDrawParser.jl" => pkgver(LDrawParser),
            "PyCall.jl" => pkgver(PyCall), "python_for_pycall" => string(PyCall.pyversion)))
    write_toml_atomic(out, report)
end

if MODE == "check"
    check_mode(OPTS["out"])
    exit(0)
end

# -----------------------------------------------------------------------------
# serve mode: engine state, supervisor thread
# -----------------------------------------------------------------------------

const ENGINE_DIR = get(OPTS, "engine-dir", "")
const RUNS_DIR = canon(get(OPTS, "runs-dir", "."))
const PARENT_PID = parse(Int, get(OPTS, "parent-pid", "0"))
const ENGINE_STDERR = stderr
const ENGINE_STATE = Dict{String,Any}("pid" => getpid(), "started_at" => now_iso(), "julia_version" => string(VERSION),
                                      "threads" => Threads.nthreads(), "runs_completed" => 0)
const FLUSH_STREAMS = IOStream[]
const FLUSH_LOCK = Threads.SpinLock()

function set_engine_state!(; kwargs...)
    for (k, v) in kwargs
        if v === nothing
            delete!(ENGINE_STATE, string(k))
        else
            ENGINE_STATE[string(k)] = v
        end
    end
    ENGINE_STATE["updated_at"] = now_iso()
    write_toml_atomic(joinpath(ENGINE_DIR, "engine.toml"), ENGINE_STATE)
end

function pid_alive(pid::Integer)
    pid <= 0 && return true
    if Sys.iswindows()
        h = ccall((:OpenProcess, "kernel32"), stdcall, Ptr{Cvoid}, (UInt32, Int32, UInt32), 0x1000, 0, pid)
        if h == C_NULL
            return Libc.GetLastError() == 5      # access denied: the process exists
        end
        code = Ref{UInt32}(0)
        ok = ccall((:GetExitCodeProcess, "kernel32"), stdcall, Int32, (Ptr{Cvoid}, Ref{UInt32}), h, code)
        ccall((:CloseHandle, "kernel32"), stdcall, Int32, (Ptr{Cvoid},), h)
        return ok != 0 && code[] == 259          # STILL_ACTIVE
    else
        return ccall(:kill, Cint, (Cint, Cint), pid, 0) == 0 || Libc.errno() == Libc.EPERM
    end
end

function hard_exit(code)
    if Sys.iswindows()
        ccall((:ExitProcess, "kernel32"), stdcall, Cvoid, (UInt32,), code)
    else
        ccall(:_exit, Cvoid, (Cint,), code)
    end
end

"""Runs on the second thread: flushes per-run logs (so the dashboard can show
progress while the main thread computes) and exits if the dashboard is gone.
Uses Libc.systemsleep because the libuv event loop belongs to the busy main thread."""
function supervisor_loop()
    last_parent_check = 0.0
    while true
        lock(FLUSH_LOCK)
        try
            for s in FLUSH_STREAMS
                isopen(s) && try
                    flush(s)
                catch
                end
            end
        finally
            unlock(FLUSH_LOCK)
        end
        if time() - last_parent_check > 2.0
            last_parent_check = time()
            if !pid_alive(PARENT_PID)
                hard_exit(3)
            end
        end
        Libc.systemsleep(0.5)
    end
end

function register_stream!(s::IOStream)
    lock(FLUSH_LOCK)
    try
        push!(FLUSH_STREAMS, s)
    finally
        unlock(FLUSH_LOCK)
    end
end
function unregister_streams!()
    lock(FLUSH_LOCK)
    try
        empty!(FLUSH_STREAMS)
    finally
        unlock(FLUSH_LOCK)
    end
end

# -----------------------------------------------------------------------------
# serve mode: running one job
# -----------------------------------------------------------------------------

const ASSIGNMENT_MODES = Dict(string(m) => m for m in (:greedy, :greedy_with_travel, :most_complex_first, :nearest_station_first,
                              :milp, :milp_w_greedy_warm_start, :genetic_algorithm, :particle_swarm, :simulated_annealing,
                              :random_search))
uses_milp(mode) = mode in (:milp, :milp_w_greedy_warm_start)
const SOLVERS = Dict("highs" => :highs, "glpk" => :glpk, "gurobi" => :gurobi)
const COMPILED_PATHS = Set{Any}()

struct RejectedJob <: Exception
    msg::String
end

function get_int(req, key, lo, hi)
    v = get(req, key, nothing)
    (v isa Integer && lo <= v <= hi) || throw(RejectedJob("Setting `$key` must be a whole number between $lo and $hi."))
    return Int(v)
end
function get_bool(req, key)
    v = get(req, key, nothing)
    v isa Bool || throw(RejectedJob("Setting `$key` must be true or false."))
    return v
end

"""Translate a job request into keyword arguments of `run_lego_demo`, re-validating
every value against whitelists (the request file is never evaluated as code)."""
function demo_arguments(req, run_dir)
    key = string(get(req, "model_key", ""))
    model_sym = Symbol(key)
    haskey(ConstructionBots.project_parameters, model_sym) ||
        throw(RejectedJob("Model `$key` is not registered in src/project_params.jl."))
    p = ConstructionBots.get_project_params(model_sym)
    isfile(joinpath(REPO, "LDraw_files", p[:file_name])) ||
        throw(RejectedJob("The model file LDraw_files/$(p[:file_name]) is missing."))
    mode = get(ASSIGNMENT_MODES, string(get(req, "assignment_mode", "")), nothing)
    mode === nothing && throw(RejectedJob("Unknown assignment mode."))
    solver = get(SOLVERS, string(get(req, "milp_optimizer", "")), nothing)
    solver === nothing && throw(RejectedJob("Unknown solver."))
    if mode == :milp_w_greedy_warm_start && solver == :glpk
        throw(RejectedJob("GLPK cannot be combined with the Greedy + MILP warm start (src/full_demo.jl: GLPK does " *
                          "not support warm starts through JuMP)."))
    end
    save_anim = get_bool(req, "save_animation")
    live_interval = get_int(req, "live_preview_interval", 0, 1_000_000)
    return (
        ldraw_file=String(p[:file_name]), project_name=String(p[:project_name]),
        model_scale=Float64(p[:model_scale]), num_robots=get_int(req, "num_robots", 1, 500),
        assignment_mode=mode, milp_optimizer=solver,
        optimizer_time_limit=get_int(req, "optimizer_time_limit", 1, 86_400),
        # optional: job files written before the metaheuristics existed do not have these keys
        metaheuristic_iterations=haskey(req, "metaheuristic_iterations") ? get_int(req, "metaheuristic_iterations", 1, 1000) : 25,
        metaheuristic_population=haskey(req, "metaheuristic_population") ? get_int(req, "metaheuristic_population", 2, 500) : 16,
        simulate_top_plans=haskey(req, "simulate_top_plans") ? get_int(req, "simulate_top_plans", 0, 50) : 0,
        rvo_flag=get_bool(req, "rvo_flag"), tangent_bug_flag=get_bool(req, "tangent_bug_flag"),
        dispersion_flag=get_bool(req, "dispersion_flag"),
        rng=Random.MersenneTwister(get_int(req, "seed", 0, typemax(Int32))),
        max_steps=get_int(req, "max_steps", 1, 100_000_000),
        max_num_iters_no_progress=get_int(req, "max_num_iters_no_progress", 1, 100_000_000),
        open_animation_at_end=false,
        save_animation=save_anim,
        save_animation_along_the_way=save_anim && live_interval > 0,
        save_anim_interval=live_interval > 0 ? live_interval : 500,
        process_updates_interval=get_int(req, "process_updates_interval", 1, 100_000),
        update_anim_at_every_step=save_anim && get_bool(req, "update_anim_at_every_step"),
        anim_active_agents=save_anim, anim_active_areas=save_anim, block_save_anim=false,
        base_results_path=run_dir, results_path=joinpath(run_dir, "simulator_output"),
        write_results=true, overwrite_results=false,
        look_for_previous_milp_solution=false, save_milp_solution=false,
        stop_after_task_assignment=false, log_level=Logging.Warn,
    )
end

path_key(a) = (a.assignment_mode, uses_milp(a.assignment_mode) ? a.milp_optimizer : :none, a.rvo_flag,
               a.tangent_bug_flag, a.dispersion_flag, a.save_animation, a.update_anim_at_every_step,
               a.save_animation_along_the_way)

"""Run `f` with stdout and stderr sent to two log files that the supervisor flushes."""
function with_run_logs(f, out_path, err_path)
    out = open(out_path, "w")
    err = open(err_path, "w")
    register_stream!(out)
    register_stream!(err)
    try
        return redirect_stdout(out) do
            redirect_stderr(err) do
                f()
            end
        end
    finally
        unregister_streams!()
        close(out)
        close(err)
    end
end

find_files(dir, pred) = isdir(dir) ? sort([joinpath(r, f) for (r, _, fs) in walkdir(dir) for f in fs if pred(f)]) : String[]

function software_versions()
    version = ConstructionBots.code_version()
    return Dict{String,Any}(
        "julia" => string(VERSION), "ConstructionBots" => pkgver(ConstructionBots),
        "source_hash" => version[:SourceHash], "git_commit" => version[:GitCommit], "git_dirty" => version[:GitDirty],
        "HiGHS.jl" => pkgver(HiGHS), "GLPK.jl" => pkgver(GLPK), "Gurobi.jl" => pkgver(Gurobi),
        "MeshCat.jl" => pkgver(MeshCat), "LDrawParser.jl" => pkgver(LDrawParser), "PyCall.jl" => pkgver(PyCall),
        "python_for_pycall" => string(PyCall.pyversion), "os" => string(Sys.KERNEL, " ", Sys.MACHINE))
end

finite_or_nothing(x) = (x isa Real && isfinite(x)) ? Float64(x) : nothing

"""Untimed, unsaved Tractor run on the same code path, so one-time compilation
does not inflate the computer-time measurements of the real run."""
function warm_up!(args, run_dir)
    key = path_key(args)
    key in COMPILED_PATHS && return "not needed (this code path already ran in this engine session)"
    tmp = mktempdir(; prefix="constructionlab_warmup_")
    p = ConstructionBots.get_project_params(:tractor)
    wargs = merge(args, (ldraw_file=String(p[:file_name]), project_name=String(p[:project_name]),
                         model_scale=Float64(p[:model_scale]), num_robots=Int(p[:num_robots]),
                         optimizer_time_limit=min(args.optimizer_time_limit, 10), rng=Random.MersenneTwister(1),
                         metaheuristic_iterations=2, metaheuristic_population=4,
                         base_results_path=tmp, results_path=joinpath(tmp, "out"), write_results=false))
    note = "completed"
    try
        with_run_logs(joinpath(run_dir, "warmup_stdout.log"), joinpath(run_dir, "warmup_stderr.log")) do
            ConstructionBots.run_lego_demo(; wargs...)
        end
        push!(COMPILED_PATHS, key)
    catch e
        note = "the warm-up run raised an error ($(first(sprint(showerror, e), 200))); the measured run may include compilation"
    finally
        rm(tmp; recursive=true, force=true)
    end
    return note
end

function run_job(req_path)
    req = TOML.parsefile(req_path)
    rm(req_path; force=true)
    run_id = string(get(req, "run_id", ""))
    run_dir = canon(string(get(req, "run_dir", "")))
    # The run folder must be an existing direct child of the dashboard's runs folder.
    if !(occursin(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$", run_id) && isdir(run_dir) &&
         samepath(dirname(run_dir), RUNS_DIR) && basename(run_dir) == run_id)
        println(ENGINE_STDERR, "Ignoring job with an invalid run folder: ", repr(run_dir))
        return
    end
    status_path = joinpath(run_dir, "status.toml")
    started = now_iso()
    status = Dict{String,Any}("run_id" => run_id, "state" => "running", "started_at" => started,
                              "engine_pid" => getpid(), "detail" => "running")
    write_toml_atomic(status_path, status)
    set_engine_state!(state="busy", current_run=run_id)

    result = Dict{String,Any}("run_id" => run_id, "started_at" => started, "software" => software_versions())
    stats = nothing
    env = nothing
    t0 = time()
    try
        args = demo_arguments(req, run_dir)
        if args.milp_optimizer == :gurobi && uses_milp(args.assignment_mode)
            ok, why = gurobi_status()
            ok || throw(RejectedJob("Gurobi was requested but cannot be used: $why No other solver was substituted."))
        end
        if get(req, "warm_up", false) === true
            result["warm_up"] = warm_up!(args, run_dir)
        end
        result["includes_compilation"] = !(path_key(args) in COMPILED_PATHS)
        if get(req, "seed_global_rng", true) === true
            Random.seed!(get_int(req, "seed", 0, typemax(Int32)))
        end
        t0 = time()
        env, stats = with_run_logs(joinpath(run_dir, "simulator_stdout.log"), joinpath(run_dir, "simulator_stderr.log")) do
            ConstructionBots.run_lego_demo(; args...)
        end
        push!(COMPILED_PATHS, path_key(args))
    catch e
        msg = sprint(showerror, e)
        if e isa RejectedJob
            result["state"] = "rejected"
            result["detail"] = e.msg
        else
            result["state"] = "failed"
            if e isa ConstructionBots.NoSolutionError
                result["failure_kind"] = "no_solution"
                result["detail"] = "The MILP solver found no feasible task assignment within the time limit."
            elseif e isa ConstructionBots.NoAssignmentError
                result["failure_kind"] = "too_few_robots"
                result["detail"] = "No valid task assignment exists. " * e.msg * " Try more robots."
            elseif occursin("rvo2", msg)
                result["failure_kind"] = "rvo2"
                result["detail"] = "The RVO2 Python module could not be used. See System Diagnostics."
            else
                result["failure_kind"] = "simulator_error"
                result["detail"] = "The simulator raised an error: " * first(first(split(msg, '\n')), 300)
            end
        end
        result["error_message"] = first(msg, 2000)
        open(joinpath(run_dir, "error.txt"), "w") do io
            showerror(io, e, catch_backtrace())
        end
    end
    result["total_wall_time_s"] = round(time() - t0; digits=3)

    if stats !== nothing
        metric(k) = finite_or_nothing(get(stats, k, nothing))
        for (k, name) in ((:Makespan, "makespan_s"), (:OptimisticMakespan, "optimistic_makespan_s"),
                          (:AssignmentTime, "assignment_time_s"), (:PreExecutionRuntime, "pre_execution_runtime_s"),
                          (:ExecutionRuntime, "execution_runtime_s"), (:StagingPlanTime, "staging_plan_time_s"),
                          (:ConfigTransportUnitsTime, "transport_config_time_s"),
                          (:RobotMinGap, "robot_min_gap_m"), (:MinGap, "min_gap_m"), (:MaxSpeed, "max_speed_mps"),
                          (:ObjectiveValue, "solver_objective"), (:ObjectiveBound, "solver_bound"),
                          (:RelativeGap, "solver_gap"))
            v = metric(k)
            v === nothing || (result[name] = v)
        end
        for (k, name) in ((:TerminationStatus, "solver_termination_status"), (:PrimalStatus, "solver_primal_status"))
            haskey(stats, k) && (result[name] = stats[k])
        end
        for (k, name) in ((:numobjects, "num_objects"), (:numassemblies, "num_assemblies"), (:numrobots, "num_robots_sim"),
                          (:RobotOverlapSteps, "robot_overlap_steps"), (:OverlapSteps, "overlap_steps"),
                          (:PositionSwaps, "position_swaps"))
            haskey(stats, k) && (result[name] = Int(stats[k]))
        end
        haskey(stats, :ValidMILPSolution) && (result["valid_milp_solution"] = Bool(stats[:ValidMILPSolution]))
        if haskey(stats, :SearchHistory)
            result["search_history"] = Float64[x for x in stats[:SearchHistory] if isfinite(x)]
            result["search_evaluations"] = Int(stats[:SearchEvaluations])
            result["search_timed_out"] = Bool(stats[:SearchTimedOut])
            result["search_kept_greedy"] = Bool(stats[:SearchKeptGreedy])
        end
        haskey(stats, :rng) && (result["rng"] = string(stats[:rng]))
        if env !== nothing && hasproperty(env, :dt)
            result["sim_time_step_s"] = Float64(env.dt)
        end
        if haskey(result, "makespan_s")
            result["state"] = "success"
            result["detail"] = "The project was completed in simulation."
            haskey(result, "sim_time_step_s") && (result["sim_steps"] = round(Int, result["makespan_s"] / result["sim_time_step_s"]))
        else
            result["state"] = "incomplete"
            # src/demo_utils.jl warns "No progress for N iterations" when it gives up; otherwise max_steps was reached.
            err_log = joinpath(run_dir, "simulator_stderr.log")
            no_progress = isfile(err_log) && occursin("No progress for", read(err_log, String))
            result["detail"] = no_progress ?
                "The simulation stopped before the project was finished: no construction task finished for " *
                "$(get(req, "max_num_iters_no_progress", "?")) consecutive steps." :
                "The simulation stopped before the project was finished: it reached the limit of " *
                "$(get(req, "max_steps", "?")) simulation steps."
        end
    end

    sim_out = joinpath(run_dir, "simulator_output")
    finals = find_files(sim_out, f -> endswith(f, "_visualization.html"))
    if !isempty(finals)
        result["animation_file"] = relpath(finals[end], run_dir)
        # Progress snapshots are temporary viewer files; the final animation contains all of their frames.
        snaps = find_files(sim_out, f -> occursin(r"_visualization_(\d+|preprocessing)\.html$", f))
        foreach(f -> rm(f; force=true), snaps)
        isempty(snaps) || (result["live_snapshots_removed"] = length(snaps))
    end
    stats_files = find_files(sim_out, f -> endswith(f, "stats.toml"))
    isempty(stats_files) || (result["stats_file"] = relpath(stats_files[end], run_dir))
    result["finished_at"] = now_iso()
    write_toml_atomic(joinpath(run_dir, "result.toml"), result)

    status["state"] = result["state"]
    status["detail"] = result["detail"]
    status["finished_at"] = result["finished_at"]
    write_toml_atomic(status_path, status)
    ENGINE_STATE["runs_completed"] += 1
    set_engine_state!(state="ready", current_run=nothing)
    GC.gc()
end

function serve()
    isdir(ENGINE_DIR) || error("engine directory does not exist: $ENGINE_DIR")
    isdir(RUNS_DIR) || error("runs directory does not exist: $RUNS_DIR")
    inbox = joinpath(ENGINE_DIR, "inbox")
    mkpath(inbox)
    if Threads.nthreads() >= 2
        Threads.@spawn supervisor_loop()
    else
        println(ENGINE_STDERR, "Warning: started with one thread; logs update only between runs.")
    end
    set_engine_state!(state="ready", ready_at=now_iso())
    println("Engine ready (pid $(getpid())).")
    while true
        jobs = sort(filter(f -> endswith(f, ".toml"), readdir(inbox)))
        if isempty(jobs)
            pid_alive(PARENT_PID) || exit(0)
            sleep(0.3)
            continue
        end
        try
            run_job(joinpath(inbox, jobs[1]))
        catch e
            # A failure in the bookkeeping itself: report it and keep serving.
            println(ENGINE_STDERR, "Engine error while handling ", jobs[1], ": ", sprint(showerror, e, catch_backtrace()))
            rm(joinpath(inbox, jobs[1]); force=true)
            set_engine_state!(state="ready", current_run=nothing, last_error=first(sprint(showerror, e), 500))
        end
    end
end

serve()
