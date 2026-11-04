# Paired comparison of assignment methods: the experiments behind any claim about them.
#
#   julia --project scripts/method_comparison.jl run --name NAME --models tractor,tie_fighter --seeds 1:30
#   julia --project scripts/method_comparison.jl analyze results/experiments/NAME_<hash>.csv ["baseline label"]
#
# `run` options (comma-separated lists are crossed with each other):
#   --models      keys of src/project_params.jl                  (default: tractor)
#   --methods     assignment modes; genetic_algorithm:top5 also simulates the 5 best plans
#                 and keeps the fastest in simulation            (default: all except the MILP modes)
#   --seeds       1:30 or 1,2,3                                  (default: 1:30)
#   --robots      robot counts; 0 means the model's default      (default: 0)
#   --budgets     search budgets ITERATIONSxPOPULATION           (default: 25x16)
#   --placements  seeds for shuffling the parts' locations; 0 keeps the fixed locations (default: 0)
#   --limit       search or solver time limit in seconds         (default: 120)
#   --solver      MILP solver                                    (default: highs)
#   --movement    rvo+tangent+dispersion flags such as 1,1,1     (default: 1,1,1)
#
# Every finished run is appended at once, so a crash loses nothing, and running the same command again
# resumes. The file name holds the code's hash, so runs from different code are never mixed. Seeds are the
# outer loop: a partial file still holds complete sets of matched seeds up to the last seed.
using ConstructionBots
using Printf
using Random

const COLUMNS = [:model, :method, :seed, :robots, :iterations, :population, :placement, :time_limit, :solver, :movement,
    :status, :makespan, :planned, :robot_min_gap, :robot_overlap_steps, :min_gap, :overlap_steps, :swaps, :max_speed,
    :assignment_time, :execution_time, :evaluations, :timed_out, :kept_greedy, :termination, :gap, :bound,
    :source_hash, :git_commit]
const RUN_KEY = COLUMNS[1:10]
const DEFAULT_METHODS = "greedy,greedy_with_travel,most_complex_first,nearest_station_first,genetic_algorithm,particle_swarm,simulated_annealing,random_search"

function parse_options(args)
    opts = Dict{String,String}()
    for i in 1:2:length(args)-1
        startswith(args[i], "--") || error("expected an option, got $(args[i])")
        opts[args[i][3:end]] = args[i+1]
    end
    return opts
end

"""`genetic_algorithm:top5` means the method with `simulate_top_plans=5`."""
function split_method(spec)
    parts = split(string(spec), ":top")
    return Symbol(parts[1]), length(parts) == 2 ? parse(Int, parts[2]) : 0
end

function parse_range(s)
    occursin(':', s) || return parse.(Int, split(s, ','))
    a, b = parse.(Int, split(s, ':'))
    return collect(a:b)
end

function run_one(key, method_spec, seed, robots, budget, placement, limit, solver, movement)
    method, top_plans = split_method(method_spec)
    p = get_project_params(key)
    n = robots == 0 ? p[:num_robots] : robots
    iterations, population = budget
    row = Dict{Symbol,Any}(:model => key, :method => method_spec, :seed => seed, :robots => n, :iterations => iterations,
                           :population => population, :placement => placement, :time_limit => limit, :solver => solver,
                           :movement => join(Int.(movement), "+"), :source_hash => ConstructionBots.SOURCE_HASH)
    try
        _, s = redirect_stdout(devnull) do
            run_lego_demo(; ldraw_file=p[:file_name], project_name=p[:project_name], model_scale=p[:model_scale],
                num_robots=n, assignment_mode=method, milp_optimizer=solver, optimizer_time_limit=limit,
                metaheuristic_iterations=iterations, metaheuristic_population=population,
                rng=MersenneTwister(seed), placement_rng=placement == 0 ? nothing : MersenneTwister(placement),
                rvo_flag=movement[1], tangent_bug_flag=movement[2], dispersion_flag=movement[3], write_results=false,
                simulate_top_plans=top_plans)
        end
        row[:status] = isfinite(s[:Makespan]) ? "success" : "incomplete"
        for (column, stat) in ((:makespan, :Makespan), (:planned, :OptimisticMakespan), (:robot_min_gap, :RobotMinGap),
                               (:robot_overlap_steps, :RobotOverlapSteps), (:min_gap, :MinGap), (:overlap_steps, :OverlapSteps),
                               (:swaps, :PositionSwaps), (:max_speed, :MaxSpeed), (:assignment_time, :AssignmentTime),
                               (:execution_time, :ExecutionRuntime), (:evaluations, :SearchEvaluations),
                               (:timed_out, :SearchTimedOut), (:kept_greedy, :SearchKeptGreedy),
                               (:termination, :TerminationStatus), (:gap, :RelativeGap), (:bound, :ObjectiveBound),
                               (:git_commit, :GitCommit))
            row[column] = get(s, stat, "")
        end
    catch e
        e isa InterruptException && rethrow()
        row[:status] = e isa ConstructionBots.NoAssignmentError ? "too_few_robots" :
                       e isa ConstructionBots.NoSolutionError ? "no_solution" : "error"
        @warn "Run failed" key method seed exception = (e, catch_backtrace())
    end
    return row
