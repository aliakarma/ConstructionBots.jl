
"""
    run_lego_demo(; kwargs...) -> (env, stats)

Run the lego demo. Nothing outside `results_path` is written, and the caller's logger and
arguments are left as they were. Raises `NoAssignmentError` if there are too few robots, and
`NoSolutionError` if a MILP solver finds no solution.

Keyword arguments:

- `ldraw_file::String`: ldraw file
- `project_name::String`: project name (default: ldraw_file)
- `model_scale::Float64`: scale of the model (default: 0.008)
- `num_robots::Int`: number of robots to use (default: 12)
- `robot_scale::Float64`: scale of the robots (default: 0.7 * model_scale)
- `robot_height::Float64`: height of the robots (default: 10 * robot_scale)
- `robot_radius::Float64`: radius of the robots (default: 25 * robot_scale)
- `num_object_layers::Int`: number of layers to stack the legos (default: 1)
- `max_steps::Int`: maximum number of steps to run the simulation (default: 100000)
- `staging_buffer_factor::Float64`: factor to multiply the largest transport unit radius by to get the staging buffer (default: 1.2)
- `build_step_buffer_factor::Float64`: factor to multiply the robot radius by to get the build step buffer (default: 0.5)
- `base_results_path::String`: base path to save results to
- `results_path::String`: folder name to save the results to (inside base_results_path)
- `assignment_mode::Symbol`: assignment mode to use (default: :greedy). Options:
    rules :greedy, :greedy_with_travel, :most_complex_first, :nearest_station_first;
    MILP :milp, :milp_w_greedy_warm_start;
    metaheuristics :genetic_algorithm, :particle_swarm, :simulated_annealing, :random_search (see assignment_algorithms.jl)
- `open_animation_at_end::Bool`: open the animation in the browser at the end of the simulation (default: false)
- `save_animation::Bool`: save the animation at the end of the simulation (default: false)
- `save_animation_along_the_way::Bool`: save the animation at periodic intervals during the simulation (default: false)
- `anim_active_agents::Bool`: animate which agents are active (green circles) (default: false)
- `anim_active_areas::Bool`: animate which areas are active (purple circles) (default: false)
- `process_updates_interval::Int`: the interval to process animation updates (default: 50)
- `block_save_anim::Bool`: whether to save the animation in blocks instead of incrementally. false = incrementall, true = save in blocks (default: false)
- `update_anim_at_every_step::Bool`: whether to update the animation at every step (default: false)
- `save_anim_interval::Int`: the interval of number of updates to save the animation if `save_animation_along_the_way=true` (default: 500)
- `rvo_flag::Bool`: whether to use RVO (default: true)
- `tangent_bug_flag::Bool`: whether to use tangent bug (default: true)
- `dispersion_flag::Bool`: whether to use dispersion (default: true)
- `overwrite_results::Bool`: whether to overwrite the stats.toml file or create a new one with a date-time filename (default: false)
- `write_results::Bool`: whether to write the results to disk (default: true)
- `max_num_iters_no_progress::Int`: maximum number of iterations to run without progress (default: 10000)
- `sim_batch_size::Int`: number of steps to run in a simulation before clearing some memory (default: 50)
- `log_level::Logging.LogLevel`: log level to use for this run (default: Logging.Warn)
- `milp_optimizer::Symbol`: optimizer to use for the MILP (default: :highs, options: :gurobi, :glpk)
- `milp_optimizer_attribute_dict::Dict`: dictionary of attributes to set on the optimizer (default: Dict())
- `optimizer_time_limit::Int`: time limit in seconds for the MILP optimizer or the metaheuristic search (default: 600)
- `metaheuristic_iterations::Int`: iterations (generations) of a metaheuristic search (default: 25)
- `metaheuristic_population::Int`: population / swarm size of a metaheuristic search (default: 16)
- `look_for_previous_milp_solution::Bool`: whether to look for a previous MILP solution (default: false)
- `save_milp_solution::Bool`: whether to save the MILP solution (default: false)
- `previous_found_optimizer_time::Int`: time limit in seconds for the optimizer when looking for a previous solution (default: 30)
- `stop_after_task_assignment::Bool`: whether to stop after task assignment (default: false)
- `ignore_rot_matrix_warning::Bool`: whether to ignore the rotation matrix warning (default: true)
- `rng::Random.AbstractRNG`: random number generator for the robots' start positions and the search (default: MersenneTwister(1))
- `placement_rng`: if an RNG, the parts' pick-up locations are shuffled with it; `nothing` keeps the fixed order (default: nothing)
- `max_acceleration::Float64`: limit on the change of an agent's commanded velocity, in m/s^2. `Inf` means instant velocity changes, as in the published results (default: Inf)
- `simulate_top_plans::Int`: metaheuristics only. If above 0, simulates Greedy's plan and this many of the best distinct plans of the search, and keeps the one that is fastest in simulation, so the simulated result is never worse than Greedy's. Costs that many extra simulations (default: 0, the best plan is used without simulating the others). `stats` then also has `TopPlanMakespans` (Greedy's first), `TopPlanPlanned` and `SelectedPlan` (0 = Greedy)

Units and physics: distances are in meters, `model_scale` scales the model and the robots with it,
and the maximum driving speed is 4 m/s regardless of scale (`rvo_interface.jl`), while the loading
speed is `50 * robot_radius` m/s. So a small model has relatively fast robots: use `MakespanPerPart`
with care, and compare makespans only within one model.

`stats` holds the configuration, the planned (`OptimisticMakespan`) and simulated (`Makespan`)
completion times in simulated seconds, the safety record (`RobotMinGap`, `RobotOverlapSteps`, `MinGap`,
`OverlapSteps`, `PositionSwaps`, `MaxSpeed`; see `SafetyMetrics`), the MILP solver outcome
(`TerminationStatus`, `ObjectiveValue`, `ObjectiveBound`, `RelativeGap`), the code version
(`SourceHash`, `GitCommit`, `GitDirty`) and `Completed`: a stats file with `Completed = false` comes
from a run that has not finished or that crashed.
"""
function run_lego_demo(;
    log_level::Logging.LogLevel=Logging.Warn,
    save_animation::Bool=false,
    save_animation_along_the_way::Bool=false,
    open_animation_at_end::Bool=false,
    simulate_top_plans::Int=0,
    kwargs...
)
    if simulate_top_plans > 0
        return run_best_simulated_plan(simulate_top_plans; log_level, save_animation, save_animation_along_the_way,
                                       open_animation_at_end, kwargs...)
    end
    process_animation_tasks = save_animation || save_animation_along_the_way || open_animation_at_end
    visualizer = process_animation_tasks ? MeshCat.Visualizer() : nothing
    try
        return with_logger(ConsoleLogger(stderr, log_level)) do
            _run_lego_demo(visualizer;
                save_animation=save_animation || save_animation_along_the_way,
                save_animation_along_the_way=save_animation_along_the_way,
                open_animation_at_end=open_animation_at_end,
                kwargs...)
        end
    finally
        # The browser needs the server when it opens the animation; otherwise free the port.
        visualizer === nothing || open_animation_at_end || MeshCat.close_server!(visualizer.core)
    end
