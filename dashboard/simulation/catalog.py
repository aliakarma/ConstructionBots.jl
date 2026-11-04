"""What can be simulated: models from the repository's registry, and the assignment,
solver and movement options that `run_lego_demo` (src/full_demo.jl) actually accepts.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

from .paths import WORKER_SCRIPT, Paths, find_julia, julia_child_env
from .tomlio import read_toml

# Friendly display names for registry keys. Purely cosmetic: models, files, scales and
# default robot counts always come from src/project_params.jl. Unknown keys are title-cased.
DISPLAY_NAMES = {
    "colored_8x8": "Colored 8×8 Plate",
    "quad_nested": "Quad Nested",
    "heavily_nested": "Heavily Nested",
    "tractor": "Tractor",
    "tie_fighter": "TIE Fighter (mini)",
    "x_wing_mini": "X-Wing (mini)",
    "imperial_shuttle": "Imperial Shuttle (mini)",
    "x_wing_tie_mini": "X-Wing + TIE (mini)",
    "at_te_walker": "AT-TE Walker (mini)",
    "x_wing": "X-Wing",
    "passenger_plane": "Passenger Plane",
    "imperial_star_destroyer": "Imperial Star Destroyer",
    "kings_castle": "King's Castle",
    "at_at": "AT-AT",
    "saturn_v": "Saturn V",
}

SIZE_LABELS = {"small": "Small", "medium": "Medium", "large": "Large", "very_large": "Very large"}


def size_class(parts: int | None) -> str:
    """Experiment size from the part count noted in the registry (thresholds group the
    registry's models by the reference run times the authors recorded)."""
    if parts is None:
        return "medium"
    if parts < 80:
        return "small"
    if parts < 200:
        return "medium"
    if parts < 700:
        return "large"
    return "very_large"


@dataclass(frozen=True)
class Model:
    key: str
    index: int
    name: str
    file_name: str
    model_scale: float
    default_robots: int
    file_exists: bool
    reference_parts: int | None = None
    reference_assemblies: int | None = None
    reference_time: str | None = None

    @property
    def size(self) -> str:
        return size_class(self.reference_parts)

    @property
    def size_label(self) -> str:
        return SIZE_LABELS[self.size]


@dataclass(frozen=True)
class Option:
    key: str
    label: str
    description: str
    uses_solver: bool = False
    family: str = ""
    search: bool = False       # metaheuristic: uses the search budget (iterations × population) and the time limit


RULE, EXACT, META = "Heuristic rule", "Exact optimization", "Metaheuristic"
SEARCH_EXPLAINED = ("A candidate is one priority number per transport task (random keys). It is decoded with "
                    "Greedy's rules (build order respected, nearest free robots matched to the task) and scored by its "
                    "planned completion time, robot travel included. The search starts from Greedy's task order and "
                    "keeps the best schedule found; Greedy's own schedule is a candidate too, so the plan is never "
                    "worse than Greedy's. A better plan does not guarantee a faster simulation: judge methods by the "
                    "simulated completion time over several seeds (src/assignment_algorithms.jl).")

ASSIGNMENT_METHODS = [
    Option("greedy", "Greedy",
           "A fast rule-based baseline: each task goes to the robot team that can finish it earliest, "
           "respecting the build order (the repository's GreedyOrderedAssignment).", False, RULE),
    Option("greedy_with_travel", "Greedy with travel",
           "Greedy, except that each robot's finish time includes its earlier travel. This is the decoder the "
           "metaheuristics use, so comparing it with them separates the decoder's effect from the search's.",
           False, RULE),
    Option("most_complex_first", "Most complex first",
           "Rule: the open task that needs the largest robot team (then has the most LEGO parts) goes first; "
           "ties go to the team that can finish earliest.", False, RULE),
    Option("nearest_station_first", "Nearest station first",
           "Rule: the open task whose pick-up station the free robots reach soonest goes first, judged by travel "
           "time only (not by when the robots become free).", False, RULE),
    Option("milp", "MILP",
           "Formulates task assignment as a mixed-integer linear program and asks an optimization solver for a "
           "schedule that minimises the planned completion time. The solver stops at the time limit, so the result "
           "may be a feasible schedule that is not proven optimal.", True, EXACT),
    Option("milp_w_greedy_warm_start", "Greedy + MILP warm start",
           "Runs Greedy first and hands its schedule to the MILP solver as a starting point, so the solver always "
           "has a feasible schedule to improve on.", True, EXACT),
    Option("genetic_algorithm", "Genetic algorithm",
           "Metaheuristic: evolves a population of task-priority orders with elitism, tournament selection, "
           "crossover and mutation. " + SEARCH_EXPLAINED, False, META, True),
    Option("particle_swarm", "Particle swarm",
           "Metaheuristic (PSO): a swarm of task-priority orders moves towards each particle's best and the swarm's "
           "best order. " + SEARCH_EXPLAINED, False, META, True),
    Option("simulated_annealing", "Simulated annealing",
           "Metaheuristic: changes one task-priority order step by step and sometimes accepts a worse one early on, "
           "less and less often as it cools. " + SEARCH_EXPLAINED, False, META, True),
    Option("random_search", "Random search",
           "Control for the metaheuristics: the same budget of candidates, drawn at random with no search operators. "
           "If a metaheuristic does not beat it, its operators add nothing. " + SEARCH_EXPLAINED, False, META, True),
]

# Short tags used in run folder names.
ASSIGNMENT_TAGS = {"greedy": "greedy", "greedy_with_travel": "greedytravel", "most_complex_first": "mcf", "nearest_station_first": "nsf", "milp": "milp",
                   "milp_w_greedy_warm_start": "milpws", "genetic_algorithm": "ga", "particle_swarm": "pso",
                   "simulated_annealing": "sa", "random_search": "rs"}

SOLVERS = [
    Option("highs", "HiGHS", "Open-source (MIT licence). Recommended default.", True),
    Option("glpk", "GLPK", "Open-source (GPL-3.0). Cannot warm-start, so it cannot be used with Greedy + MILP warm start.", True),
    Option("gurobi", "Gurobi", "Commercial. Needs your own valid Gurobi licence on this computer.", True),
]


@dataclass(frozen=True)
class MovementProfile:
    key: str
    label: str
    rvo: bool
    tangent_bug: bool
    dispersion: bool
    description: str
    note: str = ""

    @property
    def avoidance_reduced(self) -> bool:
        return not (self.rvo and self.tangent_bug and self.dispersion)

    @property
    def unsafe(self) -> bool:
        """Reciprocal collision avoidance (RVO2) is off: robots may overlap."""
        return not self.rvo


DISPERSION_NEEDS_RVO = ("In this version of the simulator the dispersion (potential-field) velocity adjustment is "
                        "applied only while RVO2 is on (src/route_planning.jl, get_twist_cmd), so with RVO2 off the "
                        "dispersion setting has no effect.")

MOVEMENT_PROFILES = [
    MovementProfile("recommended", "Recommended", True, True, True,
                    "RVO2 + Tangent Bug + Dispersion: the configuration of the repository's hosted demos."),
    MovementProfile("no_rvo2", "No RVO2", False, True, True,
                    "Turns off RVO2 reciprocal collision avoidance between robots.", DISPERSION_NEEDS_RVO),
    MovementProfile("no_tangent_bug", "No Tangent Bug", True, False, True,
                    "Robots head straight for their goals instead of steering around active construction sites."),
    MovementProfile("no_dispersion", "No Dispersion", True, True, False,
                    "Turns off the potential field that spreads waiting robots apart. The simulator itself warns that "
                    "RVO2 without dispersion is not recommended (ablation only)."),
    MovementProfile("none", "No avoidance methods", False, False, False,
                    "All three methods off: robots move straight to their goals and may pass through each other "
                    "(the configuration of the repository's X-Wing demo)."),
]

MOVEMENT_METHODS_EXPLAINED = {
    "RVO2": "Reciprocal Velocity Obstacles: each robot adjusts its velocity so that it does not collide with nearby "
            "robots, assuming they do the same (sisl fork of the RVO2 library, called through Python).",
    "Tangent Bug": "A path-following rule that steers robots around the circular construction sites that are "
                   "currently active, instead of driving straight through them.",
    "Dispersion": "A potential field that pushes idle or waiting robots apart so they do not crowd build sites.",
}

SAFETY_NOTE = ("The completion time does not reward or penalize safety: with reduced collision avoidance robots can pass "
               "through each other and finish sooner. Every run records its safety separately (smallest gap between robots, "
               "steps with an overlap, position swaps). Read those beside the completion time: a shorter time is not by "
               "itself evidence of a better or safer method.")


def option(options: list, key: str):
    for o in options:
        if o.key == key:
            return o
    raise KeyError(key)


def movement_profile(key: str) -> MovementProfile:
    return option(MOVEMENT_PROFILES, key)


def custom_profile(rvo: bool, tangent_bug: bool, dispersion: bool) -> MovementProfile:
    for p in MOVEMENT_PROFILES:
        if (p.rvo, p.tangent_bug, p.dispersion) == (rvo, tangent_bug, dispersion):
            return p
    note = DISPERSION_NEEDS_RVO if (dispersion and not rvo) else ""
    on = [n for n, f in (("RVO2", rvo), ("Tangent Bug", tangent_bug), ("Dispersion", dispersion)) if f]
    return MovementProfile("custom", "Custom", rvo, tangent_bug, dispersion,
                           "Custom combination: " + (", ".join(on) if on else "no avoidance methods") + ".", note)


@dataclass
class Catalog:
    models: list[Model] = field(default_factory=list)
    source: str = "src/project_params.jl"
    error: str | None = None

    def model(self, key: str) -> Model:
        for m in self.models:
            if m.key == key:
                return m
        raise KeyError(key)

    def has(self, key: str) -> bool:
        return any(m.key == key for m in self.models)

    @property
    def default_model_key(self) -> str | None:
        if self.has("tractor"):
            return "tractor"
        return self.models[0].key if self.models else None


def catalog_from_registry(data: dict) -> Catalog:
    models = []
    for d in data.get("models", []):
        key = str(d["key"])
        models.append(Model(
            key=key, index=int(d["index"]), name=DISPLAY_NAMES.get(key, key.replace("_", " ").title()),
            file_name=str(d["file_name"]), model_scale=float(d["model_scale"]), default_robots=int(d["default_robots"]),
            file_exists=bool(d.get("file_exists", False)), reference_parts=d.get("reference_parts"),
            reference_assemblies=d.get("reference_assemblies"), reference_time=d.get("reference_time")))
    # Small, quick models first; within a size class keep the registry order.
    order = {"small": 0, "medium": 1, "large": 2, "very_large": 3}
    models.sort(key=lambda m: (order[m.size], m.reference_parts or 0, m.index))
    return Catalog(models=models, source=str(data.get("source", "src/project_params.jl")))


def load_catalog(paths: Paths, refresh: bool = False) -> Catalog:
    """Model registry exported by the Julia worker from src/project_params.jl (cached until that file changes)."""
    paths.ensure()
    cache = paths.cache / "registry.toml"
    source = paths.repo / "src" / "project_params.jl"
    models_dir = paths.repo / "LDraw_files"
    stale = (not cache.exists() or refresh or cache.stat().st_mtime < source.stat().st_mtime
             or (models_dir.exists() and cache.stat().st_mtime < models_dir.stat().st_mtime))
    if stale:
        julia = find_julia(paths.repo)
        if julia.path is None:
            if cache.exists():
                return catalog_from_registry(read_toml(cache) or {})
            return Catalog(error="Julia was not found, so the model registry could not be read. See System Diagnostics.")
        try:
            proc = subprocess.run(
                [str(julia.path), f"--project={paths.repo}", "--startup-file=no", "--history-file=no",
                 str(WORKER_SCRIPT), "registry", "--repo", str(paths.repo), "--out", str(cache)],
                capture_output=True, text=True, timeout=180, env=julia_child_env(), cwd=str(paths.repo))
        except (OSError, subprocess.TimeoutExpired) as e:
            return Catalog(error=f"Reading the model registry failed: {e}")
        if proc.returncode != 0 or not cache.exists():
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
            return Catalog(error="Reading the model registry failed: " + " ".join(tail))
    return catalog_from_registry(read_toml(cache) or {})
