# Statistics for comparing assignment methods over matched seeds. Results are not normally distributed
# and samples are small, so everything is distribution-free. The same methods exist in Python for the
# dashboard (dashboard/simulation/compare.py).

export bootstrap_ci, sign_flip_p, holm_adjust, spearman, paired_comparison

"""
    bootstrap_ci(xs; level=0.95, n_samples=4000) -> (low, high)

Percentile bootstrap interval of the mean, with a fixed random stream so that it is reproducible.
`(missing, missing)` below 3 values, where an interval would mean little.
"""
function bootstrap_ci(xs; level=0.95, n_samples=4000)
    length(xs) < 3 && return (missing, missing)
    rng = Random.MersenneTwister(0)
    means = sort!([sum(rand(rng, xs, length(xs))) / length(xs) for _ in 1:n_samples])
    alpha = (1 - level) / 2
    return means[max(1, floor(Int, alpha * n_samples))], means[ceil(Int, (1 - alpha) * n_samples)]
end

"""
    sign_flip_p(diffs; max_exact=16, n_samples=100_000) -> p

Two-sided paired sign-flip permutation test of a mean difference of zero. Exact up to `max_exact`
non-zero pairs, sampled above that. With n pairs the smallest possible exact p is 2 / 2^n, so 6 pairs
are needed to reach p < 0.05 at all.
"""
function sign_flip_p(diffs; max_exact=16, n_samples=100_000)
    nonzero = [d for d in diffs if d != 0]
    isempty(nonzero) && return 1.0
    n = length(nonzero)
    observed = abs(sum(nonzero)) - 1e-12
    if n <= max_exact
        hits = count(0:(2^n - 1)) do bits
            abs(sum(((bits >> (i - 1)) & 1 == 1 ? -1 : 1) * nonzero[i] for i in 1:n)) >= observed
        end
        return hits / 2^n
    end
    rng = Random.MersenneTwister(0)
    hits = count(_ -> abs(sum(rand(rng, Bool) ? d : -d for d in nonzero)) >= observed, 1:n_samples)
    return (hits + 1) / (n_samples + 1)
end

"""Holm's step-down correction for several tests against one baseline."""
function holm_adjust(ps)
    adjusted = zeros(length(ps))
    running = 0.0
    for (rank, i) in enumerate(sortperm(ps))
        running = max(running, min(1.0, (length(ps) - rank + 1) * ps[i]))
        adjusted[i] = running
    end
    return adjusted
end

"""Spearman rank correlation. NaN when either side is constant."""
spearman(xs, ys) = StatsBase.corspearman(Float64.(collect(xs)), Float64.(collect(ys)))

"""
    paired_comparison(baseline, others) -> Vector of `label => result`

`baseline` maps seed to value, and `others` holds `label => (seed => value)` pairs. Each result compares
on the seeds that both have: `n`, `mean_gain` (baseline minus other, so positive means lower than the
baseline), its bootstrap `ci_low` and `ci_high`, `effect_size` (Cohen's dz), `wins`, `losses`, the
sign-flip `p` and the Holm-corrected `p_holm`.
"""
function paired_comparison(baseline, others)
    results = map(collect(others)) do (label, values)
        diffs = [baseline[s] - values[s] for s in keys(values) if haskey(baseline, s)]
        n = length(diffs)
        mean_gain = n == 0 ? missing : sum(diffs) / n
        sd = n < 2 ? missing : sqrt(sum((d - mean_gain)^2 for d in diffs) / (n - 1))
        ci = bootstrap_ci(diffs)
        (; label, n, mean_gain, ci_low=ci[1], ci_high=ci[2],
         effect_size=(sd === missing || sd == 0) ? missing : mean_gain / sd,
         wins=count(>(0), diffs), losses=count(<(0), diffs), p=n == 0 ? missing : sign_flip_p(diffs))
    end
    tested = [r.p for r in results if r.p !== missing]
    adjusted = Iterators.Stateful(holm_adjust(tested))
    return [r.label => merge(r, (; p_holm=r.p === missing ? missing : popfirst!(adjusted))) for r in results]
end
