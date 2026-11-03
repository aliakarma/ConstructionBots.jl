# Regenerates greedy_tractor_seed1.toml, the saved Greedy assignment that test_assignment_algorithms.jl
# compares against. Only rerun it after a deliberate change to Greedy, and say so in the commit message.
#     julia --project test/fixtures/make_greedy_fixture.jl
using ConstructionBots, Random, TOML

p = get_project_params(:tractor)
stats = run_lego_demo(; ldraw_file=p[:file_name], project_name=p[:project_name], model_scale=p[:model_scale],
    num_robots=p[:num_robots], assignment_mode=:greedy, rng=MersenneTwister(1), write_results=false,
    stop_after_task_assignment=true)[2]
fixture = Dict("platform" => string(Sys.KERNEL), "planned" => stats[:OptimisticMakespan],
    "tasks" => [Dict("cargo" => t["cargo"], "robots" => sort(t["robots"])) for t in stats[:AssignmentPlan]])
open(joinpath(@__DIR__, "greedy_tractor_seed1.toml"), "w") do io
    TOML.print(io, fixture; sorted=true)
end
println("Saved Greedy plan: planned makespan ", stats[:OptimisticMakespan])
