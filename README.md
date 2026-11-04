# ConstructionBots.jl

**An open-source multi-robot manufacturing simulator for testing multi-robot assembly planning algorithms.**

[![CI](https://github.com/aliakarma/ConstructionBots.jl/actions/workflows/ci.yml/badge.svg)](https://github.com/aliakarma/ConstructionBots.jl/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Julia 1.10](https://img.shields.io/badge/Julia-1.10-9558B2?logo=julia&logoColor=white)](https://julialang.org/)
[![Open the Experiment Lab notebook](https://img.shields.io/badge/Notebook-Experiment%20Lab-F37626?logo=jupyter&logoColor=white)](notebooks/ConstructionBots_Experiment_Lab.ipynb)
[![Paper (arXiv)](https://img.shields.io/badge/Paper-arXiv-B31B1B?logo=arxiv&logoColor=white)](https://arxiv.org/abs/2311.00192)
[![Paper (RAS)](https://img.shields.io/badge/Paper-RAS-blue)](https://www.sciencedirect.com/science/article/abs/pii/S0921889025002763)

![ConstructionBots.jl overview](media/constructionbots_overviw.png)

## Contents

- [Overview](#overview)
- [About this fork](#about-this-fork)
- [Quick start](#quick-start)
- [Installation](#installation)
- [Usage](#usage)
  - [Experiment Lab notebook](#experiment-lab-notebook)
  - [Demo script](#demo-script)
  - [What a run reports](#what-a-run-reports)
  - [Batch comparison runner](#batch-comparison-runner)
  - [ConstructionLab dashboard](#constructionlab-dashboard)
- [Hosted demos (upstream)](#hosted-demos-upstream)
- [Repository structure](#repository-structure)
- [Testing](#testing)
- [Results and limitations](#results-and-limitations)
- [Troubleshooting](#troubleshooting)
- [Citation](#citation)
- [License](#license)

## Overview

ConstructionBots.jl is an open-source multi-robot manufacturing simulator designed to test algorithms for multi-robot assembly planning. It approaches assembly planning at a higher level of abstraction: it addresses task planning and transit planning, and abstracts away the kino-dynamic details of piecing together assemblies. The problems it addresses and simulates are:

- **Transport team configuration:** How many robots are needed, and how should they be positioned when transporting a particular payload?
- **Spatial layout of the construction site:** Where will each assembly be built, and where will the components of those assemblies be delivered?
- **Sequential task allocation and team forming:** Which robots will collect and deliver which payloads? There are generally far more payloads than robots, so individual robots usually have to transport several payloads in sequence.
- **Collision avoidance with heterogeneous agent geometry and dynamics:** How must laden and unladen robots and robot teams move, subject to motion constraints that depend on the payload size and team configuration, to avoid collisions with other robots and with the active construction sites?

LEGO models are used to evaluate the algorithms. They provide a convenient framework for defining large assemblies that are composed of smaller assemblies in addition to individual parts. The assemblies are defined with the LDraw file specification, an open-source format for describing LEGO bricks and models.

## About this fork

> [!NOTE]
> This repository is a fork of [sisl/ConstructionBots.jl](https://github.com/sisl/ConstructionBots.jl) by Kyle Brown, Dylan M. Asmar, Mac Schwager and Mykel J. Kochenderfer (MIT licence). It adds:
>
> - more task-assignment methods (`src/assignment_algorithms.jl`): Greedy with travel, most complex first, nearest station first, and the genetic algorithm, particle swarm and simulated annealing metaheuristics, with random search as their control;
> - a safety record with every run, a code version with every result, and results that do not change when the package is recompiled;
> - fixes for Windows and for animations that recorded no movement;
> - an experiment notebook ([`notebooks/`](notebooks/NOTEBOOK_USER_GUIDE.md)), a dashboard ([`dashboard/`](dashboard/README.md)) and a batch runner for controlled comparisons ([`scripts/method_comparison.jl`](scripts/method_comparison.jl)).
>
> The published paper's claims and the hosted demos belong to the upstream project. Their numbers were not made with this fork. Results of this fork's methods are in [`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md), with what they do and do not show.

## Quick start

The shortest route to a first result is the **Experiment Lab notebook**:

1. Complete the [installation](#installation) once.
2. Open [`notebooks/ConstructionBots_Experiment_Lab.ipynb`](notebooks/ConstructionBots_Experiment_Lab.ipynb) in Jupyter or VS Code (GitHub also shows it in the browser, read-only).
3. Run the cells from top to bottom. Every line of the Setup table should read **OK**.

Prefer a script? After installation, run the default demo from the Julia REPL:

```julia
include("scripts/demos.jl")
```

Prefer a point-and-click interface? Start the [dashboard](#constructionlab-dashboard).

## Installation

| Requirement | Needed for | Where to get it |
| --- | --- | --- |
| Julia 1.10 and the repository's packages | everything | [Julia project](#1-julia-project) |
| LDraw Parts Library | part geometry, all features | [LDraw parts library](#2-ldraw-parts-library) |
| Python 3.7 with the sisl fork of RVO2, connected to Julia's PyCall | every run, even with RVO2 switched off | [RVO2](#3-rvo2) |
| Python 3.11+ | the dashboard only | [ConstructionLab dashboard](#constructionlab-dashboard) |
| Gurobi licence | only the MILP with `milp_optimizer = :gurobi` | [`notebooks/SETUP.md`](notebooks/SETUP.md#optional-gurobi) |

The Gurobi Julia package installs without a licence. HiGHS and GLPK are free and need nothing extra.

> [!TIP]
> [`notebooks/SETUP.md`](notebooks/SETUP.md) is a step-by-step installation guide written for Windows 10/11, with notes for macOS and Linux. On Linux, [`scripts/setup_rvo2.sh`](scripts/setup_rvo2.sh) installs RVO2 and the LDraw library; it is what CI runs.

### 1. Julia project

Clone the repository and instantiate the environment. `Manifest.toml` pins the exact package versions, so a clone gets the same versions the recorded results used.

```bash
git clone https://github.com/aliakarma/ConstructionBots.jl.git
cd ConstructionBots.jl
julia --project -e 'using Pkg; Pkg.instantiate(); Pkg.build()'
```

### 2. LDraw parts library

Individual part geometry is needed for all features. Download the library from the [LDraw Parts Library](https://library.ldraw.org/updates?latest) (complete library: about 80 MB zipped, 450 MB unzipped) and unzip it.

The default path assumed by LDrawParser is `joinpath(homedir(), "Documents/ldraw")`. If you placed the library elsewhere, change the path with `set_part_library_dir!`.

The `LDraw_files/` folder of this repository holds the LEGO model files (`.mpd`) used by the simulator. It is not the parts library.

### 3. RVO2

The RVO2 library is used for collision avoidance. ConstructionBots uses a Python API to interact with it, and this step is required even if you do not plan to use RVO. The modified version of RVO2 that integrates dynamic priorities is at [sisl/Python-RVO2](https://github.com/sisl/Python-RVO2).

**Linux:** run `bash scripts/setup_rvo2.sh` (see the tip above), or follow the manual steps below.

**Windows:** follow [`notebooks/SETUP.md`](notebooks/SETUP.md), step 3.

**Manual steps (Linux/macOS):**

```bash
conda create -n lego_rvo2 python=3.7 anaconda
conda activate lego_rvo2
conda install pip
pip install cython==0.29.36
git clone https://github.com/sisl/Python-RVO2.git
cd Python-RVO2
python setup.py build
python setup.py install
```

Then point PyCall at that environment. In the Julia REPL:

```julia
ENV["PYTHON"] = "path/to/lego_rvo2/bin/python3.7" # e.g. ~/miniconda3/envs/lego_rvo2/bin/python3.7
using Pkg
Pkg.build("PyCall")
```

Restart Julia and check the installation:

```julia
using PyCall
rvo = pyimport("rvo2")
```

## Usage

### Experiment Lab notebook

[`notebooks/ConstructionBots_Experiment_Lab.ipynb`](notebooks/ConstructionBots_Experiment_Lab.ipynb) is a no-code interface to the simulator. Change values only in the cells marked **EDIT ME**, then run the cells from top to bottom. It lets you:

- check the environment (Section 2),
- choose a model, task-assignment algorithm, solver, movement profile and seed (Section 3),
- run one experiment and see the result table, the planned schedule, the search progress and a 3-D animation (Section 4),
- compare algorithms on the same problem (Section 5) and repeat them over several seeds with paired statistical tests (Section 6),
- export results to CSV (Section 7).

The first experiment after a restart takes 1–3 minutes because Julia compiles the code. See [`notebooks/NOTEBOOK_USER_GUIDE.md`](notebooks/NOTEBOOK_USER_GUIDE.md) for a longer guide.

### Demo script

```julia
include("scripts/demos.jl")
```

The default demo builds a tractor from LEGO model 10708, Green Creativity Box. The model has 20 individual pieces, organized into one final assembly (the tractor) and seven subassemblies. The demo uses 10 robots with all three collision avoidance algorithms on (RVO, Dispersion and Tangent Bug), and it should open an interactive visualization of the assembly process in your browser. Change the parameters in [`scripts/demos.jl`](scripts/demos.jl) to configure it.

The main function is `run_lego_demo` in [`src/full_demo.jl`](src/full_demo.jl). Its docstring lists every option.

If `update_anim_at_every_step` is not set to `true`, the animation only updates when nodes in the schedule complete. This is faster, but entities then take straight paths between updates, so it can look as if collisions occur. To see collision avoidance with no missed steps, set it to `true`; processing time increases considerably.

![Tractor project, view a](media/tractor_demo_a.png)
![Tractor project, view b](media/tractor_demo_b.png)
![Tractor project, view c](media/tractor_demo_c.png)
![Tractor project, view d](media/tractor_demo_d.png)

### What a run reports

`run_lego_demo` returns `(env, stats)`. With `write_results=true` it writes `stats` to `<results_path>/<method>_<flags>/<date>_stats.toml`. Nothing is written outside `results_path`.

| Keys | Meaning |
| --- | --- |
| `Makespan`, `OptimisticMakespan` | Simulated and planned completion time, in simulated seconds. Lower is better. `Makespan = Inf` means the project did not finish. |
| `RobotMinGap`, `RobotOverlapSteps`, `MinGap`, `OverlapSteps`, `PositionSwaps`, `MaxSpeed` | Safety record. The makespan cannot see overlaps or teleports, so report these with it. A negative gap means two agents overlapped. |
| `TerminationStatus`, `ObjectiveValue`, `ObjectiveBound`, `RelativeGap` | How far a MILP solver got. A MILP result means "this solver for this long". |
| `SearchHistory`, `SearchEvaluations`, `SearchTimedOut`, `SearchKeptGreedy` | What a metaheuristic did. |
| `SourceHash`, `GitCommit`, `GitDirty` | The code that produced the result. Compare only results with the same hash. |
| `Completed` | `false` in a stats file means the run crashed or is still going. |

> [!WARNING]
> The simulator abstracts physics, and this affects what you can conclude. Velocity changes are instant unless you set `max_acceleration`, robots can swap positions instantly, and the top speed is 4 m/s whatever the model's scale. Completion times are comparable within one model, not across models, and have not been calibrated against real robots.

### Batch comparison runner

[`scripts/method_comparison.jl`](scripts/method_comparison.jl) runs controlled, paired comparisons over models and seeds.

```bash
julia --project scripts/method_comparison.jl run --name mine --models tractor --seeds 1:30   # paired runs, resumable
julia --project scripts/method_comparison.jl analyze results/experiments/mine_<hash>.csv     # tables with paired tests
```

Replace `<hash>` with the code hash in the name of the CSV file that the `run` command wrote. See [`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md) for the experiments run so far and how to reproduce them.

### ConstructionLab dashboard

[`dashboard/`](dashboard/README.md) contains ConstructionLab, a local web dashboard. You choose a LEGO model, an assignment method, a solver and a movement profile, run the real simulator, watch the robots build the model in 3D, and then compare and export results. It calls `ConstructionBots.run_lego_demo` in a separate Julia process that uses this repository's `Project.toml` and `Manifest.toml`; it does not re-implement the simulator.

#### Set up the dashboard

The dashboard needs everything from the [installation](#installation) above (Julia project, LDraw library, RVO2), plus a Python 3.11+ environment for the web interface. This is a different Python from the one PyCall uses for RVO2, and it does not change PyCall's configuration.

Windows (PowerShell, from the repository folder):

```powershell
cd dashboard
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

macOS / Linux:

```bash
cd dashboard
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Julia is found automatically (a juliaup installation of the version recorded in `Manifest.toml`, then `julia` on the PATH). If Julia is elsewhere, set `CONSTRUCTIONLAB_JULIA` to the full path of the `julia` executable before starting.

#### Start the dashboard

Start it from the `dashboard` folder so that its settings (`.streamlit/config.toml`) apply.

- **Windows:** double-click `dashboard\start_dashboard.bat` (it also performs the setup above the first time), or run from the `dashboard` folder:

  ```powershell
  .\.venv\Scripts\python.exe -m streamlit run app.py
  ```

- **macOS / Linux:** run `sh dashboard/start_dashboard.sh`, or run from the `dashboard` folder:

  ```bash
  .venv/bin/python -m streamlit run app.py
  ```

Then open <http://localhost:8501>. The dashboard listens on `localhost` only. To use another port, add `--server.port 8600`. Stop it with Ctrl+C in its window; the simulation engine stops with it.

On first use, open **System diagnostics** and press **Run system checks** (about 10–60 s). Every required item should read *Available*. Gurobi reads *Optional, unavailable* unless you have a licence.

#### Use the dashboard

1. **New simulation:** the defaults (Tractor, 10 robots, Greedy, Recommended movement, seed 1) are a good first run. Press **Run simulation**.
2. **Watch the run:** the right-hand side shows the current phase, completed construction tasks, and a live 3D preview that refreshes as the simulator saves snapshots. When the run finishes, a full replay appears with play, pause, a time slider, speed, *Reset view* and *Full screen*.
3. **Change the robots:** under *Robots* choose *Custom number*.
4. **Change the assignment method:** heuristic rules (*Greedy*, *Most complex first*, *Nearest station first*), exact optimization (*MILP*, *Greedy + MILP warm start*) or metaheuristics (*Genetic algorithm*, *Particle swarm*, *Simulated annealing*, with their *Iterations*, *Population* and *Time limit*).
5. **Change the solver** (MILP methods only): *HiGHS* (free, recommended), *GLPK* (free; not with warm start) or *Gurobi* (licence needed). Set the *Optimizer time limit*.
6. **Change movement:** pick a movement profile. Profiles that switch collision avoidance off show a safety note.
7. **Compare fairly:** switch to **Comparison study**, choose the factor to vary (assignment, solver, movement, robots, or repeated seeds) and the seeds. Every option runs with the same seeds and the same other settings.
8. **Compare experiments** finds comparable runs automatically and shows dot plots of simulated completion time and computer time, with summary tables. **Analytics** gives per-model overviews.
9. **Export:** use the *Download … (CSV)* buttons on History and Compare, or *Save … to exports* (a new file in `results/dashboard/exports/`, never overwriting).

The first run after starting the dashboard takes about two minutes because Julia loads and compiles the simulator. Later runs reuse the running engine and start immediately. One simulation runs at a time; others wait in the queue.

Everything the dashboard writes goes under `results/dashboard/` (ignored by Git): one folder per run in `runs/<run_id>/` with its settings, status, result, logs and animation, plus `exports/` for CSV files. See [`dashboard/README.md`](dashboard/README.md) for the settings reference, environment variables, troubleshooting and limitations.

## Hosted demos (upstream)

These demos are hosted by the upstream project. Their numbers were not made with this fork.

| Project | Allocation algorithm | RVO | Dispersion | Tangent Bug | Visualization |
| --- | --- | :---: | :---: | :---: | :---: |
| Tractor | Greedy | Yes | Yes | Yes | [Link](https://sisl.github.io/ConstructionBots.jl/stable/tractor_greedy_RVO_Dispersion_TangentBug_visualization.html) |
| Tractor | MILP | Yes | Yes | Yes | [Link](https://sisl.github.io/ConstructionBots.jl/stable/tractor_milp_RVO_Dispersion_TangentBug_visualization.html) |
| AT-TE Walker | MILP + Greedy | Yes | Yes | Yes | [Link](https://sisl.github.io/ConstructionBots.jl/stable/atte-walker_milp-ws_RVO_Dispersion_TangentBug_visualization.html) |
| X-Wing | Greedy | No | No | No | [Link](https://sisl.github.io/ConstructionBots.jl/stable/x-wing_greedy_no-RVO_no-Dispersion_no-TangentBug_visualization.html) |
| Saturn V | Greedy | Yes | Yes | Yes | [Link](https://www.youtube.com/watch?v=1hJD7NCfjZU) |

[![Saturn V demo (RVO + Dispersion + Tangent Bug)](https://img.youtube.com/vi/1hJD7NCfjZU/0.jpg)](https://www.youtube.com/watch?v=1hJD7NCfjZU)

## Repository structure

| Path | Contents |
| --- | --- |
| `src/` | The simulator, including `full_demo.jl` (`run_lego_demo`) and `assignment_algorithms.jl` |
| `scripts/` | `demos.jl`, `method_comparison.jl`, `setup_rvo2.sh` and helper scripts |
| `notebooks/` | The Experiment Lab notebook, its helper code, `SETUP.md` and `NOTEBOOK_USER_GUIDE.md` |
| `dashboard/` | ConstructionLab, the local web dashboard (Python and Streamlit) |
| `LDraw_files/` | LEGO model files (`.mpd`) |
| `test/` | Julia test suite (`runtests.jl` and fixtures) |
| `docs/` | `EXPERIMENTS.md`, `AUDIT_STATUS.md` and the recorded experiment data |
| `media/` | Images used in this README |
| `results/` | Output folder for runs (created by runs) |

## Testing

```bash
julia --project -e 'using Pkg; Pkg.test()'    # Julia test suite
cd dashboard && python -m pytest              # dashboard test suite
```

The dashboard tests use temporary folders and do not start Julia. Run them with the dashboard's Python environment (see [Set up the dashboard](#set-up-the-dashboard)). The Julia tests use the same Julia project, LDraw library and RVO2 module as a normal run.

## Results and limitations

- [`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md) lists the experiments run with this fork's methods, how to reproduce them, and what they do and do not show.
- [`docs/AUDIT_STATUS.md`](docs/AUDIT_STATUS.md) lists the known limitations left after the forensic audit.
- Results from before the audit fixes (with no `SourceHash`) are not comparable with current ones. Compare only results with the same `SourceHash`.

## Troubleshooting

| Problem | What to do |
| --- | --- |
| `rvo2` cannot be imported | Install the sisl fork into the Python that PyCall uses, then rebuild PyCall ([RVO2](#3-rvo2)). It is needed even with RVO2 switched off. |
| The LDraw parts library is not found | Place it in `Documents/ldraw`, or change the path with `set_part_library_dir!`. |
| Gurobi reports no licence | Use HiGHS or GLPK, or obtain your own licence ([`notebooks/SETUP.md`](notebooks/SETUP.md#optional-gurobi)). |
| The animation shows robots passing through each other | The animation only updates when tasks finish. Set `update_anim_at_every_step` to `true` (slower), or `SMOOTH_ANIMATION = true` in the notebook. |
| The first run takes minutes | One-time compilation after every restart. Later runs are fast. |

More cases are covered in Section 8 of the notebook, in [`notebooks/SETUP.md`](notebooks/SETUP.md) and in [`dashboard/README.md`](dashboard/README.md#8-troubleshooting).

## Citation

This simulator and the paper describing it come from the upstream project. If you use ConstructionBots.jl, please cite:

```bibtex
@article{Brown2023Assembly,
  title = {Large-Scale Multi-Robot Assembly Planning for Autonomous Manufacturing},
  author = {Kyle Brown and Dylan M. Asmar and Mac Schwager and Mykel J. Kochenderfer},
  journal = {Robotics and Autonomous Systems},
  volume = {194},
  pages = {105179},
  year = {2025},
  doi = {https://doi.org/10.1016/j.robot.2025.105179}
}
```

## License

Released under the MIT License. See [`LICENSE`](LICENSE). LDraw parts are distributed separately by [LDraw.org](https://www.ldraw.org/) under their own licence; LEGO® is a trademark of the LEGO Group, which does not endorse this project.
