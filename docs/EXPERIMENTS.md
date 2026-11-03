# Experiments

What this fork's assignment methods do in simulation, and what the evidence does and does not support.

All results come from one version of the code, source hash `1ce4205b64cd`, on Windows 11 with Julia 1.10.12 (Experiment 7 confirms Linux gives the same numbers). The raw runs are in [`experiments/`](experiments/), and every table can be checked against [`experiments/tables.md`](experiments/tables.md), which is generated from them.

## Main findings

1. **A better plan does not reliably mean a faster build.** On `colored_8x8`, plain metaheuristics plan about 15 % shorter than Greedy but take more than twice as long in simulation, and 12 of 120 runs never finish.
2. **Choosing the plan by simulating it works.** Simulating Greedy and the search's 5 best plans (`simulate_top_plans=5`) had the lowest mean on 5 of 6 models and was within 0.1 s of the lowest on the other. It is never slower than Greedy, by construction, and costs 6 extra simulations.
3. **The search operators add little beyond random sampling.** Compared with random search at the same budget, GA was significantly better only on the Tractor. PSO and SA were not significantly better on any model.
4. **Nearest station first is slower than Greedy on every model**, and the other rules depend on the model. Greedy with travel is slower than Greedy on the Tractor and faster on the TIE Fighter.
5. **Brief overlaps occur with full collision avoidance under every method** and do not clearly favour any method. The simulated completion time does not penalize them.

These findings cover six small and medium models. They do not establish how the methods behave on large models, and nothing here has been calibrated against real robots.

## Experiment 1: methods compared over matched seeds

Every method ran on the same seeds, with search budget 25 × 16 and a 120 s search limit. Only the seeds where both methods succeeded are compared. Tests are two-sided paired sign-flip tests, Holm-corrected over the 8 methods on each model.

Mean simulated completion time in seconds, over successful runs. **Bold** means significantly faster than Greedy (Holm p < 0.05), and *italics* significantly slower.

| Method | Tractor | Colored 8×8 | TIE Fighter | X-Wing mini | Imperial Shuttle | AT-TE Walker |
|---|---|---|---|---|---|---|
| Seeds | 30 | 30 | 30 | 18 to 19 | 12 to 13 | 7 to 8 |
| Greedy | 20.30 | 18.06 | 41.53 | 40.80 | 66.56 | 44.25 |
| Greedy with travel | *21.30* | 17.95 | **35.38** | 41.21 | 65.27 | 43.93 |
| Most complex first | *22.89* | 18.06 | **34.89** | 40.63 | 64.29 | 42.07 |
| Nearest station first | *27.68* | *47.05* | *73.52* | *109.54* | *147.93* | 146.42 |
| Genetic algorithm | **18.15** | *38.90* | **31.91** | 39.37 | **57.45** | 42.73 |
| Particle swarm | **18.95** | *48.17* | **31.64** | **39.00** | 61.10 | 41.51 |
| Simulated annealing | **18.61** | *47.35* | **31.93** | 39.22 | 67.96 | 41.69 |
| Random search | 19.40 | *37.85* | **32.21** | 38.84 | **57.73** | 42.62 |
| GA + simulate top 5 | **17.67** | 18.04 | **30.78** | **37.69** | **55.46** | 41.36 |

- **Colored 8×8 is the warning.** All four plain searches plan better than Greedy (about 9.6 s against 11.3 s) and simulate far worse. GA failed to finish 5 of 30 runs, PSO 4, random search 2 and SA 1. Across the plain searches, planned and simulated times are not positively related (Spearman −0.15).
- **The top-5 selection avoids this:** it finished all 30 runs at 18.04 s, nearly always by keeping Greedy's plan.
- **Simulated annealing's mean on the Imperial Shuttle (67.96 s) is driven by outliers:** its standard deviation is 33.89 s, against 3.29 s for GA.
- **AT-TE Walker has too few seeds for its gains to be significant after correction**, and 17 of its 35 search runs hit the 120 s limit, so those runs are not exactly reproducible.
- **Random search shows the search operators are not doing most of the work.** Against it, GA's mean gain is 1.25 s on the Tractor (Holm p = 0.002), and between −0.79 s and 0.45 s on the other five models, none significant. Most of the plain gain comes from sampling many plans at all.

## Experiment 2: robot count and part locations

**Robot count, Tractor, 10 seeds.** GA's gain over Greedy depends on the number of robots. It is significant at 8, 10 and 14 robots and absent at the extremes:

| Robots | Greedy [s] | GA [s] | Mean gain [s] | p |
|---|---|---|---|---|
| 4 | 34.92 | 36.08 | −1.17 | 0.127 |
| 6 | 28.03 | 27.24 | 0.80 | 0.365 |
| 8 | 25.21 | 22.14 | 3.07 | 0.012 |
| 10 | 20.23 | 18.25 | 1.98 | 0.006 |
| 14 | 17.97 | 15.99 | 1.98 | 0.002 |
| 20 | 16.26 | 16.37 | −0.10 | 0.912 |