end

cell(x) = x isa AbstractFloat ? (isfinite(x) ? string(x) : "") : string(x)

function run_grid(opts)
    name = get(opts, "name", "comparison")
    out_dir = joinpath(dirname(pathof(ConstructionBots)), "..", "results", "experiments")
    mkpath(out_dir)
    path = joinpath(out_dir, "$(name)_$(ConstructionBots.SOURCE_HASH).csv")
    done = Set{Any}()
    if isfile(path)
        rows = read_rows(path)
        foreach(r -> push!(done, Tuple(r[c] for c in RUN_KEY)), rows)
        println("Resuming: ", length(done), " runs already in ", path)
    else
        write(path, join(COLUMNS, ",") * "\n")
    end
    models = Symbol.(split(get(opts, "models", "tractor"), ','))
    methods = String.(split(get(opts, "methods", DEFAULT_METHODS), ','))
    seeds = parse_range(get(opts, "seeds", "1:30"))
    robots = parse_range(get(opts, "robots", "0"))
    budgets = [Tuple(parse.(Int, split(b, 'x'))) for b in split(get(opts, "budgets", "25x16"), ',')]
    placements = parse_range(get(opts, "placements", "0"))
    limit = parse(Int, get(opts, "limit", "120"))
    solver = Symbol(get(opts, "solver", "highs"))
    movement = parse.(Bool, split(get(opts, "movement", "1,1,1"), ','))
    is_search(m) = split_method(m)[1] in ConstructionBots.METAHEURISTIC_MODES
    for seed in seeds, key in models, placement in placements, n in robots, method in methods
        for budget in (is_search(method) ? budgets : budgets[1:1])
            p = get_project_params(key)
            k = (string(key), string(method), string(seed), string(n == 0 ? p[:num_robots] : n), string(budget[1]),
                 string(budget[2]), string(placement), string(limit), string(solver), join(Int.(movement), "+"))
            k in done && continue
            t = time()
            row = run_one(key, method, seed, n, budget, placement, limit, solver, movement)
            open(path, "a") do io
                println(io, join((cell(get(row, c, "")) for c in COLUMNS), ","))
            end
            @printf("%-18s %-24s seed %-3d %-10s makespan %s  planned %s  (%.0f s)\n", key, method, seed, row[:status],
                    cell(get(row, :makespan, "")), cell(get(row, :planned, "")), time() - t)
            flush(stdout)
        end
    end
    println("Results: ", path)
end

function read_rows(path)
    lines = readlines(path)
    header = Symbol.(split(lines[1], ','))
    rows = [Dict(zip(header, String.(split(l, ',')))) for l in lines[2:end] if !isempty(l)]
    return filter(r -> length(r) == length(header), rows)
end

num(r, c) = (v = tryparse(Float64, r[c]); v === nothing ? missing : v)
fmt(x, d=2) = x === missing ? "—" : isnan(x) ? "—" : @sprintf("%.*f", d, x)
pfmt(x) = x === missing ? "—" : x < 0.001 ? "<0.001" : @sprintf("%.3f", x)
mean_of(xs) = isempty(xs) ? missing : sum(xs) / length(xs)

