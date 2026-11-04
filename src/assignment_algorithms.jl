# Task-assignment algorithms in addition to Greedy and the MILP:
#   - priority rules: Greedy with travel, most complex first, nearest station first;
#   - random-key metaheuristics: genetic algorithm, particle swarm, simulated annealing,
#     and random search (the same budget with no search operators, as a control).
# All of them build the schedule with the build-order-respecting dispatcher of
# GreedyOrderedAssignment (`assign_collaborative_tasks!`). They differ only in which open
# transport task is assigned next; robots are then matched to that task's team slots greedily.

export PriorityRuleAssignment, MetaheuristicAssignment, assignment_plan

const PRIORITY_RULE_MODES = (:greedy_with_travel, :most_complex_first, :nearest_station_first)
const METAHEURISTIC_MODES = (:genetic_algorithm, :particle_swarm, :simulated_annealing, :random_search)

team_task_ids(sched) = [node_id(n) for n in get_nodes(sched) if matches_template(FormTransportUnit, n)]

"""Number of LEGO parts in a scene-tree node (1 for a single part)."""
num_parts(scene_tree, n) = matches_template(AssemblyNode, n) ?
    sum((num_parts(scene_tree, get_node(scene_tree, id)) for id in keys(assembly_components(n))); init=0) : 1

"""
    PriorityRuleAssignment(; schedule, problem_spec, rule)

Assigns tasks with a fixed dispatching rule:
- `:greedy_with_travel`: Greedy, except that each robot's finish time includes its earlier travel.
  This is the decoder the metaheuristics use, so it shows how much of their gain comes from the
  decoder rather than from the search.
- `:most_complex_first`: the open task with the largest transport team (then the most LEGO
  parts in its cargo) goes first; ties go to the team that can finish earliest.
- `:nearest_station_first`: the open task whose pick-up station the free robots can reach
  soonest goes first, judged by travel time only (not by when the robots become free).
"""
@with_kw struct PriorityRuleAssignment{P} <: AbstractGreedyAssignment
    schedule::OperatingSchedule = OperatingSchedule()
    problem_spec::P             = ProblemSpec()
    rule::Symbol                = :most_complex_first
end

function most_complex_first_priority(sched, scene_tree)
    rank = Dict{AbstractID,Tuple{Int,Int}}()
    for id in team_task_ids(sched)
        transport_unit = entity(get_node(sched, id))
        cargo = get_node(scene_tree, cargo_id(transport_unit))
        rank[id] = (-length(robot_team(transport_unit)), -num_parts(scene_tree, cargo))
    end
    return task -> rank[task]
end

function JuMP.optimize!(model::PriorityRuleAssignment)
    if model.rule == :greedy_with_travel
        assign_collaborative_tasks!(model; include_travel=true)
    elseif model.rule == :most_complex_first
        assign_collaborative_tasks!(model; priority=most_complex_first_priority(model.schedule, model.problem_spec))
    elseif model.rule == :nearest_station_first
        assign_collaborative_tasks!(model; use_finish_time=false)
    else
        error("Unknown priority rule: $(model.rule)")
    end
    set_leaf_vtxs!(model.schedule, ProjectComplete)
end

"""
    MetaheuristicAssignment(; schedule, problem_spec, algorithm, iterations, population, time_limit, rng)

Searches over task priorities. A candidate is a vector of random keys, one number in [0, 1]
per transport task. It is decoded by the dispatcher (among the open tasks, the one with the
largest key goes first; robots are matched greedily with travel included), and its fitness is
the planned makespan of the resulting schedule, robot travel included.

Greedy's own schedule is an extra candidate, so the planned makespan is never worse than
Greedy's; `kept_greedy` says when nothing beat it. The first search candidate is Greedy's task
order. Planned makespan ignores traffic, so a better plan does not guarantee a faster simulation:
judge the methods by the simulated `Makespan` (see `scripts/method_comparison.jl`).

- `:genetic_algorithm`: elitism, binary tournaments, biased uniform crossover, reset mutation.
- `:particle_swarm`: global-best particle swarm with Clerc-Kennedy constriction coefficients.
- `:simulated_annealing`: swap / reset moves with geometric cooling.
- `:random_search`: uniformly random keys, the control for the three search algorithms.

Each algorithm gets about `iterations × population` evaluations and stops early after
`time_limit` seconds. `history` holds the best planned makespan at the start (Greedy and its
order) and after each iteration.
"""
@with_kw mutable struct MetaheuristicAssignment{P,R} <: AbstractGreedyAssignment
    schedule::OperatingSchedule = OperatingSchedule()
    problem_spec::P             = ProblemSpec()
    algorithm::Symbol           = :genetic_algorithm
    iterations::Int             = 25
    population::Int             = 16
    time_limit::Float64         = 60.0
    rng::R                      = Random.MersenneTwister(1)
    history::Vector{Float64}    = Float64[]
    evaluations::Int            = 0
    timed_out::Bool             = false
    kept_greedy::Bool           = false
    top_k::Int                  = 0        # how many of the best distinct plans to keep in `top_plans`
    top_plans::Vector{Tuple{Float64,Vector{Float64}}} = Tuple{Float64,Vector{Float64}}[]
    fixed_keys::Union{Nothing,Vector{Float64}} = nothing # build this candidate instead of searching
