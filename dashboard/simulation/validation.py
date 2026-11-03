"""Experiment settings: validation and translation into `run_lego_demo` arguments.

Every value is checked here before a run is created, and checked again by the Julia
worker against its own whitelists. Nothing a user types is ever executed as code.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from .catalog import (ASSIGNMENT_METHODS, SAFETY_NOTE, SOLVERS, Catalog, Model, MovementProfile,
                      Option, custom_profile, movement_profile, option)

MAX_ROBOTS = 500
MAX_SEED = 2_147_483_647
MAX_SEEDS_PER_STUDY = 50
MAX_RUNS_PER_STUDY = 60

# Live preview: how often (in visualizer updates) the simulator saves an animation snapshot
# (`save_anim_interval`), and how many updates it buffers before writing them (`process_updates_interval`).
LIVE_PREVIEW = {
    "off": (0, 50),
    "normal": (60, 30),
    "frequent": (20, 10),
}
LIVE_PREVIEW_LABELS = {"off": "Off", "normal": "Normal", "frequent": "Frequent"}
SMOOTH_LIVE_FACTOR = 5   # smooth animations update every step, so snapshot less often

NO_TIME_LIMIT = 0                    # wall-clock limit in minutes: 0 = the run may take as long as it needs
MAX_TIMEOUT_MIN = 7 * 24 * 60
DEFAULT_MAX_STEPS = 100_000          # run_lego_demo defaults
DEFAULT_MAX_NO_PROGRESS = 10_000


def limits_suffix(max_steps, max_no_progress) -> list[str]:
    """Label parts for non-default step limits, so differently limited runs never share a label."""
    out = []
    if max_steps not in (None, DEFAULT_MAX_STEPS):
        out.append(f"max {max_steps:,} steps")
    if max_no_progress not in (None, DEFAULT_MAX_NO_PROGRESS):
        out.append(f"stop after {max_no_progress:,} idle steps")
    return out


@dataclass
class RunConfig:
    """One experiment in the dashboard's own terms. Every field has a sensible default."""

    model_key: str = "tractor"
    num_robots: int | None = None          # None = the model's default from the registry
    seed: int = 1
    assignment: str = "greedy"
    solver: str = "highs"
    movement: str = "recommended"          # a MOVEMENT_PROFILES key, or "custom"
    custom_rvo: bool = True
    custom_tangent_bug: bool = True
    custom_dispersion: bool = True
    optimizer_time_limit_s: int = 60       # MILP solver, or metaheuristic search
    search_iterations: int = 25            # metaheuristics only (run_lego_demo metaheuristic_iterations)
    search_population: int = 16            # metaheuristics only (run_lego_demo metaheuristic_population)
    max_steps: int = 100_000               # run_lego_demo default
    max_iters_no_progress: int = 10_000    # run_lego_demo default
    save_animation: bool = True
    smooth_animation: bool = False         # run_lego_demo `update_anim_at_every_step`
    live_preview: str = "normal"
    timeout_min: int | None = None         # None or 0 = no wall-clock limit
    warm_up: bool = False
    confirm_large: bool = False
    label: str = ""
    batch_id: str = ""
    study_factor: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RunConfig":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Resolved:
    """A validated configuration translated into the simulator's actual arguments."""

    config: RunConfig
    model: Model
    num_robots: int
    robots_source: str
    assignment: Option
    solver: Option | None
    movement: MovementProfile
    timeout_min: int
    live_interval: int
    process_updates_interval: int

    @property
    def label(self) -> str:
        if self.config.label:
            return self.config.label
        parts = [f"{self.model.name}, {self.num_robots} robots", self.assignment.label]
        if self.solver:
            parts[-1] += f" + {self.solver.label}"
        parts.append(self.movement.label)
        parts += limits_suffix(self.config.max_steps, self.config.max_iters_no_progress)
        return " | ".join(parts)

    def demo_arguments(self) -> dict[str, Any]:
        """Keyword arguments passed to ConstructionBots.run_lego_demo (shown to the user and saved with the run)."""
        c = self.config
        live = c.save_animation and self.live_interval > 0
        return {
            "ldraw_file": self.model.file_name,
            "project_name": self.model.key,
            "model_scale": self.model.model_scale,
            "num_robots": self.num_robots,
            "assignment_mode": f":{self.assignment.key}",
            "milp_optimizer": f":{self.solver.key}" if self.solver else f":highs (not used by {self.assignment.label})",
            "optimizer_time_limit": c.optimizer_time_limit_s,
            "metaheuristic_iterations": c.search_iterations,
            "metaheuristic_population": c.search_population,
            "rvo_flag": self.movement.rvo,
            "tangent_bug_flag": self.movement.tangent_bug,
            "dispersion_flag": self.movement.dispersion,
            "rng": f"MersenneTwister({c.seed})",
            "max_steps": c.max_steps,
            "max_num_iters_no_progress": c.max_iters_no_progress,
            "save_animation": c.save_animation,
            "update_anim_at_every_step": c.save_animation and c.smooth_animation,
            "save_animation_along_the_way": live,
            "save_anim_interval": self.live_interval if live else 500,
            "process_updates_interval": self.process_updates_interval,
            "anim_active_agents": c.save_animation,
            "anim_active_areas": c.save_animation,
            "open_animation_at_end": False,
            "write_results": True,
            "overwrite_results": False,
            "look_for_previous_milp_solution": False,
            "save_milp_solution": False,
        }

    def job_request(self, run_id: str, run_dir: str) -> dict[str, Any]:
        """The job file read by julia_worker.jl (plain values only)."""
        c = self.config
        return {
            "run_id": run_id,
            "run_dir": run_dir,
            "model_key": self.model.key,
            "num_robots": self.num_robots,
            "assignment_mode": self.assignment.key,
            "milp_optimizer": self.solver.key if self.solver else "highs",
            "optimizer_time_limit": c.optimizer_time_limit_s,
            "metaheuristic_iterations": c.search_iterations,
            "metaheuristic_population": c.search_population,
            "rvo_flag": self.movement.rvo,
            "tangent_bug_flag": self.movement.tangent_bug,
            "dispersion_flag": self.movement.dispersion,
            "seed": c.seed,
            "seed_global_rng": True,
            "max_steps": c.max_steps,
            "max_num_iters_no_progress": c.max_iters_no_progress,
            "save_animation": c.save_animation,
            "update_anim_at_every_step": c.save_animation and c.smooth_animation,
            "live_preview_interval": self.live_interval if c.save_animation else 0,
            "process_updates_interval": self.process_updates_interval,
            "warm_up": c.warm_up,
        }