end

"""
Planned makespan barely predicts the simulated one, so choose by simulating: Greedy's plan and the search's best
`top_k` distinct plans, each from the same start state. The winner runs once more with the caller's output
settings, which costs little and keeps one code path for writing results.
"""
function run_best_simulated_plan(top_k; assignment_mode::Symbol=:greedy, rng=Random.MersenneTwister(1),
                                 placement_rng=nothing, stop_after_task_assignment::Bool=false, kwargs...)
    assignment_mode in METAHEURISTIC_MODES || error("simulate_top_plans needs a metaheuristic, not :$assignment_mode")
    stop_after_task_assignment && error("simulate_top_plans needs to simulate, so it cannot stop after task assignment")
    # Every call must start from the same random state
    start_state() = (rng=copy(rng), placement_rng=placement_rng === nothing ? nothing : copy(placement_rng))
    quiet = (; (k => v for (k, v) in kwargs if !(k in (:save_animation, :save_animation_along_the_way,
                                                       :open_animation_at_end, :write_results)))...)
    _, search = run_lego_demo(; quiet..., start_state()..., assignment_mode, search_top_k=top_k,
                              write_results=false, stop_after_task_assignment=true)
    plans = search[:SearchTopPlans]

    simulate(mode, keys) = run_lego_demo(; quiet..., start_state()..., assignment_mode=mode, fixed_priority_keys=keys,
                                         write_results=false)[2]
    results = [simulate(:greedy, nothing); [simulate(assignment_mode, keys) for (_, keys) in plans]]
    makespans = Float64[s[:Makespan] for s in results]
    selected = argmin(makespans) # the first of equals, so Greedy wins ties

    extra = Dict{Symbol,Any}(k => search[k] for k in (:SearchHistory, :SearchEvaluations, :SearchTimedOut,
                                                      :SearchIterations, :SearchPopulation))
    extra[:assignment_mode] = string(assignment_mode)
    extra[:SearchKeptGreedy] = selected == 1
    extra[:SelectedPlan] = selected - 1
    extra[:TopPlanMakespans] = makespans
    extra[:TopPlanPlanned] = Float64[s[:OptimisticMakespan] for s in results]
    env, stats = run_lego_demo(; kwargs..., start_state()...,
                               assignment_mode=selected == 1 ? :greedy : assignment_mode,
                               fixed_priority_keys=selected == 1 ? nothing : plans[selected-1][2], extra_stats=extra)
    return env, stats
end

const ASSIGNMENT_FILE_PREFIXES = Dict(:milp => "milp_", :greedy => "greedy_", :milp_w_greedy_warm_start => "milp-ws_",
    :greedy_with_travel => "greedy-travel_", :most_complex_first => "mcf_", :nearest_station_first => "nsf_",
    :genetic_algorithm => "ga_", :particle_swarm => "pso_", :simulated_annealing => "sa_", :random_search => "rs_")

