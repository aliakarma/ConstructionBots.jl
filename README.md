# ConstructionBots.jl

[![Build Status](https://github.com/aliakarma/ConstructionBots.jl/workflows/CI/badge.svg)](https://github.com/aliakarma/ConstructionBots.jl/actions)

![ConstructionBots.jl Overivew](media/constructionbots_overviw.png)

[arXiv](https://arxiv.org/abs/2311.00192)
[RAS](https://www.sciencedirect.com/science/article/abs/pii/S0921889025002763)

ConstructionBots.jl is an open-source multi-robot manufacturing simulator and is designed to test algorithms for multi-robot assembly planning. This system approaches multi-robot assembly planning from a higher level of abstraction and addresses task planning and transit planning but abstracts away the kino-dynamic details of piecing together assemblies. Problems addressed and simulated:
- **Transport Team configuration:** How many robots are needed and how should robots be positioned when transporting a particular payload?
- **Spatial layout of the construction site:** Where will each assembly be built, and where will the components of those assemblies be delivered?
- **Sequential task allocation and team forming:** Which robots will collect and deliver which payloads? Since there are generally far more payloads than robots, individual robots generally have to transport multiple payloads in sequence.
- **Collision avoidance with heterogeneous agent geometry and dynamics:** How must laden and unloaden robots and robot teams move, subject to motion constraints that depend on the payload size and team configuration, to avoid collision with other robots and the active construction sites in the environment?

ConstructionBots uses LEGO models to evaluate algorithms. LEGO models offer a convenient framework for defining large assemblies that are often composed of smaller assemblies in addition to individual parts. ConstructionBots uses assemblies that are defined using the LDraw file specification, an open-source tool for describing LEGO bricks and models.

> **About this fork.** This repository is a fork of [sisl/ConstructionBots.jl](https://github.com/sisl/ConstructionBots.jl) by Kyle Brown, Dylan M. Asmar, Mac Schwager and Mykel J. Kochenderfer (MIT licence). It adds:
> - more task-assignment methods (`src/assignment_algorithms.jl`): Greedy with travel, most complex first, nearest station first, and the genetic algorithm, particle swarm and simulated annealing metaheuristics with random search as their control;
> - a safety record with every run, a code version with every result, and results that do not change when the package is recompiled;
> - fixes for Windows and for animations that recorded no movement;
> - an experiment notebook ([`notebooks/`](notebooks/NOTEBOOK_USER_GUIDE.md)), a dashboard ([`dashboard/`](dashboard/README.md)) and a batch runner for controlled comparisons ([`scripts/method_comparison.jl`](scripts/method_comparison.jl)).
>
> The published paper's claims and the hosted demos below belong to the upstream project. Their numbers were not made with this fork. Results of this fork's methods are in [`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md), with what they do and do not show.

## Hosted Demos to View the Functionality of ConstructionBots
These demos are hosted by the upstream project.

| Project | Allocation Algorithm | RVO | Dispersion  | Tangent Bug | Visualization |
| --- | :---: | :---: | :---: | :---: | :---: |
| Tractor | Greedy | Yes | Yes | Yes | [Link](https://sisl.github.io/ConstructionBots.jl/stable/tractor_greedy_RVO_Dispersion_TangentBug_visualization.html) |
| Tractor | MILP | Yes | Yes | Yes | [Link](https://sisl.github.io/ConstructionBots.jl/stable/tractor_milp_RVO_Dispersion_TangentBug_visualization.html) |
| AT-TE Walker  | MILP + Greedy | Yes | Yes | Yes | [Link](https://sisl.github.io/ConstructionBots.jl/stable/atte-walker_milp-ws_RVO_Dispersion_TangentBug_visualization.html) |
| X-Wing  | Greedy | No | No | No | [Link](https://sisl.github.io/ConstructionBots.jl/stable/x-wing_greedy_no-RVO_no-Dispersion_no-TangentBug_visualization.html) |
| Saturn V  | Greedy | Yes | Yes | Yes | [Link](https://www.youtube.com/watch?v=1hJD7NCfjZU) |

#### Saturn V (RVO + Dispersion + Tangent Bug) Video
[![Saturn V demo](https://img.youtube.com/vi/1hJD7NCfjZU/0.jpg)](https://www.youtube.com/watch?v=1hJD7NCfjZU)

## Installation

### ConstructionBots
To interact with ConstructionBots, it is recommended you clone this repository and instantiate the environment. It needs Julia 1.10; `Manifest.toml` pins the exact package versions, so a clone gets the same versions the recorded results used.
```bash
git clone https://github.com/aliakarma/ConstructionBots.jl.git
cd ConstructionBots.jl
julia
```
```julia
julia> ] activate .
pkg> instantiate
pkg> build
```
The project depends on the Gurobi Julia package, which installs without a licence. You only need a [Gurobi licence](notebooks/SETUP.md#optional-gurobi) to run the MILP with `milp_optimizer = :gurobi`; HiGHS and GLPK are free and need nothing extra.

### LDraw Parts Library
Individual part geometry is needed for all features. The parts library can be downloaded from [LDraw™ Parts Library](https://library.ldraw.org/updates?latest). Place the unzipped library in your desired path. The default path assumed by LDrawParser is `joinpath(homedir(), "Documents/ldraw")`. It is recommended to download the complete library (~80 MB zipped, ~450 MB unzipped). If you did not place the parts library in the default path, you can change the path LDrawParser uses by the `set_part_library_dir!` command.

### RVO
The RVO2 library is used for collision avoidance. ConstructionBots uses a Python API to interact with RVO2 library. The modified version of RVO2 that integrates dynamic priorities can be found at https://github.com/sisl/Python-RVO2.

To install the RVO2 library:
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
Once you have the RVO2 library built, you need to set the path to the appropriate environment for PyCall to find the RVO2 library. In the Julia REPL, run the following:
```julia
julia> ENV["PYTHON"] = "path/to/lego_rvo2/bin/python3.7" # e.g. ~/miniconda3/envs/lego_rvo2/bin/python3.7
julia> using Pkg
julia> Pkg.build("PyCall")
```

Restart Julia and run the following to test the installation of the RVO2 library:
```julia
julia> using PyCall
julia> rvo = pyimport("rvo2")
```

Note: In the current build of ConstructionBots, this step is still required even if you do not plan to use RVO.

On Linux, [`scripts/setup_rvo2.sh`](scripts/setup_rvo2.sh) does these steps and downloads the LDraw library. It is what CI runs. On Windows, follow [`notebooks/SETUP.md`](notebooks/SETUP.md).

## Usage
This repository comes with demos to demonstrate the functionality of ConstructionBots. To run the demos, run the following in the Julia REPL:
```julia
julia> include("scripts/demos.jl")
```
The default demo is the a Tractor based on LEGO model 10708, Green Creativity Box. The tractor model has a total of 20 individual pieces, which are organized into one final assembly (the tractor) and seven subassemblies. The demo is configured to use 10 robots to assemble the tractor, with all three collision avoidance algorithms on (RVO, Dispersion and Tangent Bug), and it should open an interactive visualization of the assembly process in your browser. The demo can be configured by changing the parameters in [`demos.jl`](scripts/demos.jl). Examples of the simulation are shown below.
You can interact with an example from the tractor simulation [here](https://sisl.github.io/ConstructionBots.jl/stable/tractor_greedy_RVO_Dispersion_TangentBug_visualization.html).
The main function for the demo is `run_lego_demo` in [`full_demo.jl`](src/full_demo.jl). Its docstring lists every option.

If the demo setting `update_anim_at_every_step` is not set to `true`, then the animation will only update at the completion of nodes in the schedule. This setting results in faster processing times for the animation, but results in entities taking straight paths between updates. Therefore, it appears that collisions occur between entities. If collision avoidance is enabled and you want to see the collision avoidance in action (with no missed steps), set `update_anim_at_every_step` to `true`. Changing this setting increases processing time quite a bit.

### What a run reports
`run_lego_demo` returns `(env, stats)` and, with `write_results=true`, writes `stats` to `<results_path>/<method>_<flags>/<date>_stats.toml`. Nothing is written outside `results_path`.

| Keys | Meaning |
| --- | --- |
| `Makespan`, `OptimisticMakespan` | Simulated and planned completion time, in simulated seconds. Lower is better. `Makespan = Inf` means the project did not finish. |
| `RobotMinGap`, `RobotOverlapSteps`, `MinGap`, `OverlapSteps`, `PositionSwaps`, `MaxSpeed` | Safety record. The makespan cannot see overlaps or teleports, so report these with it. A negative gap means two agents overlapped. |
| `TerminationStatus`, `ObjectiveValue`, `ObjectiveBound`, `RelativeGap` | How far a MILP solver got. A MILP result means "this solver for this long". |
| `SearchHistory`, `SearchEvaluations`, `SearchTimedOut`, `SearchKeptGreedy` | What a metaheuristic did. |
| `SourceHash`, `GitCommit`, `GitDirty` | The code that produced the result. Compare only results with the same hash. |
| `Completed` | `false` in a stats file means the run crashed or is still going. |

The simulator abstracts physics, and this affects what you can conclude: velocity changes are instant unless you set `max_acceleration`, robots can swap positions instantly, and the top speed is 4 m/s whatever the model's scale. Completion times are comparable within one model, not across models, and they have not been calibrated against real robots.

### Experiments and tests
```bash
julia --project scripts/method_comparison.jl run --name mine --models tractor --seeds 1:30   # paired runs, resumable
julia --project scripts/method_comparison.jl analyze results/experiments/mine_<hash>.csv     # tables with paired tests
julia --project -e 'using Pkg; Pkg.test()'                                                   # Julia test suite
cd dashboard && python -m pytest                                                             # dashboard test suite
```
See [`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md) for the experiments run so far and how to reproduce them, and [`docs/AUDIT_STATUS.md`](docs/AUDIT_STATUS.md) for the known limitations left after the forensic audit.

### Images from the Tractor Project
![Tractor Project a](media/tractor_demo_a.png)

![Tractor Project b](media/tractor_demo_b.png)

![Tractor Project c](media/tractor_demo_c.png)

![Tractor Project d](media/tractor_demo_d.png)

## Citation

```
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