end

struct SearchTimeLimit <: Exception end

# Search settings. Starting values from the literature on random-key methods (not tuned for this problem).
const GA_CROSSOVER_BIAS = 0.7  # chance that a child's key comes from the better parent
const GA_ELITE_FRACTION = 1 / 8
const PSO_INERTIA = 0.729      # Clerc-Kennedy constriction
const PSO_ACCELERATION = 1.494 # Clerc-Kennedy constriction
const PSO_MAX_VELOCITY = 0.2   # keys live in [0, 1]: at most a fifth of the range per iteration
const SA_FIRST_ACCEPTED_WORSENING = 0.02 # a 2 % worse schedule is first accepted with probability 1/e

"""
Planned makespan (robot travel included) of the schedule built with `priority`; the schedule
is restored afterwards. `Inf` if this order cannot be completed.
"""
function evaluate_priority!(model, priority, distances; order=nothing, include_travel=true, travel_at_end=false)
    sched = model.schedule
    G = get_graph(sched)
    edges0 = Set(edges(G))
    specs0 = [(get_t0(n), get_tF(n), get_min_duration(n)) for n in get_nodes(sched)]
    ms = try
        assign_collaborative_tasks!(model; priority=priority, distance_dict=distances, order=order,
                                    include_travel=include_travel, travel_at_end=travel_at_end)
        makespan(sched)
    catch e
        e isa NoAssignmentError || rethrow()
        Inf
    finally
        for ed in collect(edges(G))
            ed in edges0 || rem_edge!(G, ed)
        end
        for (n, (t0, tF, d)) in zip(get_nodes(sched), specs0)
            set_t0!(n, t0)
            set_tF!(n, tF)
            set_min_duration!(n, d)
        end
    end
    model.evaluations += 1
    return ms
end

function JuMP.optimize!(model::MetaheuristicAssignment)
    model.algorithm in METAHEURISTIC_MODES || error("Unknown metaheuristic: $(model.algorithm)")
    @assert model.iterations >= 1 && model.population >= 2 "need iterations >= 1 and population >= 2"
    tasks = sort!(team_task_ids(model.schedule); by=stable_id_key)
    index = Dict(t => i for (i, t) in enumerate(tasks))
    distances = Dict{Tuple{Int,Int},Float64}() # travel times depend only on geometry: shared by all candidates
    decode(keys) = task -> (-keys[index[task]],)

    if model.fixed_keys !== nothing
        assign_collaborative_tasks!(model; priority=decode(model.fixed_keys), distance_dict=distances, include_travel=true)
        set_leaf_vtxs!(model.schedule, ProjectComplete)
        return model
    end

    greedy_order = AbstractID[]
    greedy_ms = evaluate_priority!(model, task -> (), distances; order=greedy_order, include_travel=false,
                                   travel_at_end=true) # exactly as Greedy
    seed = zeros(length(tasks))
    for (k, t) in enumerate(greedy_order)
        seed[index[t]] = 1 - (k - 1) / length(tasks)
    end

    deadline = time() + model.time_limit
    best_keys, best_ms = nothing, greedy_ms
    plans = Dict{Vector{AbstractID},Tuple{Float64,Vector{Float64}}}() # keyed by task order: distinct plans only
    fitness = keys -> begin
        time() > deadline && throw(SearchTimeLimit())
        order = model.top_k > 0 ? AbstractID[] : nothing
        ms = evaluate_priority!(model, decode(keys), distances; order=order)
        if ms < best_ms
            best_keys, best_ms = copy(keys), ms
        end
        if model.top_k > 0 && isfinite(ms) && !haskey(plans, order)
            plans[order] = (ms, copy(keys))
        end
        ms
    end
    record() = push!(model.history, best_ms)
    empty!(model.history)
    try
        f0 = fitness(seed)
        record()
        if length(tasks) >= 2
            search! = Dict(:genetic_algorithm => genetic_algorithm!, :particle_swarm => particle_swarm!,
                           :simulated_annealing => simulated_annealing!, :random_search => random_search!)[model.algorithm]
            search!(model, fitness, seed, f0, record)
        end
    catch e
        e isa SearchTimeLimit || rethrow()
        model.timed_out = true
    end
    isempty(model.history) && record()
    model.top_plans = first(sort!(collect(values(plans)); by=first), model.top_k)
    model.kept_greedy = best_keys === nothing
    if model.kept_greedy
        assign_collaborative_tasks!(model; distance_dict=distances)
    else
        assign_collaborative_tasks!(model; priority=decode(best_keys), distance_dict=distances, include_travel=true)
    end
    set_leaf_vtxs!(model.schedule, ProjectComplete)
    model