"""Temp file + rename, so a crash can never leave a half-written stats file."""
function write_stats(path, stats)
    tmp = string(path, ".tmp")
    open(tmp, "w") do io
        TOML.print(io, stats)
    end
    mv(tmp, path; force=true)
end

function milp_time_limit_attribute(milp_optimizer::Symbol, seconds)
    milp_optimizer == :glpk && return "tm_lim" => seconds * 1000 # GLPK counts milliseconds
    milp_optimizer == :gurobi && return "TimeLimit" => seconds
    milp_optimizer == :highs && return "time_limit" => Float64(seconds)
    return nothing
end

"""Install the default optimizer of the MILP formulation, with these attributes added to `attrs`."""
function configure_milp_optimizer!(attrs, milp_optimizer::Symbol, time_limit)
    attrs[MOI.Silent()] = false
    default_milp_optimizer = nothing
    if milp_optimizer == :glpk
        default_milp_optimizer = () -> GLPK.Optimizer(; want_infeasibility_certificates=false)
        attrs["msg_lev"] = GLPK.GLP_MSG_ALL
    elseif milp_optimizer == :gurobi
        default_milp_optimizer = () -> Gurobi.Optimizer()
        # MIPFocus: 1 -- feasible solutions, 2 -- optimal solutions, 3 -- bound
        attrs["MIPFocus"] = 1
    elseif milp_optimizer == :highs
        default_milp_optimizer = () -> HiGHS.Optimizer()
        attrs["presolve"] = "on"
    else
        @warn "No additional parameters for $milp_optimizer were set."
    end
    limit = milp_time_limit_attribute(milp_optimizer, time_limit)
    limit === nothing || (attrs[limit.first] = limit.second)
    set_default_milp_optimizer!(default_milp_optimizer)
    clear_default_milp_optimizer_attributes!()
    set_default_milp_optimizer_attributes!(attrs)
    return attrs
end

"""What the solver reports: \"MILP\" results are only as good as this solver in this much time."""
function record_milp_outcome!(stats, milp_model)
    model = milp_model.model
    stats[:TerminationStatus] = string(JuMP.termination_status(model))
    stats[:PrimalStatus] = string(JuMP.primal_status(model))
    for (key, f) in ((:ObjectiveValue, JuMP.objective_value), (:ObjectiveBound, JuMP.objective_bound),
                     (:RelativeGap, JuMP.relative_gap), (:SolverTime, JuMP.solve_time))
        value = try
            Float64(f(model))
        catch # not every solver reports each of these, or there is no solution
            NaN
        end
        isfinite(value) && (stats[key] = value)
    end
end

function solve_assignment(assignment_mode, tg_sched, scene_tree, soln_matrix, stats;
    metaheuristic_iterations, metaheuristic_population, optimizer_time_limit, rng, search_top_k, fixed_priority_keys
)
    function solved_milp(warm_start)
        milp_model = isnothing(warm_start) ? formulate_milp(SparseAdjacencyMILP(), tg_sched, scene_tree) :
                     formulate_milp(SparseAdjacencyMILP(), tg_sched, scene_tree; warm_start_soln=warm_start)
        optimize!(milp_model)
        record_milp_outcome!(stats, milp_model)
        return milp_model, primal_status(milp_model) != MOI.NO_SOLUTION
    end

    if assignment_mode == :milp
        return solved_milp(soln_matrix)
    elseif assignment_mode == :milp_w_greedy_warm_start
        if soln_matrix === nothing
            greedy_sched = deepcopy(tg_sched)
            greedy_model = ConstructionBots.GreedyOrderedAssignment(greedy_cost=GreedyFinalTimeCost())
            greedy_model = formulate_milp(greedy_model, greedy_sched, scene_tree)
            optimize!(greedy_model)
            soln_matrix = get_assignment_matrix(greedy_model)
        end
        return solved_milp(soln_matrix)
    elseif assignment_mode == :greedy
        ## Greedy Assignment with enforced build-step ordering
        milp_model = ConstructionBots.GreedyOrderedAssignment(greedy_cost=GreedyFinalTimeCost())
        milp_model = formulate_milp(milp_model, tg_sched, scene_tree)
        optimize!(milp_model)
        return milp_model, true
    elseif assignment_mode in PRIORITY_RULE_MODES
        milp_model = PriorityRuleAssignment(schedule=tg_sched, problem_spec=scene_tree, rule=assignment_mode)
        optimize!(milp_model)
        return milp_model, true
    elseif assignment_mode in METAHEURISTIC_MODES
        # A stream of its own, derived from the seed, so that it does not overlap the placement stream
        milp_model = MetaheuristicAssignment(schedule=tg_sched, problem_spec=scene_tree, algorithm=assignment_mode,
            iterations=metaheuristic_iterations, population=metaheuristic_population,
            time_limit=Float64(optimizer_time_limit),
            rng=Random.MersenneTwister(rand(copy(rng), UInt32)),
            top_k=search_top_k, fixed_keys=fixed_priority_keys)
        optimize!(milp_model)
        search_top_k > 0 && (stats[:SearchTopPlans] = milp_model.top_plans)
        stats[:SearchHistory] = milp_model.history
        stats[:SearchEvaluations] = milp_model.evaluations
        stats[:SearchTimedOut] = milp_model.timed_out
        stats[:SearchKeptGreedy] = milp_model.kept_greedy
        stats[:SearchIterations] = metaheuristic_iterations
        stats[:SearchPopulation] = metaheuristic_population
        return milp_model, true
    end
    error("Unknown assignment mode: $assignment_mode")
