let
    # Five wins out of five: only all-plus and all-minus are as extreme, out of 2^5 sign patterns.
    @test sign_flip_p([1.0, 2.0, 3.0, 4.0, 5.0]) == 2 / 32
    @test sign_flip_p([1.0, -1.0]) == 1.0
    @test sign_flip_p([0.0, 0.0]) == 1.0
    @test sign_flip_p(ones(20)) < 1e-4 # sampled, not exact

    @test holm_adjust([0.01, 0.04, 0.03]) ≈ [0.03, 0.06, 0.06]
    @test holm_adjust([0.5, 0.9]) == [1.0, 1.0]

    @test spearman([1, 2, 3, 4], [10, 20, 30, 40]) ≈ 1
    @test spearman([1, 2, 3, 4], [4, 3, 2, 1]) ≈ -1
    @test isnan(spearman([1, 1, 1], [1, 2, 3]))

    @test bootstrap_ci([1.0, 2.0]) === (missing, missing)
    low, high = bootstrap_ci([1.0, 2.0, 3.0, 4.0, 5.0])
    @test 1 <= low < 3 < high <= 5
    @test bootstrap_ci([1.0, 2.0, 3.0, 4.0, 5.0]) == (low, high) # reproducible

    baseline = Dict(1 => 10.0, 2 => 12.0, 3 => 14.0, 4 => 9.0)
    faster = Dict(1 => 9.0, 2 => 10.0, 3 => 11.0)     # seed 4 failed, so it cannot be compared
    unrelated = Dict(7 => 1.0)
    results = Dict(paired_comparison(baseline, ["faster" => faster, "unrelated" => unrelated]))
    r = results["faster"]
    @test (r.n, r.wins, r.losses) == (3, 3, 0)
    @test r.mean_gain ≈ 2
    @test r.effect_size ≈ 2
    @test r.p == 2 / 8
    @test r.p_holm == 2 / 8  # a method with no matched seeds is not a test, so it does not count against it
    @test results["unrelated"].n == 0
    @test results["unrelated"].p === missing
end
