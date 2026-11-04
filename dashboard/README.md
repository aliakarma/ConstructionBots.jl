# ConstructionLab

**Multi-Robot Construction Simulation & Research.** A local web dashboard for
[ConstructionBots.jl](../README.md): choose a LEGO model, a task-assignment method, a solver and a movement
profile, run the real simulator, watch the robots build the model in 3D, then compare and export the results.

ConstructionLab does not re-implement anything. Every run calls the simulator's public entry point
`ConstructionBots.run_lego_demo` in a separate Julia process that uses this repository's own `Project.toml` and
`Manifest.toml`.

---

## 1. One-time setup

ConstructionLab needs the same things as the simulator, plus a small Python environment for the web interface.

| What | Why | How |
|---|---|---|
| Julia 1.10 and the repository's packages | runs the simulator | [notebooks/SETUP.md](../notebooks/SETUP.md), step 1 |
| LDraw Parts Library | LEGO part shapes | [notebooks/SETUP.md](../notebooks/SETUP.md), step 2 |
| Python 3.7 with the **sisl fork of RVO2**, connected to Julia's PyCall | the simulator imports it for every run | [notebooks/SETUP.md](../notebooks/SETUP.md), step 3 |
| Python 3.11+ for the dashboard | runs the web interface | below |
| Gurobi licence (optional) | only for the Gurobi solver | section 7 |

The dashboard's Python and the Python that Julia uses for RVO2 are **two different Pythons**. Nothing in the
dashboard's environment changes PyCall's configuration.

**Install the dashboard (Windows, PowerShell, from the repository folder):**

```powershell
cd dashboard
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

**macOS / Linux:**

```sh
cd dashboard
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Julia is found automatically: the dashboard looks for a juliaup installation of the Julia version recorded in
`Manifest.toml` (1.10.12 here), then for `julia` on the PATH. If Julia is somewhere else, set
`CONSTRUCTIONLAB_JULIA` to the full path of the `julia` executable before starting.

## 2. Start the dashboard

* **Windows:** double-click `dashboard\start_dashboard.bat` (it also performs the installation above the first
  time), or run from the `dashboard` folder:

  ```powershell
  .\.venv\Scripts\python.exe -m streamlit run app.py
  ```

* **macOS / Linux:** `sh dashboard/start_dashboard.sh`, or `.venv/bin/python -m streamlit run app.py` from the
  `dashboard` folder.

Then open <http://localhost:8501>. Start it from the `dashboard` folder so that its settings
(`.streamlit/config.toml`) apply. The dashboard listens on `localhost` only. To use another port, add
`--server.port 8600`. Stop it with Ctrl+C in its window; the simulation engine stops with it.

On first use, open **System diagnostics** and press **Run system checks** (about 10–60 s). Every required item
should read *Available*. Gurobi reads *Optional, unavailable* unless you have a licence.

## 3. Using it (no programming needed)

1. **New simulation:** the defaults (Tractor, 10 robots, Greedy, Recommended movement, seed 1) are a good first run.
   Press **Run simulation**.
2. Watch the run on the right: the current phase, completed construction tasks while robots move, and a **live 3D
   preview** that refreshes as the simulator saves snapshots. When the run finishes the full **replay** appears with
   play, pause, a time slider, speed, *Reset view* and *Full screen*.
3. **Change the robots:** under *Robots* choose *Custom number*.
4. **Change the assignment method:** heuristic rules (*Greedy*, *Most complex first*, *Nearest station first*),
   exact optimization (*MILP*, *Greedy + MILP warm start*) or metaheuristics (*Genetic algorithm*, *Particle swarm*,
   *Simulated annealing*; set their *Iterations*, *Population* and *Time limit*).
5. **Change the solver** (MILP methods only): *HiGHS* (free, recommended), *GLPK* (free; not with warm start), or
   *Gurobi* (licence needed). Set the *Optimizer time limit*.
6. **Change movement:** pick a movement profile. Profiles that switch collision avoidance off show a safety note.
7. **Compare fairly:** switch to **Comparison study**, choose the factor to vary (assignment, solver, movement,
   robots, or repeated seeds), and the seeds. Every option runs with the same seeds and the same other settings.