end

function build_visualization(visualizer, scene_tree, sched, staging_circles, color_map)
    delete!(visualizer)

    # Visualize assembly
    factory_vis = ConstructionBots.populate_visualizer!(scene_tree, visualizer;
        color_map=color_map,
        color=RGB(0.3, 0.3, 0.3),
        material_type=MeshLambertMaterial
    )
    ConstructionBots.add_indicator_nodes!(factory_vis)
    factory_vis.staging_nodes = ConstructionBots.render_staging_areas!(visualizer, scene_tree,
        sched, staging_circles;
        dz=0.00, color=RGBA(0.4, 0.0, 0.4, 0.5))
    for (k, color) in [
        (HypersphereKey() => RGBA(0.0, 1.0, 0.0, 0.3)),
        (HyperrectangleKey() => RGBA(1.0, 0.0, 0.0, 0.3))
    ]
        ConstructionBots.show_geometry_layer!(factory_vis, k; color=color)
    end
    for (k, nodes) in factory_vis.geom_nodes
        setvisible!(nodes, false)
    end
    setvisible!(factory_vis.geom_nodes[BaseGeomKey()], true)
    setvisible!(factory_vis.active_flags, false)
    set_scene_tree_to_initial_condition!(scene_tree, sched; remove_all_edges=true)
    ConstructionBots.update_visualizer!(factory_vis)
    return factory_vis
end

function add_agent_policies!(env, tangent_bug_flag, dispersion_flag)
    static_potential_function = (x, r) -> 0.0
    pairwise_potential_function = ConstructionBots.repulsion_potential
    for node in get_nodes(env.sched)
        if matches_template(Union{RobotStart,FormTransportUnit}, node)
            n = entity(node)
            agent_radius = get_radius(get_base_geom(n, HypersphereKey()))
            vmax = ConstructionBots.get_rvo_max_speed(n)

            tangent_bug_pol = nothing
            dispersion_pol = nothing
            if tangent_bug_flag
                tangent_bug_pol = TangentBugPolicy(
                    dt=env.dt, vmax=vmax, agent_radius=agent_radius
                )
            end
            if dispersion_flag
                dispersion_pol = ConstructionBots.PotentialFieldController(
                    agent=n,
                    node=node,
                    agent_radius=agent_radius,
                    vmax=vmax,
                    max_buffer_radius=2.5 * agent_radius,
                    interaction_radius=(15 * agent_radius),
                    static_potentials=static_potential_function,
                    pairwise_potentials=pairwise_potential_function
                )
            end

            env.agent_policies[node_id(n)] = ConstructionBots.VelocityController(
                nominal_policy=tangent_bug_pol,
                dispersion_policy=dispersion_pol
            )
        end
    end
end

function record_animation_preprocessing(visualizer, factory_vis, sched, scene_tree)
    print("Animating preprocessing step...")
    anim = ConstructionBots.AnimationWrapper(visualizer, 0)
    atframe(anim, ConstructionBots.current_frame(anim)) do
        jump_to_final_configuration!(scene_tree; set_edges=true)
        ConstructionBots.update_visualizer!(factory_vis)
        setvisible!(factory_vis.geom_nodes[HyperrectangleKey()], false)
        setvisible!(factory_vis.staging_nodes, false)
    end
    ConstructionBots.step_animation!(anim)
    ConstructionBots.animate_preprocessing_steps!(
        factory_vis,
        sched;
        dt=0.0,
        anim=anim,
        interp_steps=40
    )
    setanimation!(visualizer, anim.anim, play=false)
    print("done\n")
    return anim
end

function record_safety!(stats, env)
    safety = env.safety
    stats[:RobotMinGap] = safety.robot_min_gap
    stats[:RobotOverlapSteps] = safety.robot_overlap_steps
    stats[:MinGap] = safety.min_gap
    stats[:OverlapSteps] = safety.overlap_steps
    stats[:PositionSwaps] = safety.swaps
    stats[:MaxSpeed] = safety.max_speed
end