Greedy's completion time falls steadily with more robots and flattens at around 14 to 20.

**Part locations, Tractor, 6 seeds each.** With the parts' pick-up locations shuffled (5 layouts), GA's mean gain over Greedy was positive every time, from 1.06 s to 4.35 s. With 6 seeds per layout, only two layouts reached p < 0.05 (p = 0.031 each), uncorrected across the layouts.

## Experiment 3: safety

Finished runs with at least one overlap between free robots, under full collision avoidance:

| Method | Tractor | Colored 8×8 | TIE Fighter | X-Wing mini | Imperial Shuttle | AT-TE Walker |
|---|---|---|---|---|---|---|
| Greedy | 12/30 | 15/30 | 17/30 | 13/19 | 7/13 | 3/8 |
| Genetic algorithm | 9/30 | 17/25 | 10/30 | 11/19 | 6/13 | 1/7 |
| GA + simulate top 5 | 8/30 | 14/30 | 15/30 | 10/18 | 6/12 | 1/7 |

- **Overlaps are common but small.** The deepest on each model was 6.6 to 12.3 cm. A detailed log of Greedy on three models (6 seeds each) found 1 to 3 overlapping steps per affected run, or 25 to 75 ms, and depths of 0.4 to 7.6 cm.
- **Most are not team formation.** In that log they were between robots on different tasks, or shortly after a team disbanded. On `colored_8x8` they all came at about 0.95 s into the run, on 3 of 6 seeds.
- **Position swaps are rare:** at most 3 per method over 30 runs on the Tractor.
- **Speed stays near the 4 m/s limit once swaps are left out** (at most 4.15 m/s in any run of Experiment 1). The audit saw spikes of 12 and 34 m/s when swaps were included, so this supports its suspicion that swaps caused them.
- **Without avoidance, overlaps are far worse:** Greedy on the Tractor, seed 1, overlaps for 134 steps with a −0.24 m gap, and finishes in 14.93 s rather than 22.75 s. That faster time is not an improvement.

The cause of the brief overlaps with avoidance on was not established, and they were not removed.

## Experiment 4: decoder against search

Mean planned and simulated completion time, separating what each ingredient contributes. Random search uses the search's decoder with no search operators.

| Model | | Greedy | Greedy with travel | Random search | GA |
|---|---|---|---|---|---|
| Tractor | planned | 14.55 | 14.22 | 12.24 | 11.75 |
| | simulated | 20.30 | 21.30 | 19.40 | 18.15 |
| TIE Fighter | planned | 29.43 | 26.32 | 23.33 | 22.80 |
| | simulated | 41.53 | 35.38 | 32.21 | 31.91 |

On the TIE Fighter, most of the simulated gain comes from the decoder (6.15 s of 9.62 s). On the Tractor, the decoder makes the simulation slower despite a better plan.

## Experiment 5: search budget

Tractor, 10 seeds. More evaluations keep improving the plan, while the simulated gain is smaller:

| Mean evaluations | GA planned | GA simulated | SA planned | SA simulated |
|---|---|---|---|---|
| 3 to 4 | 13.64 | 20.63 | 13.55 | 20.82 |
| 7 to 12 | 13.41 | 20.46 | 13.25 | 20.93 |
| 92 to 102 | 12.37 | 19.83 | 12.30 | 19.64 |
| 800 to 1,002 | 11.50 | 18.52 | 11.44 | 18.40 |
| 8,813 to 9,932 | 11.15 | 18.18 | 10.99 | 18.06 |

Within one budget, the rank correlation between planned and simulated time ranges from 0.33 to 0.76, so on the Tractor better plans do help on average. The default of 400 evaluations is not an optimized choice. Two of the 100 runs hit the 600 s limit while other jobs loaded the machine.

## Experiment 6: MILP with a 300 s limit

Tractor and Colored 8×8, seeds 1 and 2, planned / simulated completion time in seconds. **No run proved optimality**: all stopped at the time limit.

| Model, seed | HiGHS | HiGHS warm start | Gurobi | Gurobi warm start | Best lower bound |
|---|---|---|---|---|---|
| Tractor, 1 | 28.70 / 37.28 | 14.85 / 22.45 | 10.85 / 18.38 | 11.08 / 16.53 | 8.57 |
| Tractor, 2 | 24.30 / 35.68 | 14.25 / 18.38 | 11.15 / 20.30 | 10.98 / 16.33 | 8.42 |
| Colored 8×8, 1 | 17.35 / 25.25 | 11.30 / 17.30 | 9.55 / 25.88 | 8.90 / 40.05 | 5.76 |
| Colored 8×8, 2 | 17.63 / 25.23 | 11.40 / 17.45 | 8.95 / 30.50 | 9.05 / 60.38 | 6.06 |

