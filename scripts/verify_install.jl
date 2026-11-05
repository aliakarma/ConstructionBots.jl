# Proves an installation works: builds the Tractor with Greedy and compares the plan with the recorded one.
#     julia --project scripts/verify_install.jl
using ConstructionBots, Random, TOML

p = get_project_params(:tractor)
_, stats = run_lego_demo(; ldraw_file=p[:file_name], project_name=p[:project_name], model_scale=p[:model_scale],
    num_robots=p[:num_robots], assignment_mode=:greedy, rng=MersenneTwister(1), write_results=false)
recorded = TOML.parsefile(joinpath(@__DIR__, "..", "test", "fixtures", "greedy_tractor_seed1.toml"))["planned"]
planned = stats[:OptimisticMakespan]
println("Tractor, Greedy, seed 1: planned $planned s (recorded $recorded s), simulated $(stats[:Makespan]) s, ",
        "code version $(stats[:SourceHash])")
# Same tolerance as test_assignment_algorithms.jl: one time step of rounding across CPU architectures.
if !isfinite(stats[:Makespan]) || !isapprox(planned, recorded; atol=0.05)
    println(stderr, "The installation runs, but it does not reproduce the recorded result.")
    exit(1)
end
println("OK: the simulator works and reproduces the recorded result.")
