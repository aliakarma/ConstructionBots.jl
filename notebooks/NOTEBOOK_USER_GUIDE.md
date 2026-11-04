# ConstructionBots Experiment Lab — User Guide

This guide is for lab members who want to run ConstructionBots experiments without programming.
Everything happens in one notebook: `notebooks/ConstructionBots_Experiment_Lab.ipynb`.
If the software is not installed yet on your computer, follow `notebooks/SETUP.md` first (once).

## Files

| File | Purpose | Do I edit it? |
|---|---|---|
| `ConstructionBots_Experiment_Lab.ipynb` | The notebook: settings, runs, tables, charts, export. | Only the settings cells. |
| `notebook_helpers.jl` | Translates the notebook's friendly settings into simulator arguments, checks them, runs experiments, saves and displays results. | No. |
| `SETUP.md` | One-time installation. | No. |
| `NOTEBOOK_USER_GUIDE.md` | This guide. | No. |

## Opening the notebook

1. Start VS Code and open the `ConstructionBots.jl` folder (*File → Open Folder…*).
2. In the Explorer, open `notebooks` → `ConstructionBots_Experiment_Lab.ipynb`.
3. Click **Select Kernel** (top right) → **Jupyter Kernel…** → **Julia 1.10**.
4. Click into the first code cell (Section 2, "SETUP") and press **Shift + Enter**. Continue cell by cell, or use
   **Run All** (the comparison in Section 5 then runs too; set `RUN_COMPARISON = false` if you do not want that).

To start over at any time: **Restart** (toolbar), then run from the top again. Saved results are never deleted.

## 1. Run the baseline experiment

Run Sections 2, 3 and 4 without changing anything. You get the **Tractor** model (20 parts) built by 10 robots
with the **Genetic algorithm** task assignment and the **Recommended** movement profile, seed 1. For the baseline, set
`ASSIGNMENT_METHOD = "Greedy"`. The first run after a restart takes 1–3 minutes (compilation); afterwards a Tractor run
takes a few seconds. Expected result for Greedy on the test computer: status **SUCCESS**, planned completion time
**14.88 s**, simulated completion time **22.75 s**, code version `1ce4205b64cd`. A different code version
can give a different number.

## 2. Change the model and the number of robots

In the **EXPERIMENT SETTINGS** cell:

```julia
MODEL            = "X-Wing (mini)"   # a name from the "Available models" table
NUMBER_OF_ROBOTS = 15                # or `nothing` for the model's default
```

Run the settings cell, the "check the settings" cell, and the run cell again.

* Names must be in double quotes; numbers must not.
* Large models are blocked unless you set `ALLOW_LARGE_MODELS = true` in the Advanced settings, because they can
  run for minutes to hours.
* Too few robots makes the problem impossible (some parts need teams of several robots). On the Tractor, 1–3 robots
  fail with "3 robots are too few: the largest transport team of tractor needs 4"; the default of 10 works.

## 3. Switch the assignment method

```julia
ASSIGNMENT_METHOD = "Particle swarm"   # or any of the ten below (short names "GA", "PSO", "SA" also work)
```

*Assignment* decides which robot fetches which part, and in which order. Ten methods in three families:

