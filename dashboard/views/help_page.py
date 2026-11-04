"""Help & about: how to use the dashboard, what the numbers mean, and where they come from."""
from __future__ import annotations

import streamlit as st

from simulation.catalog import ASSIGNMENT_METHODS, MOVEMENT_METHODS_EXPLAINED, MOVEMENT_PROFILES, SAFETY_NOTE, SOLVERS
from ui import nav, theme


def render() -> None:
    theme.page_header("Help & about", "How to use ConstructionLab, what each result means, and how the dashboard "
                      "relates to the ConstructionBots simulator.", eyebrow="System")
    tabs = st.tabs(["Getting started", "Results explained", "Methods", "3D viewer", "Reproducibility",
                    "Troubleshooting", "About"])

    with tabs[0]:
        theme.section("The workflow", "Configure → Run → Observe → Compare → Export")
        st.markdown("""
1. **Open New simulation.** The defaults are a good first experiment: the *Tractor* model, its default 10 robots,
   *Greedy* task assignment and the *Recommended* movement profile.
2. **Change what you want to study** — the number of robots, the assignment method (and its solver), or the
   movement profile. Everything else can stay as it is.
3. **Press Run simulation.** The right-hand side shows the current phase, and while robots move, how many
   construction tasks are complete. A live 3D preview appears once tasks are assigned.
4. **Watch the replay** when the run finishes: play, pause, scrub, change speed, rotate and zoom with the mouse.
5. **Compare** runs on the Compare experiments page, and **export** tables as CSV files for Excel or other tools.

To compare methods fairly, use **Comparison study** on the New simulation page: it varies exactly one factor,
runs every option with the same random seeds, and keeps everything else fixed.
""")
        st.markdown("The first run after starting the dashboard takes about two minutes: the simulation engine loads "
                    "Julia and compiles the simulator's code. Later runs of the same kind are much faster.")
        nav.link("new", "Start a new simulation", icon=":material/play_circle:")

    with tabs[1]:
        theme.section("What the numbers mean")
        theme.kv_table([
            ("Completion time (makespan)", "Simulated seconds from the start until the model is completely built. "
                                           "Reported by the simulator as Makespan. Lower is better."),
            ("Planned completion", "The schedule's own estimate right after task assignment, ignoring traffic "
                                   "(OptimisticMakespan). The gap to the completion time shows the cost of robots "
                                   "waiting for and avoiding each other."),
            ("Assignment time", "Computer (wall-clock) seconds spent assigning tasks (AssignmentTime in the "
                                "simulator's statistics file)."),
            ("Preparation time", "Computer seconds from reading the model to finishing assignment "
                                 "(PreExecutionRuntime)."),
            ("Execution time", "Computer seconds spent simulating the robots' motion (ExecutionRuntime)."),
            ("Total run time", "Computer seconds for the whole simulator call, measured by the dashboard."),
            ("Includes compilation", "Yes for the first run of each kind in an engine session: Julia compiles code "
                                     "while running it, which inflates computer times (not simulated times)."),
            ("Solver result", "The MILP solver's own status: optimal, or stopped at the time limit with a "
                              "feasible schedule and a remaining optimality gap. A MILP result means \"this solver "
                              "for this long\", not the optimum."),
            ("Smallest robot gap", "The closest two free robots ever came, surface to surface. Negative means they "
                                   "overlapped. The makespan cannot see this, so read the two together."),
            ("Overlap steps", "Simulation steps with an overlap. The counter for all agents treats transport teams "
                              "as bounding circles, so it can overstate contact; the one for robots is exact."),
            ("Position swaps", "Times two robots instantly exchanged positions to unblock a team. These are teleports, "
                               "which a real robot could not do."),
        ], header=("Result", "Meaning"))
        theme.note("Simulated time and computer time are different things. Simulated seconds describe the robots' "
                   "world; computer seconds describe how long your computer worked. Charts and tables always say "
                   "which one they show (sim s or cpu s).", "info")
        theme.section("Run outcomes")
        theme.kv_table([
            ("Completed", "The simulator finished building the model."),
            ("Incomplete", "The simulation ran but stopped before the model was built: no task finished for the "
                           "configured number of steps, or the step limit was reached. No completion time exists."),
            ("Failed", "The simulator raised an error, for example no feasible task assignment (often too few robots "
                       "for the largest transport team). The error and logs are kept with the run."),
            ("Rejected", "The settings could not be used (for example Gurobi without a licence). Nothing was simulated."),
            ("Cancelled / Timed out", "Stopped by you, or by the wall-clock limit. Partial output is kept."),
            ("Interrupted", "The dashboard was closed or restarted while the run was queued or running."),
        ], header=("Status", "Meaning"))
        st.caption("Failed and incomplete runs are never counted as zero in charts or averages; they are counted "
                   "and listed separately.")

    with tabs[2]:
        theme.section("Task assignment")
        theme.kv_table([(o.label, f"{o.family}. {o.description}") for o in ASSIGNMENT_METHODS],
                       header=("Method", "What it does"))
        st.markdown("**Three families.** *Heuristic rules* (Greedy, Greedy with travel, Most complex first, Nearest station first) apply a "
                    "fixed rule and decide instantly. *Exact optimization* (the MILP methods) asks a solver for the "
                    "schedule with the shortest planned completion time, within the time limit. *Metaheuristics* "
                    "(Genetic algorithm, Particle swarm, Simulated annealing, and Random search as their control) search over task orders with a budget of "
                    "iterations × population candidate schedules and stop early at the time limit. All of them respect "
                    "the build order and team sizes, and the same movement simulation follows, so differences in the "
                    "results come from the assignment. To benchmark them, choose *Study* and vary the assignment method.")
        theme.section("Optimization solvers", "only used by the MILP methods")
        theme.kv_table([(o.label, o.description) for o in SOLVERS], header=("Solver", "Notes"))
        st.markdown("A MILP solver stops at the **optimizer time limit**. Whatever schedule it has by then is used, "
                    "which may not be optimal. On this computer, for example, MILP from scratch on the Tractor with a "
                    "30 s limit produced a longer planned schedule than Greedy; the warm-started variant starts from "
                    "Greedy's schedule and can only improve on it.")
        theme.section("Movement")
        for k, v in MOVEMENT_METHODS_EXPLAINED.items():
            st.markdown(f"**{k}.** {v}")
        theme.kv_table([(p.label, f"RVO2 {'on' if p.rvo else 'off'} · Tangent Bug {'on' if p.tangent_bug else 'off'} · "
                                  f"Dispersion {'on' if p.dispersion else 'off'}", p.description + (" " + p.note if p.note else ""))
                        for p in MOVEMENT_PROFILES], header=("Profile", "Flags", "Notes"))
        theme.note(SAFETY_NOTE, "warn", "Safety limitation.")

    with tabs[3]:
        theme.section("The 3D viewer")
        st.markdown("""
The viewer shows the simulator's own MeshCat animation of the run — not an illustration.

* **Live preview** (while running): the simulator saves the animation so far every few dozen updates; the viewer
  loads each new snapshot and, with *Follow latest* ticked, jumps to the newest moment. It is a periodic snapshot,
  not a continuous video stream.
* **Replay** (after the run): the complete animation. *Play*, *Restart*, the slider and the speed menu control
  playback; the time readout converts animation frames to simulated seconds.
* **Mouse:** drag to rotate, scroll to zoom, right-drag to pan. *Reset view* frames the whole site.
  *Scene controls* opens MeshCat's own panel (layers, camera, background). *Full screen* and *Open in new tab*
  give the viewer the whole screen.
* **Colours in the scene:** purple discs are construction sites that are currently active; green rings mark robots
  and transport teams that are currently working. Parts keep their LEGO colours.
* **Smooth animation** (Advanced settings) records every simulation step. Without it, positions are recorded when
  tasks finish and drawn as straight lines in between, so robots can *appear* to pass through each other.
""")
    with tabs[4]:
        theme.section("Reproducing a result")
        st.markdown("""
* Every run folder contains `config.toml` with your settings and the **exact keyword arguments** passed to
  `ConstructionBots.run_lego_demo`, plus the simulator's own `stats.toml`, both log files and, in `result.toml`,
  the software versions, the git commit and a hash of the simulator's source. Runs from different code are never
  compared with each other.
* The **random seed** is passed as `rng = MersenneTwister(seed)`; in this version of the simulator it decides the
  robots' starting positions (and the metaheuristics' random numbers). Apart from MILP with a time limit, the same
  code, settings and seed give the same results, including after a recompile.
* **MILP with a time limit is not deterministic**: how far the solver gets depends on the computer's speed and load,
  so repeated runs can produce different schedules.
* **Computer times** depend on the computer and on compilation. Tick *Warm up first* (or use a study, where warm-up is
  on by default) when you need clean computer-time measurements.
""")
    with tabs[5]:
        theme.section("Common problems")
        theme.kv_table([
            ("The first run sits at “Loading the LEGO model…” for a minute or two",
             "Normal: Julia is compiling the simulator. Later runs are faster."),
            ("“The engine failed to start”", "Open System diagnostics, run the checks, and read the engine log there. "
                                             "Usually Julia or the project packages are missing."),
            ("RVO2 is missing", "The simulator needs the sisl fork of RVO2 for every run, installed in the Python "
                                "that Julia's PyCall uses (not the Python running this dashboard). Follow "
                                "notebooks/SETUP.md, step 3."),
            ("“No valid task assignment exists”", "Too few robots for the largest transport team of this model. Use "
                                                  "the model default or more robots."),
            ("Gurobi runs are rejected", "Gurobi needs your own licence. Use HiGHS, or see dashboard/README.md."),
            ("The run is Incomplete", "Robots stopped making progress. Try the Recommended movement profile, more "
                                      "robots, or a larger 'Maximum steps without progress'."),
            ("The viewer stays empty", "Animations exist only when 'Save 3D animation' is on. Large models take a "
                                       "while to save; the replay appears when the run finishes."),
            ("“Another ConstructionLab dashboard is using this results folder”",
             "Only one dashboard window may run simulations at a time. Close the other one."),
        ], header=("Symptom", "What to do"))
        nav.link("diagnostics", "Open System diagnostics", icon=":material/monitor_heart:")

    with tabs[6]:
        theme.section("About ConstructionLab")
        st.markdown("""
ConstructionLab is a local dashboard for the open-source **ConstructionBots.jl** multi-robot assembly simulator
(Stanford Intelligent Systems Laboratory). It does not re-implement any planning or motion logic: every run calls the
simulator's public entry point `run_lego_demo` in a separate Julia process, using the repository's own Julia
environment.

**Citation.** K. Brown, D. M. Asmar, M. Schwager, M. J. Kochenderfer. *Large-Scale Multi-Robot Assembly Planning for
Autonomous Manufacturing.* Robotics and Autonomous Systems 194 (2025) 105179.

**Licences.** ConstructionBots.jl: MIT. LEGO part geometry: the LDraw Parts Library (CC BY 2.0 / CC BY 4.0), downloaded
separately. HiGHS: MIT. GLPK: GPL-3.0. Gurobi: commercial, needs your own licence. The dashboard uses Streamlit,
pandas and Altair (Apache-2.0 / BSD-3-Clause).
""")