- **The solver decides the outcome.** Gurobi plans far better than HiGHS in the same time, so a "MILP" result means this solver for this long.
- **Colored 8×8 repeats the first finding:** Gurobi's better plans simulate far worse than HiGHS warm start, which stays close to Greedy's plan.
- **The bounds are consistent.** With the same robots, no method planned below a lower bound the solver proved. The best plans for these seeds are 10.85 s on the Tractor and 8.90 s on Colored 8×8.
- **This is a small sample:** 2 seeds each, one machine under load, and not a comparison in equal wall-clock time.

## Experiment 7: determinism

- **Across builds:** 30 runs (3 models, 5 methods, 2 seeds) were identical to the last digit after forcing a recompile with an unrelated source change.
- **Across platforms:** the same 30 runs on Ubuntu (WSL 2), from a clean clone, were identical to Windows, including simulated times, with the same source hash.
- **Limits:** a search that hits its time limit, and a MILP at its limit, are not exactly reproducible, because how far they get depends on the machine's speed. No other OS or CPU architecture was tested.

## Large models and crashes

Greedy runs that finish on this machine:

| Model | Parts | Robots | Seeds | Simulated [s] | Planned [s] | Simulation time [cpu s] |
|---|---|---|---|---|---|---|
| X-Wing | 309 | 50 | 2 | 177.55, 173.50 | 120.60, 120.65 | 652, 501 |
| Passenger Plane | 326 | 50 | 1 | 230.93 | 173.95 | 773 |
| Imperial Star Destroyer | 418 | 75 | 1 | 158.95 | 106.90 | 1,225 |
| King's Castle | 761 | 125 | 1 | 238.80 | 198.45 | 2,425 |

These runs show that large models can finish. They are not a comparison of methods.

**The dashboard's crash is fixed.** Runs in the dashboard engine died with exit code 0xC0000409 or a crash in `python37.dll`. The log shows why: `Fatal Python error: GC object already tracked`. The engine has a helper thread for flushing logs. A garbage collection it triggered could run PyCall's finalizers on that thread, while the simulation thread was inside Python. The helper thread now never runs finalizers. Before the fix, a real engine test lost 4 of its 5 simulation runs on the Tractor. After the fix, the same test passed on each repeat. This is a fix to the dashboard's worker: the notebook and scripts run with one thread and do not have this problem, but anyone starting extra Julia threads alongside a simulation should keep this in mind.

One experiment process stopped without any message (exit code 127) while the machine was short of memory. It finished normally when resumed, and it did not recur. Its cause was not established.

## What was not done

- **The planned 30 seeds on the medium models.** X-Wing mini reached 18 complete seeds, Imperial Shuttle 12 and AT-TE Walker 7.
- **Methods on large models.** Only Greedy, plus one warm-start run on X-Wing, which did not improve on Greedy in 120 s.
- **The largest models.** AT-AT, Heavily Nested and Saturn V (1,105 to 1,845 parts) were not attempted.
- **Equal wall-clock budgets.** Methods got equal evaluation budgets instead, and assignment times differ.
- **Any real-robot validation.** Velocity changes are instant by default, robots can swap positions, and scale is not physically consistent across models, so completion times are comparable only within one model.

## Reproducing

```bash
# Experiment 1, one model. Running the same command again resumes where it stopped.
METHODS=greedy,greedy_with_travel,most_complex_first,nearest_station_first,genetic_algorithm,particle_swarm,simulated_annealing,random_search,genetic_algorithm:top5
julia --project scripts/method_comparison.jl run --name exp1_tractor --models tractor --methods $METHODS --seeds 1:30 --limit 120

# Experiment 2
julia --project scripts/method_comparison.jl run --name exp2_robots --models tractor --methods greedy,genetic_algorithm --seeds 1:10 --robots 4,6,8,10,14,20
julia --project scripts/method_comparison.jl run --name exp2_placement --models tractor --methods greedy,genetic_algorithm --seeds 1:6 --placements 1,2,3,4,5

# Experiment 5
julia --project scripts/method_comparison.jl run --name exp5_budget --models tractor --methods genetic_algorithm,simulated_annealing --seeds 1:10 --budgets 1x2,5x2,10x10,25x40,100x100 --limit 600

# Experiment 6
julia --project scripts/method_comparison.jl run --name exp6_highs --models tractor,colored_8x8 --methods milp,milp_w_greedy_warm_start --seeds 1,2 --limit 300 --solver highs

# Tables
julia --project scripts/method_comparison.jl analyze results/experiments/exp1_tractor_<hash>.csv
julia --project scripts/method_comparison.jl analyze results/experiments/exp1_tractor_<hash>.csv "random_search 25x16"
```

A run takes about 1.5 GB of memory, and `rvo2` is not thread-safe, so run at most a few processes side by side, each on its own model. The file name holds the code's hash, so a change to `src/` or `Manifest.toml` starts a new file.