| Family | Methods | Idea |
|---|---|---|
| Heuristic rules | "Greedy", "Greedy with travel", "Most complex first", "Nearest station first" | A fixed rule picks the next task: earliest finish (Greedy, with or without counting earlier travel), largest robot team first, or the pick-up station the free robots reach soonest. Instant. |
| Exact optimization | "MILP", "Greedy + MILP warm start" | A mixed-integer linear program solved by HiGHS / GLPK / Gurobi, stopped at the time limit. The warm start gives Greedy's answer to the solver as its starting point. |
| Metaheuristics | "Genetic algorithm", "Particle swarm", "Simulated annealing", "Random search" | Search over task orders (one priority number per task, decoded with Greedy's rules and scored by the planned completion time). Start from Greedy's order and keep the best schedule found, so the plan is never worse than Greedy's. Random search is the control: the same budget, no search operators. |

The rules and metaheuristics are in `src/assignment_algorithms.jl` and run through `run_lego_demo` like the
original methods (`assignment_mode = :greedy_with_travel`, `:most_complex_first`, `:nearest_station_first`,
`:genetic_algorithm`, `:particle_swarm`, `:simulated_annealing`, `:random_search`).

A better plan does not guarantee a faster simulation, because the plan ignores traffic. Judge methods by the simulated
completion time over several seeds (Section 6 of the notebook).

## 4. Select a solver or a search budget

```julia
TIME_LIMIT_SECONDS = 60      # MILP solver or metaheuristic
SOLVER             = "HiGHS" # MILP only: or "GLPK", or "Gurobi"
SEARCH_ITERATIONS  = 25      # metaheuristics only
SEARCH_POPULATION  = 16      # metaheuristics only
```

A metaheuristic evaluates about `SEARCH_ITERATIONS × SEARCH_POPULATION` candidate schedules (400 by default, a few
seconds on the Tractor) and stops early at the time limit; its result says so if it did ("STOPPED AT THE TIME
LIMIT"). All of them get the same budget, so they can be compared fairly.

Only the two MILP methods use a solver. HiGHS is free and recommended. GLPK is free but cannot be combined with
the warm-start method (the notebook refuses this combination). Gurobi needs your own licence (see SETUP.md).
The optimizer stops at the time limit and uses its best answer so far, so a MILP result means "this solver for this
long", not the optimum. The result table shows the solver's status, gap and lower bound; report them with the limit.

## 5. Select a movement profile

```julia
MOVEMENT_PROFILE = "No Tangent Bug"
```

| Profile | RVO2 | Tangent Bug | Dispersion |
|---|---|---|---|
| Recommended | on | on | on |
| No RVO2 | off | on | on |
| No Tangent Bug | on | off | on |
| No Dispersion | on | on | off |
| No avoidance methods | off | off | off |
| Custom | `CUSTOM_RVO2` | `CUSTOM_TANGENT_BUG` | `CUSTOM_DISPERSION` |

Movement profiles decide **how robots move**, not who does which task. Change either the assignment method *or*
the movement profile in one comparison, not both. In this version of the code the dispersion adjustment only acts
while RVO2 is on; and no profile guarantees collision-free motion, so check the safety record of each run.

Switching avoidance **off** usually makes the completion time **shorter** (test computer, Tractor, seed 1:
Recommended 22.75 s, No avoidance methods 14.93 s). This is not better behaviour: the robots then ignore each other,
and the completion time does not penalize that. Judge movement profiles together with the safety columns: smallest
robot gap (negative means overlap), overlap steps and swaps.

## 6. Run a comparison

In Section 5, edit the **COMPARISON SETTINGS** cell and run the next cells. The default, `"Custom"`, runs the
algorithms listed in `ALGORITHMS_TO_COMPARE`:

```julia
COMPARISON_PRESET     = "Custom"
ALGORITHMS_TO_COMPARE = ["Greedy", "Most complex first", "Genetic algorithm", "Particle swarm"]
```

| Preset | Compares |
|---|---|
| `"Custom"` | The algorithms in `ALGORITHMS_TO_COMPARE` |
| `"A"` | Baseline only (1 run) |
| `"B"` | Greedy vs MILP vs Greedy + MILP warm start (HiGHS) |
| `"C"` | MILP with HiGHS vs GLPK vs Gurobi (Gurobi skipped without licence) |
| `"D"` | The 5 movement profiles with Greedy |
| `"E"` | Tractor with 6 / 10 / 14 robots, then X-Wing (mini) |
| `"F"` | The four heuristic rules |
| `"G"` | The metaheuristics and Random search, with Greedy and Greedy with travel as references (same budget for each) |
| `"H"` | All ten algorithms |

Progress is printed as "Run 2 of 3 …" with the status and elapsed time. To stop early, create an empty file called
`STOP` in the batch folder printed at the start, or press **Interrupt**. For more reliable conclusions, use
Section 6 (several matched seeds per configuration).

## 7. Inspect statistics and charts

* `show_visuals(LAST_RUN)` (Section 4) shows one run: the result table with units and explanations, the planned
  schedule (a Gantt chart with one row per robot), the search progress of a metaheuristic, and the 3-D animation.
  It works for any run, e.g. `show_visuals(COMPARISON_RESULTS[2])`.
* `show_comparison(COMPARISON_RESULTS)` (Section 5) shows one row per run (failures included) and charts of the
  completion time, planned completion time and assignment time (bars coloured by algorithm; runs that did not
  succeed have no bar and are labelled in red), the metaheuristics' search progress against the other algorithms'
  planned times, and all planned schedules on one time axis. The charts are saved as `.svg` in the batch folder.
* The single charts are also available on their own: `chart_metric`, `chart_convergence`, `chart_schedule`.
* `show_summary` (Section 6) gives the success rate, the mean with its 95 % confidence interval, the standard deviation,
  minimum and maximum, and the safety record over seeds.
* `show_paired` (Section 6) compares each configuration with Greedy seed by seed, with an effect size and a statistical
  test corrected for several comparisons. `show_plan_vs_simulation` shows whether better plans simulate faster.

**Simulated seconds** (completion time, planned completion time) describe the robots' world and are the main
result. **Computer seconds** (assignment, preparation, execution, total) describe how long your computer worked.

## 8. Export results

Section 7 writes a new time-stamped CSV to `results/notebook_lab/exports/` and checks it can be read back.
Every saved run is also appended to `results/notebook_lab/all_runs.csv`, and every comparison has its own
`summary.csv` in `results/notebook_lab/batches/<batch ID>/`. CSV files open directly in Excel. Empty cells mean
"not available" — they are never filled with zero.

## 9. View and find saved animations

With `SAVE_ANIMATION = true`, the run folder contains
`results/notebook_lab/runs/<run ID>/simulator_output/<…>/<date>_visualization.html`. The path is shown in the result
table ("Animation file"), together with how many objects move in it.

**In the notebook:** `show_visuals(LAST_RUN)` in Section 4 ends with `show_animation(LAST_RUN)`. It checks the file
(a table reports the number of moving objects; 0 means the file shows only the finished model), then shows a viewer
with *Play*, a time slider, speed and *Reset view*. Any run can be shown: `show_animation(COMPARISON_RESULTS[2])`,
or `show_animation("path/to/file_visualization.html")`. The animation is copied into the cell output (files up to
30 MB), so it shows in Jupyter, JupyterLab and VS Code, needs no server and survives a kernel restart; the saved
notebook grows by a few MB per animation, so *Clear All Outputs* before sharing it. Larger files, or
`show_animation(LAST_RUN; inline = false)`, are served by the notebook's Julia session at `http://127.0.0.1` (this
computer only) instead; after a kernel restart, run the cell again.

**Outside the notebook:** the file is self-contained (MeshCat writes its viewer program and all scene data into it;
no server or internet connection is needed). Drag it into a web browser, or set `OPEN_ANIMATION_IN_BROWSER = true`
in the animation cell. In that view, open *Animations* (right-hand panel) and press *play*; drag with the mouse to
rotate, scroll to zoom.

**Animations made by older versions of the code** show only the finished model; run those experiments again to get a
moving animation.

## 10. Troubleshoot a failed run

1. Read the status line: **FAILED**, **INCOMPLETE**, **REJECTED** (settings invalid, nothing ran), **SKIPPED**
   (e.g. Gurobi without licence) or **INTERRUPTED**.
2. Read the "status detail" and "error message" lines in the result table.
3. Look in the run folder: `simulator_log.txt` (everything the simulator printed) and, for failures, `error.txt`.
4. Check the Troubleshooting table in Section 8 of the notebook.
5. If something seems broken: Restart the kernel and run all cells from the top.

## Good experimental practice

* Change one kind of setting per comparison; keep model, robots, seed and limits fixed.
* Use matched seeds (Section 6): at least 10, and 30 for anything you publish. Report the number of seeds, the mean with
  its confidence interval, and the paired test. Do not generalize from one model.
* Report the safety record with every completion time: a faster run with overlapping robots is not a better one.
* Report the optimizer time limit and solver with every MILP result.
* Computer-time numbers depend on the computer and include compilation for runs marked
  `includes_one_time_compilation = true`; compare computer times only within one batch on one machine.
* The `effective_config.toml` in every run folder records the exact simulator arguments and software versions. Quote
  the `source_hash` of any number you report, and compare only runs with the same one.
* For batches over several models and many seeds, use `scripts/method_comparison.jl`.