8. **Compare experiments** finds comparable runs automatically and shows dot plots of the simulated completion time
   and of computer time, plus summary tables. **Analytics** gives per-model overviews.
9. **Export:** *Download … (CSV)* buttons on History and Compare, or *Save … to exports* (new file in
   `results/dashboard/exports/`, never overwriting).
10. **Troubleshooting:** see the *Help & about* page and section 8 below.

The first run after starting the dashboard takes about two minutes because Julia loads and compiles the simulator.
Later runs reuse the running engine and start immediately.

## 4. How it works

```
 Browser ──▶ Streamlit app (dashboard/app.py, views/*)            one Python process, localhost only
               │  validates settings (simulation/validation.py)
               │  writes results/dashboard/runs/<run_id>/config.toml + a job file
               ▼
             Engine manager (simulation/engine.py) ──launches──▶ Julia engine: simulation/julia_worker.jl serve
               │  queue · one run at a time · timeouts · cancel        (--project=<repo>, --threads=2)
               │                                                       calls ConstructionBots.run_lego_demo(...)
               │                                                       writes logs, stats.toml, animation, result.toml
               ▼
             Viewer server (simulation/artifact_server.py) ──▶ player page + the run's MeshCat animation file
```

* **Engine.** A persistent Julia process, so the 1–2 minute compile cost is paid once per session rather than once
  per run. It runs one job at a time. Cancelling or timing out a run stops the engine process (Julia cannot safely
  abort a running computation), and the next run starts a fresh engine. A Windows Job Object and a parent-process
  watchdog make sure the engine never outlives the dashboard.
* **Progress.** Phases come from the simulator's own console messages. While robots move, the progress bar is the
  simulator's own count of completed schedule tasks (`n_closed` of `n_total`). No percentage is invented for the
  other phases.
* **Viewer.** The simulator saves self-contained MeshCat HTML files. The viewer server (127.0.0.1, random port,
  GET only, strict file-name patterns) shows them inside a player page with its own controls. The live preview uses
  the simulator's `save_animation_along_the_way` snapshots. It is not a continuous stream: the simulation loop never
  yields to MeshCat's WebSocket server, so a live WebSocket connection cannot be served reliably while it computes.
* **Diagnostics.** `julia_worker.jl check` tests the Julia side; `julia_worker.jl registry` reads the model registry
  from `src/project_params.jl`. Neither changes anything.

## 5. Where results go

Everything is written under `results/dashboard/`, which is already ignored by Git:

```
results/dashboard/
├── runs/<run_id>/
│   ├── config.toml            settings, resolved values and the exact run_lego_demo keyword arguments
│   ├── status.toml            queued / running / success / incomplete / failed / rejected / canceled / timed_out / interrupted
│   ├── result.toml            metrics parsed from the simulator's statistics, software versions, flags
│   ├── simulator_stdout.log   simulator console output, including the MILP solver log
│   ├── simulator_stderr.log   progress meter and warnings
│   ├── error.txt              error and stack trace (failed runs only)
│   └── simulator_output/<method>_<flags>/<time>_stats.toml and <time>_visualization.html (the simulator's own files),
│       and simulator_output/variable_dump/ when a run got stuck (debugging dump)
├── exports/                   CSV files saved from the dashboard (never overwritten)
├── deleted_runs/              runs removed from the history (kept, not erased)
├── engine/                    engine logs and job inbox
└── cache/                     model registry and diagnostics results
```

Run folders are never reused. A run's status is written only after all its files are complete. Failed and
incomplete runs keep their logs and are shown as such: they are never averaged in or plotted as zeros.

## 6. Settings reference

