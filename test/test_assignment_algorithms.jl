let
    project_params = get_project_params(:tractor)
    plan_of(mode; kwargs...) = run_lego_demo(;
        ldraw_file                 = project_params[:file_name],
        project_name               = project_params[:project_name],
        model_scale                = project_params[:model_scale],
        num_robots                 = project_params[:num_robots],
        assignment_mode            = mode,
        metaheuristic_iterations   = 4,
        metaheuristic_population   = 6,
        write_results              = false,
        stop_after_task_assignment = true,
        kwargs...
    )[2]
    assignments(stats) = sort!([(p["cargo"], sort(p["robots"]), p["start"], p["finish"]) for p in stats[:AssignmentPlan]])

    greedy = plan_of(:greedy)

    for mode in (:greedy_with_travel, :most_complex_first, :nearest_station_first,
                 :genetic_algorithm, :particle_swarm, :simulated_annealing, :random_search)
        stats = plan_of(mode)
        @test isfinite(stats[:OptimisticMakespan])
        plan = stats[:AssignmentPlan]
        @test length(plan) == stats[:numobjects] + stats[:numassemblies] - 1 # every part and sub-assembly is carried once
        @test all(p -> p["start"] <= p["finish"] && !isempty(p["robots"]), plan)
        if haskey(stats, :SearchHistory)
            h = stats[:SearchHistory]
            @test issorted(h; rev=true)                      # the best schedule never gets worse
            @test h[end] ≈ stats[:OptimisticMakespan]        # the schedule handed on is the best one found
            @test stats[:SearchEvaluations] >= length(h)
            # Greedy's schedule is a candidate, so the plan is never worse than Greedy's
            @test stats[:OptimisticMakespan] <= greedy[:OptimisticMakespan] + 1e-9
        end
    end

    @testset "The search leaves the schedule as it found it" begin
        # With no time to search, the result is Greedy's own schedule, built after Greedy has already
        # been evaluated once on the same schedule. Any leftover from that evaluation would change it.
        stats = plan_of(:genetic_algorithm; optimizer_time_limit=-1)
        @test stats[:SearchTimedOut] && stats[:SearchKeptGreedy]
        @test stats[:SearchEvaluations] == 1
        @test stats[:SearchHistory] ≈ [greedy[:OptimisticMakespan]]
        @test assignments(stats) == assignments(greedy)
        @test stats[:OptimisticMakespan] == greedy[:OptimisticMakespan]
    end

    @testset "Seeds repeat exactly and differ from each other" begin
        for mode in (:greedy, :genetic_algorithm, :simulated_annealing)
            @test assignments(plan_of(mode; rng=MersenneTwister(2))) == assignments(plan_of(mode; rng=MersenneTwister(2)))
        end
        @test assignments(plan_of(:greedy; rng=MersenneTwister(1))) != assignments(plan_of(:greedy; rng=MersenneTwister(2)))
    end

    @testset "Choosing the plan by simulating it" begin
        simulated(; kwargs...) = run_lego_demo(;
            ldraw_file=project_params[:file_name], project_name=project_params[:project_name],
            model_scale=project_params[:model_scale], num_robots=project_params[:num_robots],
            metaheuristic_iterations=4, metaheuristic_population=6, write_results=false, kwargs...)[2]
        plain_greedy = simulated(; assignment_mode=:greedy)
        stats = simulated(; assignment_mode=:genetic_algorithm, simulate_top_plans=3)
        @test stats[:TopPlanMakespans][1] == plain_greedy[:Makespan]
        @test length(stats[:TopPlanMakespans]) == 4
        @test stats[:Makespan] == minimum(stats[:TopPlanMakespans]) # the rerun of the winner reproduces it exactly
        @test stats[:Makespan] <= plain_greedy[:Makespan]           # never worse than Greedy in simulation
        @test stats[:OptimisticMakespan] == stats[:TopPlanPlanned][stats[:SelectedPlan]+1]
        @test stats[:assignment_mode] == "genetic_algorithm"
        @test_throws ErrorException simulated(; assignment_mode=:greedy, simulate_top_plans=2)
    end

    @testset "Greedy is unchanged (saved assignment)" begin
        # Recorded on Windows; Linux gives the identical plan. Regenerate with test/fixtures/make_greedy_fixture.jl.
        fixture = TOML.parsefile(joinpath(@__DIR__, "fixtures", "greedy_tractor_seed1.toml"))
        @test greedy[:OptimisticMakespan] ≈ fixture["planned"]
        @test [[p["cargo"], sort(p["robots"])] for p in greedy[:AssignmentPlan]] ==
              [[t["cargo"], t["robots"]] for t in fixture["tasks"]]
    end
end