"""Markdown tables per model: outcome and safety per method, gains against Greedy, plan-to-simulation correlation."""
function analyze(path, baseline="greedy")
    rows = read_rows(path)
    is_search(r) = split_method(r[:method])[1] in ConstructionBots.METAHEURISTIC_MODES
    label(r) = is_search(r) ? "$(r[:method]) $(r[:iterations])x$(r[:population])" : r[:method]
    println("Source: ", basename(path), ", ", length(rows), " runs, code ", unique(getindex.(rows, :source_hash)), "\n")
    configs = unique([(r[:model], r[:robots], r[:placement], r[:movement]) for r in rows])
    for config in configs
        group = [r for r in rows if (r[:model], r[:robots], r[:placement], r[:movement]) == config]
        labels = unique(label.(group))
        println("### ", config[1], ", ", config[2], " robots", config[3] == "0" ? "" : ", placement $(config[3])",
                config[4] == "1+1+1" ? "" : ", movement $(config[4])", "\n")
        println("| Method | Success | Simulated [s], mean (95 % CI) | SD | Planned [s] | Runs with overlap | Smallest robot gap [m] | Swaps | Assignment [cpu s] |")
        println("|---|---|---|---|---|---|---|---|---|")
        times = Dict{String,Dict{String,Float64}}()
        for l in labels
            rs = [r for r in group if label(r) == l]
            ok = [r for r in rs if r[:status] == "success"]
            vals = [num(r, :makespan) for r in ok]
            times[l] = Dict(r[:seed] => num(r, :makespan) for r in ok)
            low, high = bootstrap_ci(vals)
            sd = length(vals) < 2 ? missing : sqrt(sum((v - mean_of(vals))^2 for v in vals) / (length(vals) - 1))
            gaps = collect(skipmissing(num(r, :robot_min_gap) for r in ok))
            println("| ", l, " | ", length(ok), "/", length(rs), " | ", fmt(mean_of(vals)), " (", fmt(low), " to ", fmt(high), ") | ",
                    fmt(sd), " | ", fmt(mean_of(collect(skipmissing(num(r, :planned) for r in ok)))), " | ",
                    count(r -> something(tryparse(Int, r[:robot_overlap_steps]), 0) > 0, ok), " | ",
                    isempty(gaps) ? "—" : fmt(minimum(gaps), 3), " | ",
                    sum((something(tryparse(Int, r[:swaps]), 0) for r in ok); init=0), " | ",
                    # with :top the simulator's figure covers only the final rerun, so it would mislead
                    occursin(":top", l) ? "—" : fmt(mean_of(collect(skipmissing(num(r, :assignment_time) for r in ok)))), " |")
        end
        if haskey(times, baseline) && length(labels) > 1
            println("\nAgainst $baseline, seed by seed (positive gain = faster than $baseline):\n")
            println("| Method | Pairs | Mean gain [s] (95 % CI) | dz | Wins / losses | p | p (Holm) |")
            println("|---|---|---|---|---|---|---|")
            for (l, r) in paired_comparison(times[baseline], [l => times[l] for l in labels if l != baseline])
                println("| ", l, " | ", r.n, " | ", fmt(r.mean_gain), " (", fmt(r.ci_low), " to ", fmt(r.ci_high), ") | ",
                        fmt(r.effect_size), " | ", r.wins, " / ", r.losses, " | ", pfmt(r.p), " | ", pfmt(r.p_holm), " |")
            end
        end
        println("\nSpearman correlation of planned and simulated completion time (does a better plan simulate faster?):\n")
        println("| Runs | n | Spearman |\n|---|---|---|")
        ok = [r for r in group if r[:status] == "success"]
        corr(rs) = length(rs) < 3 ? missing : spearman([num(r, :planned) for r in rs], [num(r, :makespan) for r in rs])
        println("| all methods | ", length(ok), " | ", fmt(corr(ok)), " |")
        search = [r for r in ok if is_search(r) && split_method(r[:method])[2] == 0]
        isempty(search) || println("| all search methods | ", length(search), " | ", fmt(corr(search)), " |")
        for l in labels
            rs = [r for r in ok if label(r) == l]
            println("| ", l, " | ", length(rs), " | ", fmt(corr(rs)), " |")
        end
        println()
    end
end

if abspath(PROGRAM_FILE) == @__FILE__
    mode = isempty(ARGS) ? "" : ARGS[1]
    if mode == "run"
        run_grid(parse_options(ARGS[2:end]))
    elseif mode == "analyze" && length(ARGS) in (2, 3)
        analyze(ARGS[2:end]...)
    else
        println("usage: julia --project scripts/method_comparison.jl run [options] | analyze <file.csv> [baseline label]")
        exit(2)
    end
end
