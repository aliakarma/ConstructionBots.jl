# Status of the forensic audit findings

Outcome of each finding from the forensic audit of 2026-11-03 (5/10, Major Revision). **Fixed** means the fix is in the code and was verified. **Partly** means what remains is listed. Measured results are in [EXPERIMENTS.md](EXPERIMENTS.md).

## Critical

| # | Finding | Status | What changed, and how it was verified |
|---|---|---|---|
| 1 | Work not under version control | Fixed locally | Committed on branch `fork-work`. **Not pushed yet**, so it is still only on this machine. |
| 2 | Results change between builds | Fixed | IDs hash on their type's name rather than the module's build id. 30 of 30 runs identical across builds, and across Windows and Linux. Every run records `SourceHash`, and the tools never compare or reuse across hashes. |
| 3 | No working test gate | Fixed | 143 Julia tests in place of 17 assertion lines, and 60 dashboard tests plus a real-simulation test. All Julia tests pass through `Pkg.test()` from a clean Linux clone, using CI's steps. The CI workflow itself has not run on GitHub yet. |
| 4 | Code crashes on Windows; results relied on runtime patches | Fixed | Both fixes moved into `src/`; both patches deleted. A saved animation decodes to 64 moving objects. |
| 5 | Headline metric blind to safety | Fixed | Every run records gaps, overlap steps, swaps and top speed, shown beside makespan in the notebook and dashboard. **The overlaps themselves still occur**, and their cause was not established. |
| 6 | Metaheuristics optimize a proxy; benefit unproven | Fixed, with limits | Claims rewritten to rest on simulated results. `simulate_top_plans` chooses by simulating, and is never slower than Greedy. Tested with up to 30 paired seeds on 6 models. Seeds on 3 of the models and all large-model comparisons fall short of the plan. |

## Moderate

| # | Finding | Status | Notes |
|---|---|---|---|
| 1 | MILP never solved; ranking depends on solver | Partly | Status, bound and gap are recorded and shown. Experiment 6 ran both solvers for 300 s. **Still no run proves optimality.** Whether Greedy and the MILP enforce the build order differently was not investigated. |
| 2 | "Seeded with Greedy" hid a decoder change | Fixed | Greedy's real schedule is a candidate, so a plan is never worse than Greedy's. `:greedy_with_travel` and `:random_search` separate the effects. |
| 3 | Comparison pipeline could mislead | Fixed | Budgets are separate levels, repeats count once, and success rates, confidence intervals and Holm-corrected paired tests are reported, in both the notebook and the dashboard. |
| 4 | Narrow coverage | Partly | 6 models in the comparison. Part placement and robot count were varied on the Tractor only. |
| 5 | Robustness and scale not demonstrated | Partly | The dashboard crash was found and fixed. Too few robots gives a clear error. Models up to 418 parts finish. **Plain searches can still deadlock** (12 of 120 on Colored 8×8), and stuck runs are reported as incomplete. Most of the largest models were not attempted. |
| 6 | Limited simulation realism | Partly | Swaps counted, units documented, optional `max_acceleration` added (it limits commanded velocity only, and RVO can still change velocity faster). **Default physics deliberately unchanged**, so results stay comparable with the paper. No real-world calibration exists. |
| 7 | Environment not reproducible from a clone | Partly | `Manifest.toml` committed, Julia bound raised to 1.10, setup script tested on Linux. **Not done:** no container, `rvo2` is still needed with RVO off, Python 3.7 is still required, and Gurobi stays a dependency (it needs no licence unless used, as the Linux test confirms). |
| 8 | Publishing risk in the notebook | Fixed | Outputs cleared (44.5 MB to about 56 KB), no personal paths, and CI rejects a notebook with outputs. A copy with the old outputs is at `results/audit/backup/`. CI checks this in place of `nbstripout`. |
| 9 | Side effects beyond the results folder | Partly | Dumps stay in `results_path`, the caller's logger and arguments are untouched, nothing is written with `write_results=false`, and stats files are atomic with a `Completed` flag. **Module-level globals remain**; each run resets the ones it uses. |
| 10 | Fragile control flow and structure | Partly | `NoAssignmentError` replaces assertion and message matching, and validators are now enforced. `run_lego_demo` is split into helpers, but **its main function is still long**. |
| 11 | Documentation and fork identity out of date | Fixed | README, badges, docs target and guides corrected, upstream credited. The docs deploy is manual only. The upstream demo HTML files stay in `docs/src`, labelled as upstream's. |

## Minor

All fixed except one: `array_isapprox` stays in `test/runtests.jl`, the only place that uses it. CPU times from before this work still include compilation in some old records; the tools flag these.

## Missing experiments

| # | Experiment | Status |
|---|---|---|
| 1 | Powered comparison, 30 seeds, 6 models | Partly: 30 seeds on 3 models, 18, 12 and 7 on the others |
| 2 | Vary more than start positions | Done on the Tractor |
| 3 | Safety-adjusted results | Done with Experiment 1 |
| 4 | Search ablation | Done |
| 5 | Plan-to-simulation predictiveness | Done on the Tractor |
| 6 | Solved MILP baseline | Run, but nothing was solved to optimality |
| 7 | Cross-platform and cross-build determinism | Done on one Windows and one Linux machine |

## Not checked

- The published paper's claims: the paper is not in this repository.
- The CI workflow on GitHub itself, and any OS other than Windows 11 and Ubuntu under WSL 2.
- The dashboard in a real browser in this round. Pages were rendered with Streamlit's test harness, using real run records.