end

function genetic_algorithm!(model, fitness, seed, f0, record)
    rng, P, T = model.rng, model.population, length(seed)
    pop = vcat([seed], [rand(rng, T) for _ in 2:P])
    fit = [f0; [fitness(x) for x in pop[2:end]]]
    record()
    n_elite = max(1, floor(Int, P * GA_ELITE_FRACTION))
    tournament() = (i = rand(rng, 1:P); j = rand(rng, 1:P); fit[i] <= fit[j] ? i : j)
    for _ in 2:model.iterations
        ranked = sortperm(fit)
        new_pop, new_fit = pop[ranked[1:n_elite]], fit[ranked[1:n_elite]]
        while length(new_pop) < P
            a, b = tournament(), tournament()
            fit[b] < fit[a] && ((a, b) = (b, a)) # a is the better parent
            child = [rand(rng) < GA_CROSSOVER_BIAS ? pop[a][i] : pop[b][i] for i in 1:T]
            for i in 1:T
                rand(rng) < 1 / T && (child[i] = rand(rng))
            end
            push!(new_pop, child)
            push!(new_fit, fitness(child))
        end
        pop, fit = new_pop, new_fit
        record()
    end
end

function particle_swarm!(model, fitness, seed, f0, record)
    rng, P, T = model.rng, model.population, length(seed)
    w, c, vmax = PSO_INERTIA, PSO_ACCELERATION, PSO_MAX_VELOCITY
    x = vcat([seed], [rand(rng, T) for _ in 2:P])
    v = [vmax .* (2 .* rand(rng, T) .- 1) for _ in 1:P]
    pbest, pfit = deepcopy(x), [f0; [fitness(xi) for xi in x[2:end]]]
    g = argmin(pfit)
    record()
    for _ in 2:model.iterations
        for i in 1:P
            r1, r2 = rand(rng, T), rand(rng, T)
            v[i] = clamp.(w .* v[i] .+ c .* r1 .* (pbest[i] .- x[i]) .+ c .* r2 .* (pbest[g] .- x[i]), -vmax, vmax)
            x[i] = clamp.(x[i] .+ v[i], 0.0, 1.0)
            f = fitness(x[i])
            if f < pfit[i]
                pbest[i], pfit[i] = copy(x[i]), f
                f < pfit[g] && (g = i)
            end
        end
        record()
    end
end

function simulated_annealing!(model, fitness, seed, f0, record)
    rng, P, T = model.rng, model.population, length(seed)
    x, fx = copy(seed), f0
    n = model.iterations * P
    t_start = isfinite(f0) ? SA_FIRST_ACCEPTED_WORSENING * f0 : 1.0
    t_end = t_start / 1000
    for k in 1:n
        y = copy(x)
        if rand(rng) < 0.5
            i = rand(rng, 1:T)
            j = rand(rng, 1:T-1)
            j += j >= i # a different task: swapping a key with itself would waste an evaluation
            y[i], y[j] = y[j], y[i]
        else
            y[rand(rng, 1:T)] = rand(rng)
        end
        fy = fitness(y)
        temp = t_start * (t_end / t_start)^(k / n)
        if fy <= fx || rand(rng) < exp(-(fy - fx) / temp)
            x, fx = y, fy
        end
        k % P == 0 && record()
    end
end

function random_search!(model, fitness, seed, f0, record)
    rng, P, T = model.rng, model.population, length(seed)
    for _ in 1:model.iterations
        for _ in 1:P
            fitness(rand(rng, T))
        end
        record()
    end
end

"""
    assignment_plan(sched) -> Vector{Dict{String,Any}}

One entry per transport task of an assigned schedule, for schedule (Gantt) charts: the cargo,
the robots of its team, when each of them sets off towards it (`departures`), when the team
forms (`start`) and when the cargo is deposited (`finish`). Times are planned simulated seconds.
"""
function assignment_plan(sched)
    plan = Dict{String,Any}[]
    for n in get_nodes(sched)
        matches_template(FormTransportUnit, n) || continue
        transport_unit = entity(n)
        robots, departures = Int[], Float64[]
        for v in inneighbors(sched, get_vtx(sched, n))
            r = get_node(sched, v)
            matches_template(RobotGo, r) || continue
            push!(robots, get_id(node_id(entity(r))))
            push!(departures, get_t0(r))
        end
        cargo = cargo_id(transport_unit)
        push!(plan, Dict{String,Any}(
            "cargo" => (cargo isa AssemblyID ? "assembly " : "part ") * string(get_id(cargo)),
            "is_assembly" => cargo isa AssemblyID,
            "robots" => robots, "departures" => departures,
            "start" => get_t0(n), "finish" => get_tF(get_node(sched, DepositCargo(transport_unit)))))
    end
    return sort!(plan; by=p -> (p["start"], p["cargo"]))
end