function _run_lego_demo(visualizer;
    ldraw_file::String="tractor.mpd",
    project_name::String=ldraw_file,
    model_scale::Float64=0.008,
    num_robots::Int=12,
    robot_scale::Float64=model_scale * 0.7,
    robot_height::Float64=10 * robot_scale,
    robot_radius::Float64=25 * robot_scale,
    num_object_layers::Int=1,
    max_steps::Int=100000,
    staging_buffer_factor::Float64=1.2,
    build_step_buffer_factor::Float64=0.5,
    base_results_path::String=joinpath(dirname(pathof(ConstructionBots)), "..", "results"),
    results_path::String=joinpath(base_results_path, project_name),
    assignment_mode::Symbol=:greedy,
    open_animation_at_end::Bool=false,
    save_animation::Bool=false,
    save_animation_along_the_way::Bool=false,
    anim_active_agents::Bool=false,
    anim_active_areas::Bool=false,
    process_updates_interval::Int=50,
    block_save_anim::Bool=false,
    update_anim_at_every_step::Bool=false,
    save_anim_interval::Int=500,
    rvo_flag::Bool=true,
    tangent_bug_flag::Bool=true,
    dispersion_flag::Bool=true,
    overwrite_results::Bool=false,
    write_results::Bool=true,
    max_num_iters_no_progress::Int=10000,
    sim_batch_size::Int=50,
    milp_optimizer::Symbol=:highs,
    milp_optimizer_attribute_dict::Dict=Dict(),
    optimizer_time_limit::Int=600,
    metaheuristic_iterations::Int=25,
    metaheuristic_population::Int=16,
    look_for_previous_milp_solution::Bool=false,
    save_milp_solution::Bool=false,
    previous_found_optimizer_time::Int=30,
    stop_after_task_assignment::Bool=false,
    ignore_rot_matrix_warning::Bool=true,
    rng::Random.AbstractRNG=Random.MersenneTwister(1),
    placement_rng::Union{Nothing,Random.AbstractRNG}=nothing,
    max_acceleration::Float64=Inf,
    search_top_k::Int=0,        # internal: see run_best_simulated_plan
    fixed_priority_keys=nothing,
    extra_stats::Dict=Dict()
)

    process_animation_tasks = visualizer !== nothing
    haskey(ASSIGNMENT_FILE_PREFIXES, assignment_mode) || error("Unknown assignment mode: $(assignment_mode)")
    soln_str_pre = ASSIGNMENT_FILE_PREFIXES[assignment_mode]

    if rvo_flag && !dispersion_flag
        @warn "RVO is enabled but dispersion is disabled. This is not recommended."
    end

    if block_save_anim
        if process_updates_interval != save_anim_interval
            @warn "When block_save_anim is true, it is recommended to set save_anim_interval to the same value as process_updates_interval."
        end
        if !save_animation_along_the_way
            @warn "block_save_anim is true but save_animation_along_the_way is false. Will save along the way anyway."
        end
    end

    # record statistics
    stats = Dict()
    merge!(stats, code_version())
    stats[:Completed] = false
    stats[:rng] = "$rng"
    stats[:modelscale] = model_scale
    stats[:robotscale] = robot_scale
    stats[:assignment_mode] = string(assignment_mode)
    stats[:rvo_flag] = rvo_flag
    stats[:tangent_bug_flag] = tangent_bug_flag
    stats[:dispersion_flag] = dispersion_flag
    stats[:OptimizerTimeLimit] = optimizer_time_limit
    stats[:MaxAcceleration] = max_acceleration
    stats[:PlacementShuffled] = placement_rng !== nothing

    filename = joinpath(dirname(pathof(ConstructionBots)), "..", "LDraw_files", ldraw_file)
    @assert ispath(filename) "File $(filename) does not exist."

    # Adding additional attributes for GLPK, HiGHS, and Gurobi
    uses_milp = assignment_mode in (:milp, :milp_w_greedy_warm_start)
    milp_attributes = copy(milp_optimizer_attribute_dict)
    if uses_milp
        stats[:Optimizer] = string(milp_optimizer)
        stats[:WarmStart] = assignment_mode == :milp_w_greedy_warm_start
        configure_milp_optimizer!(milp_attributes, milp_optimizer, optimizer_time_limit)
    end

    if rvo_flag
        prefix = "RVO"
    else
        prefix = "no-RVO"
    end
    if dispersion_flag
        prefix = string(prefix, "_Dispersion")
    else
        prefix = string(prefix, "_no-Dispersion")
    end
    if tangent_bug_flag
        prefix = string(prefix, "_TangentBug")
    else
        prefix = string(prefix, "_no-TangentBug")
    end
    prefix = string(soln_str_pre, prefix)
    if write_results || save_animation
        mkpath(joinpath(results_path, prefix))
    end
    save_milp_solution && mkpath(results_path)

    name_augment = ""
    if !overwrite_results
        name_augment = string(Dates.format(Dates.now(), "yyyymmdd_HHMMSS"), "_")
    end

    stats_file_name = string(name_augment, "stats", ".toml")
    anim_file_name = string(name_augment, "visualization.html")
    anim_prog_file_name = string(name_augment, "visualization_")

    stats_path = joinpath(results_path, prefix, stats_file_name)
    anim_path = joinpath(results_path, prefix, anim_file_name)
    anim_prog_path = joinpath(results_path, prefix, anim_prog_file_name)


    sim_params = SimParameters(
        sim_batch_size,
        max_steps,
        process_animation_tasks,
        save_anim_interval,
        process_updates_interval,
        block_save_anim,
        update_anim_at_every_step,
        anim_active_agents,
        anim_active_areas,
        anim_prog_path,
        save_animation_along_the_way,
        max_num_iters_no_progress,
        write_results ? joinpath(results_path, "variable_dump") : nothing
    )

    reset_all_id_counters!()
    reset_all_invalid_id_counters!()

    set_default_robot_geom!(
        Cylinder(Point(0.0, 0.0, 0.0), Point(0.0, 0.0, robot_height), robot_radius)
    )

    ConstructionBots.set_rvo_default_time_step!(1 / 40.0)
    ConstructionBots.set_default_loading_speed!(50 * default_robot_radius())
    ConstructionBots.set_default_rotational_loading_speed!(50 * default_robot_radius())
    ConstructionBots.set_staging_buffer_radius!(default_robot_radius()) # for tangent_bug policy
    ConstructionBots.set_max_acceleration!(max_acceleration)

    ConstructionBots.set_rvo_default_neighbor_distance!(16 * default_robot_radius())
    ConstructionBots.set_rvo_default_min_neighbor_distance!(10 * default_robot_radius())

    # Setting default optimizer for staging layout
    ConstructionBots.set_default_geom_optimizer!(ECOS.Optimizer)
    ConstructionBots.set_default_geom_optimizer_attributes!(MOI.Silent() => true)


    pre_execution_start_time = time()
    model = parse_ldraw_file(filename; ignore_rotation_determinant=ignore_rot_matrix_warning)
    populate_part_geometry!(model; ignore_rotation_determinant=ignore_rot_matrix_warning)
    LDrawParser.change_coordinate_system!(model, ldraw_base_transform(), model_scale; ignore_rotation_determinant=ignore_rot_matrix_warning)

    ## CONSTRUCT MODEL SPEC
    print("Constructing model spec...")
    spec = ConstructionBots.construct_model_spec(model)
    model_spec = ConstructionBots.extract_single_model(spec)
    id_map = ConstructionBots.build_id_map(model, model_spec)
    color_map = ConstructionBots.construct_color_map(model_spec, id_map)
    @assert validate_graph(model_spec)
    print("done!\n")

    ## CONSTRUCT SceneTree
    print("Constructing scene tree...")
    assembly_tree = ConstructionBots.construct_assembly_tree(model, model_spec, id_map)
    scene_tree = ConstructionBots.convert_to_scene_tree(assembly_tree)
    print("done!\n")

    # Compute Approximate Geometry
    print("Computing approximate geometry...")
    compute_approximate_geometries!(scene_tree, HypersphereKey())
    compute_approximate_geometries!(scene_tree, HyperrectangleKey())
    print("done!\n")

    # Define TransportUnit configurations
    print("Configuring transport units...")
    config_transport_units_time = time()
    ConstructionBots.init_transport_units!(scene_tree; robot_radius=robot_radius)
    config_transport_units_time = time() - config_transport_units_time
    print("done!\n")

    # The finished model is never carried, so its transport team does not count
    min_robots = maximum(length(robot_team(n)) for n in get_nodes(scene_tree)
                         if matches_template(TransportUnitNode, n) && cargo_id(n) != AssemblyID(1))
    num_robots >= min_robots || throw(NoAssignmentError(
        "$num_robots robots are too few: the largest transport team of $project_name needs $min_robots."))

    # validate SceneTree
    print("Validating scene tree...")
    root = get_node(scene_tree, collect(get_all_root_nodes(scene_tree))[1])
    @assert validate_tree(get_transform_node(root))
    @assert validate_embedded_tree(scene_tree, v -> get_transform_node(get_node(scene_tree, v)))
    print("done!\n")

    ## Add robots to scene tree
    robot_spacing = 5 * robot_radius
    robot_start_box_side = ceil(sqrt(num_robots)) * robot_spacing
    xy_range = (-robot_start_box_side/2:robot_spacing:robot_start_box_side/2)
    vtxs = ConstructionBots.construct_vtx_array(; spacing=(1.0, 1.0, 0.0), ranges=(xy_range, xy_range, 0:0))

    robot_vtxs = StatsBase.sample(rng, vtxs, num_robots; replace=false)

    ConstructionBots.add_robots_to_scene!(scene_tree, robot_vtxs, [default_robot_geom()])

    ## Recompute approximate geometry for when the robot is transporting it
    # Add temporary robots to the transport units and recalculate the bounding geometry
    # then remove them after the new geometries are calcualted
    ConstructionBots.add_temporary_invalid_robots!(scene_tree; with_edges=true)
    compute_approximate_geometries!(scene_tree, HypersphereKey())
    @assert all(map(node -> has_vertex(node.geom_hierarchy, HypersphereKey()), get_nodes(scene_tree)))
    compute_approximate_geometries!(scene_tree, HyperrectangleKey())
    @assert all(map(node -> has_vertex(node.geom_hierarchy, HyperrectangleKey()), get_nodes(scene_tree)))
    ConstructionBots.remove_temporary_invalid_robots!(scene_tree)

    ## Construct Partial Schedule (without robots assigned)
    print("Constructing partial schedule...")
    jump_to_final_configuration!(scene_tree; set_edges=true)
    sched = construct_partial_construction_schedule(model, model_spec, scene_tree, id_map)
    @assert validate_schedule_transform_tree(sched)
    print("done!\n")

    ## Generate staging plan
    print("Generating staging plan...")
    max_object_transport_unit_radius = ConstructionBots.get_max_object_transport_unit_radius(scene_tree)
    staging_plan_time = time()
    staging_circles, bounding_circles = ConstructionBots.generate_staging_plan!(scene_tree, sched;
        buffer_radius=staging_buffer_factor * max_object_transport_unit_radius,
        build_step_buffer_radius=build_step_buffer_factor * default_robot_radius()
    )
    staging_plan_time = time() - staging_plan_time
    print("done!\n")

    # record statistics
    stats[:numobjects] = length([node_id(n) for n in get_nodes(scene_tree) if matches_template(ObjectNode, n)])
    stats[:numassemblies] = length([node_id(n) for n in get_nodes(scene_tree) if matches_template(AssemblyNode, n)])
    stats[:numrobots] = length([node_id(n) for n in get_nodes(scene_tree) if matches_template(RobotNode, n)])
    stats[:ConfigTransportUnitsTime] = config_transport_units_time
    stats[:StagingPlanTime] = staging_plan_time
    write_results && write_stats(stats_path, stats)

    # Move objects to the starting locations. Keep expanding a square from the origin until
    # all objects are placed while not putting obhects in building locations.
    print("Placing objects at starting locations ...")
    # Max height of cargo (excluding the final assembly)
    max_cargo_height = maximum(map(n -> get_base_geom(n, HyperrectangleKey()).radius[3] * 2,
        filter(n -> (matches_template(TransportUnitNode, n) && cargo_id(n) != AssemblyID(1)),
            get_nodes(scene_tree))))
    other_circles = get_buildstep_circles(sched)
    build_circles = remove_redundant(collect(values(other_circles)); ϵ=robot_radius)
    object_vtxs = get_object_vtx(scene_tree, build_circles, max_cargo_height,
        num_object_layers, 2 * robot_radius)
    placement_rng === nothing || Random.shuffle!(placement_rng, object_vtxs)
    ConstructionBots.select_initial_object_grid_locations!(sched, object_vtxs)

    # Move assemblies up so they float above the robots
    for node in get_nodes(scene_tree)
        if matches_template(AssemblyNode, node)
            start_node = get_node(sched, AssemblyComplete(node))
            # raise start
            current = global_transform(start_config(start_node))
            rect = current(get_base_geom(node, HyperrectangleKey()))
            dh = max_cargo_height - (rect.center.-rect.radius)[3]
            set_desired_global_transform_without_affecting_children!(
                start_config(start_node),
                CoordinateTransformations.Translation(current.translation[1:2]..., dh) ∘ CoordinateTransformations.LinearMap(current.linear)
            )
        end
    end
    # Make sure all transforms line up
    ConstructionBots.calibrate_transport_tasks!(sched)
    @assert validate_schedule_transform_tree(sched; post_staging=true)
    print("done!\n")

    # Task Assignments
    print("Assigning robots...")
    ConstructionBots.add_dummy_robot_go_nodes!(sched)
    @assert validate_schedule_transform_tree(sched; post_staging=true)

    # Convert to OperatingSchedule
    ConstructionBots.set_default_loading_speed!(50 * default_robot_radius())
    ConstructionBots.set_default_rotational_loading_speed!(50 * default_robot_radius())

    tg_sched = ConstructionBots.convert_to_operating_schedule(sched)

    assignment_time = time()
    ## MILP solver

    solution_fname = joinpath(results_path, string(soln_str_pre, "$(num_robots).jld2"))
    no_solution_fname = joinpath(results_path, string(soln_str_pre, "$(num_robots)_NO-SOLN.jld2"))

    soln_matrix = nothing
    if look_for_previous_milp_solution && uses_milp
        if milp_optimizer == :glpk
            @warn """GLPK is not currently implemented through JuMP to support warm-starting.
                       Recommend using HiGHS (:highs) or Gurobi (:gurobi) when using previous solutions."""
        end
        if isfile(solution_fname)
            println("\n\tFound previous MILP solution at $solution_fname")
            soln_matrix = JLD2.load(solution_fname, "soln_matrix")
            soln_matrix = SparseArrays.SparseMatrixCSC(soln_matrix)
            limit = milp_time_limit_attribute(milp_optimizer, previous_found_optimizer_time)
            limit === nothing || (milp_attributes[limit.first] = limit.second)
            clear_default_milp_optimizer_attributes!()
            set_default_milp_optimizer_attributes!(milp_attributes)
        elseif isfile(no_solution_fname)
            println("Aborting based on finding $no_solution_fname")
            throw(NoSolutionError())
        else
            println("\n\tNo previous MILP solution at $solution_fname")
        end
    end

    if assignment_mode == :milp_w_greedy_warm_start && milp_optimizer == :glpk
        println()
        @warn """GLPK is not currently implemented through JuMP to support warm-starting.
                   Recommend using HiGHS (:highs) or Gurobi (:gurobi)."""
    end
    milp_model, valid_milp_solution = solve_assignment(assignment_mode, tg_sched, scene_tree, soln_matrix, stats;
        metaheuristic_iterations, metaheuristic_population, optimizer_time_limit, rng, search_top_k, fixed_priority_keys)
    merge!(stats, extra_stats)

    post_assignment_makespan = Inf
    if valid_milp_solution
        @assert validate_schedule_transform_tree(
            ConstructionBots.convert_from_operating_schedule(typeof(sched), tg_sched)
            ; post_staging=true)
        @assert update_project_schedule!(nothing, milp_model, tg_sched, scene_tree) "the assignment causes a cycle in the schedule"
        @assert validate(tg_sched)
        stats[:AssignmentPlan] = assignment_plan(tg_sched)
        # Assign robots to "home" locations so they don't sit around in each others' way
        go_nodes = [n for n in get_nodes(tg_sched) if matches_template(RobotGo, n) && is_terminal_node(tg_sched, n)]
        min_assembly_1_xy = (staging_circles[AssemblyID(1)].center.-staging_circles[AssemblyID(1)].radius)[1:2]
        for (ii, n) in enumerate(go_nodes)
            vtx_x = min_assembly_1_xy[1] - ii * 5 * robot_radius
            vtx_y = min_assembly_1_xy[2]
            set_desired_global_transform!(goal_config(n),
                CoordinateTransformations.Translation(vtx_x, vtx_y, 0.0) ∘ identity_linear_map()
            )
        end
        post_assignment_makespan = makespan(tg_sched)
    end
    assignment_time = time() - assignment_time
    print("done!\n")

    # If valid milp solution found, save if option was passed
    if valid_milp_solution && save_milp_solution && uses_milp
        println("Saving MILP solution to $solution_fname")
        JLD2.save(solution_fname, "soln_matrix", get_assignment_matrix(milp_model))
    elseif save_milp_solution && uses_milp
        println("Saving a no soltuion file to $no_solution_fname")
        JLD2.save(no_solution_fname, "soln_matrix", false)
    end

    # compile pre execution statistics
    pre_execution_time = time() - pre_execution_start_time

    stats[:AssignmentTime] = assignment_time
    stats[:PreExecutionRuntime] = pre_execution_time
    stats[:OptimisticMakespan] = post_assignment_makespan
    stats[:ValidMILPSolution] = valid_milp_solution
    write_results && write_stats(stats_path, stats)

    if !valid_milp_solution
        throw(NoSolutionError())
    elseif stop_after_task_assignment
        stats[:Completed] = true
        write_results && write_stats(stats_path, stats)
        return nothing, stats
    end

    factory_vis = ConstructionBots.FactoryVisualizer(vis=visualizer)
    if !isnothing(visualizer)
        factory_vis = build_visualization(visualizer, scene_tree, sched, staging_circles, color_map)
    end

    set_scene_tree_to_initial_condition!(scene_tree, sched; remove_all_edges=true)


    # rvo
    if rvo_flag
        ConstructionBots.reset_rvo_python_module!()
        ConstructionBots.rvo_set_new_sim!(ConstructionBots.rvo_new_sim())
    end


    max_robot_go_id = maximum([n.id.id for n in get_nodes(tg_sched) if matches_template(RobotGo, n)])
    max_cargo_id = maximum([cargo_id(entity(n)).id for n in get_nodes(tg_sched) if matches_template(TransportUnitGo, n)])

    env = PlannerEnv(
        sched=tg_sched,
        scene_tree=scene_tree,
        staging_circles=staging_circles,
        max_robot_go_id=max_robot_go_id,
        max_cargo_id=max_cargo_id,
    )

    if rvo_flag
        ConstructionBots.rvo_add_agents!(scene_tree)
    end

    add_agent_policies!(env, tangent_bug_flag, dispersion_flag)

    anim = nothing
    if process_animation_tasks
        anim = record_animation_preprocessing(visualizer, factory_vis, sched, scene_tree)
        if save_animation_along_the_way
            save_animation!(visualizer, "$(anim_prog_path)preprocessing.html")
        end
    end

    set_use_rvo!(rvo_flag)
    set_avoid_staging_areas!(true)

    execution_start_time = time()

    status, time_steps = run_simulation!(env, factory_vis, anim, sim_params)

    if status == true
        execution_time = time() - execution_start_time
    else
        execution_time = Inf
        time_steps = Inf
    end

    # Add results
    stats[:ExecutionRuntime] = execution_time
    stats[:Makespan] = time_steps * env.dt
    stats[:MakespanPerPart] = stats[:Makespan] / stats[:numobjects]
    record_safety!(stats, env)
    stats[:Completed] = true
    write_results && write_stats(stats_path, stats)

    if process_animation_tasks
        if save_animation
            save_animation!(visualizer, anim_path)
        end
        if open_animation_at_end
            open(visualizer)
        end
    end
    return env, stats
end
