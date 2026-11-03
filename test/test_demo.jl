let
    project = get_project_params(:tractor)
    tractor = (ldraw_file=project[:file_name], project_name=project[:project_name],
               model_scale=project[:model_scale], num_robots=project[:num_robots])
    repo = joinpath(dirname(pathof(ConstructionBots)), "..")
    dumps_before = isdir(joinpath(repo, "variable_dump")) ? readdir(joinpath(repo, "variable_dump")) : String[]

    @testset "A full run completes and records what it did" begin
        mktempdir() do tmp
            logger_before = global_logger()
            attributes = Dict("mip_rel_gap" => 0.5)
            env, stats = run_lego_demo(; tractor..., base_results_path=tmp, milp_optimizer_attribute_dict=attributes)
            @test global_logger() === logger_before # a library must not replace the caller's logger
            @test attributes == Dict("mip_rel_gap" => 0.5)
            @test project_complete(env)
            @test stats[:Completed]
            @test isfinite(stats[:Makespan]) && stats[:Makespan] > 0
            @test stats[:Makespan] >= stats[:OptimisticMakespan] # the plan ignores traffic
            @test stats[:numobjects] == 20 && stats[:numassemblies] == 8
            @test stats[:MakespanPerPart] ≈ stats[:Makespan] / 20

            # safety
            @test isfinite(stats[:RobotMinGap]) && isfinite(stats[:MinGap])
            @test stats[:MinGap] <= stats[:RobotMinGap] + 1e-9 || stats[:OverlapSteps] >= stats[:RobotOverlapSteps]
            @test stats[:RobotOverlapSteps] >= 0 && stats[:PositionSwaps] >= 0
            @test 0 < stats[:MaxSpeed] < 10 # no teleports are hidden in the speed

            # code version
            @test length(stats[:SourceHash]) == 12
            @test stats[:SourceHash] == ConstructionBots.SOURCE_HASH

            files = [joinpath(r, f) for (r, _, fs) in walkdir(tmp) for f in fs]
            stats_file = only(filter(f -> endswith(f, "stats.toml"), files))
            on_disk = TOML.parsefile(stats_file)
            @test on_disk["Completed"] === true
            @test on_disk["Makespan"] == stats[:Makespan]
            @test on_disk["SourceHash"] == stats[:SourceHash]
            @test !any(f -> endswith(f, ".tmp"), files) # stats are written atomically
        end
    end

    @testset "write_results=false touches nothing on disk" begin
        mktempdir() do tmp
            target = joinpath(tmp, "not_created")
            run_lego_demo(; tractor..., results_path=target, write_results=false, stop_after_task_assignment=true)
            @test !ispath(target)
        end
    end

    @testset "Too few robots is a clear error" begin
        @test_throws ConstructionBots.NoAssignmentError run_lego_demo(; tractor..., num_robots=3, write_results=false)
        @test run_lego_demo(; tractor..., num_robots=4, write_results=false, stop_after_task_assignment=true)[2][:Completed]
    end

    @testset "A stuck run stays inside its results folder" begin
        mktempdir() do tmp
            target = joinpath(tmp, "out")
            env, stats = run_lego_demo(; tractor..., results_path=target, max_num_iters_no_progress=5)
            @test !project_complete(env)
            @test stats[:Makespan] == Inf
            @test stats[:Completed] # the record is complete, the project is not
            @test isdir(joinpath(target, "variable_dump"))
        end
        now_there = isdir(joinpath(repo, "variable_dump")) ? readdir(joinpath(repo, "variable_dump")) : String[]
        @test now_there == dumps_before
    end

    @testset "Saved animations contain movement" begin
        mktempdir() do tmp
            env, stats = run_lego_demo(; tractor..., base_results_path=tmp, save_animation=true,
                                       anim_active_agents=true, anim_active_areas=true)
            @test stats[:Completed]
            animation = only(f for (r, _, fs) in walkdir(tmp) for f in fs if endswith(f, "visualization.html"))
            path = only(joinpath(r, f) for (r, _, fs) in walkdir(tmp) for f in fs if f == animation)
            @test Main.ExperimentLab._animation_info(path).moving > 0
        end
    end

    @testset "MILP results say how far the solver got" begin
        @test ConstructionBots.milp_time_limit_attribute(:glpk, 30) == ("tm_lim" => 30_000) # milliseconds
        @test ConstructionBots.milp_time_limit_attribute(:highs, 30) == ("time_limit" => 30.0)
        @test ConstructionBots.milp_time_limit_attribute(:gurobi, 30) == ("TimeLimit" => 30)
        stats = run_lego_demo(; tractor..., assignment_mode=:milp_w_greedy_warm_start, milp_optimizer=:highs,
                              optimizer_time_limit=10, write_results=false, stop_after_task_assignment=true)[2]
        @test stats[:Optimizer] == "highs" && stats[:WarmStart]
        @test stats[:TerminationStatus] in ("OPTIMAL", "TIME_LIMIT")
        @test isfinite(stats[:ObjectiveValue]) && haskey(stats, :ObjectiveBound)
    end

    @testset "Runs do not leak into each other" begin
        run_without_rvo() = run_lego_demo(; tractor..., rvo_flag=false, tangent_bug_flag=false, dispersion_flag=false,
                                          write_results=false)[2]
        first_run = run_without_rvo()
        run_lego_demo(; tractor..., write_results=false) # with RVO in between
        second_run = run_without_rvo()
        @test first_run[:Makespan] == second_run[:Makespan]
        # Without avoidance robots do overlap, and the record has to show it.
        @test first_run[:RobotOverlapSteps] > 0
        @test first_run[:RobotMinGap] < 0
    end

    @testset "Acceleration limit" begin
        limited = run_lego_demo(; tractor..., max_acceleration=40.0, write_results=false)[2]
        @test limited[:Completed] && isfinite(limited[:Makespan])
        @test limited[:MaxAcceleration] == 40.0
    end

    @testset "Part placement can be randomized" begin
        run_with(placement) = run_lego_demo(; tractor..., placement_rng=placement, write_results=false,
                                            stop_after_task_assignment=true)[2]
        fixed, shuffled = run_with(nothing), run_with(MersenneTwister(5))
        @test shuffled[:PlacementShuffled] && !fixed[:PlacementShuffled]
        @test shuffled[:OptimisticMakespan] != fixed[:OptimisticMakespan]
        @test shuffled[:OptimisticMakespan] == run_with(MersenneTwister(5))[:OptimisticMakespan]
    end

    @testset "The notebook's run_experiment works and saves a complete record" begin
        mktempdir() do tmp
            Main.ExperimentLab.lab_setup(; repo_root=repo, results_folder=tmp)
            lab = Main.ExperimentLab
            rec = lab.run_experiment(lab.ExperimentConfig(; model="Tractor", assignment="Random search",
                                                          search_iterations=2, search_population=4, reuse_results=false);
                                     verbose=false)
            @test rec[:status] == "success"
            @test rec[:robot_min_gap_m] isa Real && rec[:position_swaps] isa Integer
            @test rec[:source_hash] == ConstructionBots.SOURCE_HASH
            again = lab.run_experiment(lab.ExperimentConfig(; model="Tractor", assignment="Random search",
                                                            search_iterations=2, search_population=4); verbose=false)
            @test occursin("reused", again[:status_detail])
            @test again[:makespan_s] == rec[:makespan_s]
            @test length(lab.read_csv(joinpath(tmp, "all_runs.csv"))) == 2
            failed = lab.run_experiment(lab.ExperimentConfig(; model="Tractor", num_robots=2, reuse_results=false); verbose=false)
            @test failed[:status] == "failed" && occursin("too few", failed[:status_detail])
        end
    end
end