| Dashboard setting | `run_lego_demo` argument |
|---|---|
| Model | `ldraw_file`, `project_name`, `model_scale` from `src/project_params.jl` |
| Number of robots | `num_robots` (1–500) |
| Random seed | `rng = MersenneTwister(seed)`. In this version it sets the robots' start positions. The worker also seeds Julia's global RNG with the same value. |
| Assignment method | `assignment_mode` = `:greedy` / `:greedy_with_travel` / `:most_complex_first` / `:nearest_station_first` / `:milp` / `:milp_w_greedy_warm_start` / `:genetic_algorithm` / `:particle_swarm` / `:simulated_annealing` / `:random_search` |
| Solver | `milp_optimizer` = `:highs` / `:glpk` / `:gurobi` (GLPK + warm start is rejected, as in `src/full_demo.jl`) |
| Optimizer / search time limit | `optimizer_time_limit` (s), used by the MILP methods and the metaheuristics |
| Iterations, Population | `metaheuristic_iterations`, `metaheuristic_population` (metaheuristics only) |
| Movement profile | `rvo_flag`, `tangent_bug_flag`, `dispersion_flag` |
| Save 3D animation / Smooth | `save_animation`, `update_anim_at_every_step`, `anim_active_agents`, `anim_active_areas` |
| Live preview | `save_animation_along_the_way`, `save_anim_interval`, `process_updates_interval` |
| Maximum steps / without progress | `max_steps`, `max_num_iters_no_progress` |
| Always | `open_animation_at_end=false`, `write_results=true`, `overwrite_results=false`, `look_for_previous_milp_solution=false`, `save_milp_solution=false` |

Large and very large models (300+ parts) need an explicit confirmation. There is no wall-clock limit by default, so a
run finishes however long it takes. Set a *Wall-clock limit* (1 to 10,080 minutes) only if you want the dashboard to
stop a run that is taking too long; a run stopped this way ends as `timed_out` and keeps its partial output.

## 7. Gurobi (optional)

Gurobi is never required: HiGHS and GLPK are installed with the project. Gurobi needs **your own** licence (free
academic licences exist; see [notebooks/SETUP.md](../notebooks/SETUP.md), "Optional: Gurobi"). The dashboard checks
the licence before a Gurobi run. Without a valid licence the run is **rejected**. It is never silently switched to
another solver. Licence files are never read, copied or displayed by the dashboard. Diagnostics show only Gurobi's
error code.

## 8. Troubleshooting

| Symptom | What to do |
|---|---|
| "Julia was not found" | Install Julia 1.10 with juliaup, or set `CONSTRUCTIONLAB_JULIA`. |
| "The engine failed to start" | System diagnostics → Run system checks; read the engine log shown there. |
| RVO2 missing | Install the sisl fork into the Python that PyCall uses ([notebooks/SETUP.md](../notebooks/SETUP.md), step 3). |
| LDraw library missing | Download the complete library to `Documents/ldraw`, or set `CONSTRUCTIONLAB_LDRAW_DIR`. |
| "No valid task assignment exists" | Too few robots for the model's largest transport team. Use more robots. |
| Run is *Incomplete* | Robots stopped making progress. Try the Recommended movement profile or raise *Maximum steps without progress*. |
| "Another ConstructionLab dashboard is using this results folder" | Only one dashboard may run simulations at a time. Close the other one, or delete `results/dashboard/engine/owner.toml` if none is running. |

Environment variables (all optional): `CONSTRUCTIONLAB_JULIA` (Julia executable), `CONSTRUCTIONLAB_LDRAW_DIR`
(LDraw library), `CONSTRUCTIONLAB_ENGINE_IDLE_MIN` (stop an idle engine after this many minutes, default 60),
`CONSTRUCTIONLAB_RESULTS_DIR` (alternative results folder; used by the tests).

## 9. Tests

```powershell
cd dashboard
.\.venv\Scripts\python.exe -m pytest
```

These are unit and interface tests: settings validation, run records and CSV export, comparison logic, viewer-server
path safety, engine queueing and ownership, and a render test of every page with Streamlit's AppTest. They use
temporary folders and do not start Julia.

`tests/test_real_simulation.py` runs real simulations through the real engine and worker, then renders the pages from
those records. It needs Julia, the LDraw library and rvo2, and takes several minutes, so it runs only on request:

```powershell
$env:CONSTRUCTIONLAB_REAL_TESTS = "1"; .\.venv\Scripts\python.exe -m pytest tests/test_real_simulation.py
```

## 10. Limitations

* One simulation runs at a time (others wait in the queue).
* The live preview refreshes when the simulator saves a snapshot, not continuously.
* Computer-time measurements include one-time compilation for the first run of each kind in an engine session
  (flagged in every table). Use *Warm up first*, which studies enable by default, for clean timings.
* MILP runs with a time limit are not deterministic across repeated runs.
* Uploading custom LDraw models is not supported. The model list is the repository's registry.
* Light theme only.