@dataclass
class Validation:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    resolved: Resolved | None = None

    @property
    def ok(self) -> bool:
        return not self.errors and self.resolved is not None


def _is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def resolve_movement(c: RunConfig) -> MovementProfile:
    if c.movement == "custom":
        return custom_profile(bool(c.custom_rvo), bool(c.custom_tangent_bug), bool(c.custom_dispersion))
    return movement_profile(c.movement)


def validate(c: RunConfig, catalog: Catalog, env: dict[str, str] | None = None) -> Validation:
    """Check every setting. `env` holds diagnostic statuses (e.g. {"rvo2": "ok", "solver_gurobi": "unavailable"})."""
    env = env or {}
    v = Validation()
    err, warn = v.errors.append, v.warnings.append

    # Model
    if catalog.error:
        err(catalog.error)
        return v
    if not catalog.has(c.model_key):
        err(f'"{c.model_key}" is not a model in the repository registry (src/project_params.jl).')
        return v
    model = catalog.model(c.model_key)
    if not model.file_exists:
        err(f"The model file LDraw_files/{model.file_name} is missing. Restore the repository's LDraw_files folder.")

    # Robots
    if c.num_robots is None:
        num_robots, source = model.default_robots, "model default"
    elif _is_int(c.num_robots) and 1 <= c.num_robots <= MAX_ROBOTS:
        num_robots, source = c.num_robots, "custom"
    else:
        err(f"Number of robots must be a whole number from 1 to {MAX_ROBOTS}.")
        num_robots, source = model.default_robots, "model default"
    if source == "custom" and num_robots < model.default_robots:
        warn(f"Fewer robots than the model's default ({model.default_robots}). If a transport team needs more robots "
             "than are available, the simulator stops with \"no assignment found\".")
    if num_robots > 2 * model.default_robots:
        warn(f"{num_robots} robots is more than twice the model's default ({model.default_robots}); planning and "
             "simulation take longer with many robots.")

    if not (_is_int(c.seed) and 0 <= c.seed <= MAX_SEED):
        err(f"Random seed must be a whole number from 0 to {MAX_SEED}.")

    # Assignment and solver
    try:
        assignment = option(ASSIGNMENT_METHODS, c.assignment)
    except KeyError:
        err(f'Unknown assignment method "{c.assignment}".')
        return v
    solver = None
    if assignment.uses_solver:
        try:
            solver = option(SOLVERS, c.solver)
        except KeyError:
            err(f'Unknown solver "{c.solver}".')
            return v
        if solver.key == "glpk" and assignment.key == "milp_w_greedy_warm_start":
            err("GLPK cannot be combined with Greedy + MILP warm start. The simulator notes that GLPK does not support "
                "warm starts through JuMP (src/full_demo.jl), so the greedy starting point would be silently ignored. "
                "Choose HiGHS (free) or Gurobi (licensed).")
        status = env.get(f"solver_{solver.key}")
        if solver.key == "gurobi":
            if status == "unavailable":
                err("Gurobi has no valid licence on this computer (see System Diagnostics). Choose HiGHS or GLPK. "
                    "The dashboard never replaces a requested solver with another one.")
            elif status != "ok":
                warn("Gurobi's licence has not been checked yet. The engine checks it before the run starts and "
                     "rejects the run if no valid licence is found; no other solver is substituted.")
        elif status in ("fail", "unavailable"):
            err(f"{solver.label} is not usable on this computer (see System Diagnostics).")
        if not (_is_int(c.optimizer_time_limit_s) and 1 <= c.optimizer_time_limit_s <= 86_400):
            err("Optimizer time limit must be a whole number of seconds from 1 to 86400.")
        elif c.optimizer_time_limit_s > 3600:
            warn("The optimizer time limit is over one hour.")
        if model.size != "small":
            warn("The MILP grows quickly with model size; on this model the solver will probably stop at the time "
                 "limit with a feasible but unproven schedule.")
    if assignment.search:
        if not (_is_int(c.search_iterations) and 1 <= c.search_iterations <= 1000):
            err("Search iterations must be a whole number from 1 to 1000.")
        if not (_is_int(c.search_population) and 2 <= c.search_population <= 500):
            err("Search population must be a whole number from 2 to 500.")
        if not (_is_int(c.optimizer_time_limit_s) and 1 <= c.optimizer_time_limit_s <= 86_400):
            err("Search time limit must be a whole number of seconds from 1 to 86400.")
        if model.size != "small":
            warn("A metaheuristic builds the whole schedule once per candidate; on this model the search will "
                 "probably stop at the time limit before using its full budget.")

    # Movement
    try:
        movement = resolve_movement(c)
    except KeyError:
        err(f'Unknown movement profile "{c.movement}".')
        return v
    if movement.rvo and not movement.dispersion:
        warn("RVO2 is on but dispersion is off. The simulator warns that this is not recommended.")
    if movement.note:
        warn(movement.note)
    if movement.unsafe:
        warn(SAFETY_NOTE)
    if env.get("rvo2") == "fail":
        err("The RVO2 module cannot be imported by the Python that Julia uses, and the simulator needs it for every "
            "run (even with RVO2 off). See System Diagnostics.")

    # Limits and animation
    if not (_is_int(c.max_steps) and 100 <= c.max_steps <= 100_000_000):
        err("Maximum simulation steps must be a whole number from 100 to 100,000,000.")
    if not (_is_int(c.max_iters_no_progress) and 10 <= c.max_iters_no_progress <= 100_000_000):
        err("Maximum steps without progress must be a whole number from 10 to 100,000,000.")
    if c.live_preview not in LIVE_PREVIEW:
        err("Unknown live preview setting.")
        interval, pui = 0, 50
    else:
        interval, pui = LIVE_PREVIEW[c.live_preview]
        if c.smooth_animation and interval:
            interval *= SMOOTH_LIVE_FACTOR
            pui *= SMOOTH_LIVE_FACTOR
    if not c.save_animation:
        interval = 0
    if c.smooth_animation and c.save_animation and model.size in ("large", "very_large"):
        warn("Smooth animation records every simulation step; on a model this size the animation file becomes very "
             "large and the run much slower.")
    if interval and model.size in ("large", "very_large"):
        warn("Live preview re-saves the whole animation so far at every snapshot; on a model this size each snapshot "
             "is large. Consider turning live preview off.")

    timeout = c.timeout_min if c.timeout_min is not None else NO_TIME_LIMIT
    if not (_is_int(timeout) and (timeout == NO_TIME_LIMIT or 1 <= timeout <= MAX_TIMEOUT_MIN)):
        err(f"Wall-clock time limit must be 0 (no limit) or a whole number of minutes from 1 to {MAX_TIMEOUT_MIN}.")
        timeout = NO_TIME_LIMIT

    if model.size in ("large", "very_large") and not c.confirm_large:
        err(f"{model.name} is a {model.size_label.lower()} model ({model.reference_parts} parts; the authors noted a "
            f"reference run time of {model.reference_time}, far longer with MILP or animation). Confirm the run in "
            "Advanced settings to start it.")
    if len(c.label) > 120:
        err("The label must be at most 120 characters.")

    if not v.errors:
        v.resolved = Resolved(config=c, model=model, num_robots=num_robots, robots_source=source,
                              assignment=assignment, solver=solver, movement=movement, timeout_min=timeout,
                              live_interval=interval, process_updates_interval=pui)
    return v


# -----------------------------------------------------------------------------
# Studies: several runs that differ in exactly one factor (plus matched seeds)
# -----------------------------------------------------------------------------

STUDY_FACTORS = {
    "assignment": "Assignment method",
    "solver": "Optimization solver",
    "movement": "Movement profile",
    "num_robots": "Number of robots",
    "seed": "Random seed only (repeated trials)",
}


def parse_int_list(text: str, lo: int, hi: int, max_items: int) -> tuple[list[int], str | None]:
    """Parse "1, 2, 5-8" into [1, 2, 5, 6, 7, 8]."""
    values: list[int] = []
    text = (text or "").strip()
    if not text:
        return [], "Enter at least one value."
    for part in re.split(r"[,\s;]+", text):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)|(\d+)", part)
        if not m:
            return [], f'"{part}" is not a whole number or a range like 1-5.'
        if m.group(3) is not None:
            rng = [int(m.group(3))]
        else:
            a, b = int(m.group(1)), int(m.group(2))
            if b < a:
                return [], f'The range "{part}" runs backwards.'
            if b - a + 1 > max_items:
                return [], f"At most {max_items} values are allowed."
            rng = list(range(a, b + 1))
        for x in rng:
            if not lo <= x <= hi:
                return [], f"{x} is outside the allowed range {lo}–{hi}."
            if x not in values:
                values.append(x)
    if len(values) > max_items:
        return [], f"At most {max_items} values are allowed."
    return values, None


def expand_study(base: RunConfig, factor: str, levels: list, seeds: list[int], batch_id: str) -> list[RunConfig]:
    """All runs of a one-factor study. Every setting except `factor` (and the seed) is copied from `base`,
    so competing methods start from the same robot positions (matched seeds)."""
    if factor not in STUDY_FACTORS:
        raise ValueError(factor)
    runs = []
    level_list = levels if factor != "seed" else [None]
    for level in level_list:
        for s in seeds:
            c = replace(base, seed=s, batch_id=batch_id, study_factor=factor, label="")
            if factor == "assignment":
                c = replace(c, assignment=level)
            elif factor == "solver":
                c = replace(c, solver=level)
            elif factor == "movement":
                c = replace(c, movement=level)
            elif factor == "num_robots":
                c = replace(c, num_robots=int(level))
            runs.append(c)
    return runs
