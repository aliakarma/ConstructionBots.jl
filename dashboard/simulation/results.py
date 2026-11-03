"""Run records: reading what each run folder contains, deriving progress from the
simulator's own console output, and exporting tables.

A run folder (results/dashboard/runs/<run_id>/) holds:
  config.toml              settings, resolved values and the exact run_lego_demo arguments (dashboard)
  status.toml              lifecycle state (dashboard while queued/cancelled; worker while running/finished)
  result.toml              metrics parsed from the simulator's statistics (worker)
  simulator_stdout.log     simulator console output (phases, solver log)
  simulator_stderr.log     progress meter and warnings
  error.txt                error and stack trace, if the run failed
  simulator_output/...     the simulator's own files: <time>_stats.toml and <time>_visualization.html
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .paths import Paths
from .tomlio import read_toml

FINAL_STATES = {"success", "incomplete", "failed", "rejected", "canceled", "timed_out", "interrupted"}
ACTIVE_STATES = {"queued", "running"}

STATE_LABELS = {
    "queued": "Queued",
    "running": "Running",
    "success": "Completed",
    "incomplete": "Incomplete",
    "failed": "Failed",
    "rejected": "Rejected",
    "canceled": "Cancelled",
    "timed_out": "Timed out",
    "interrupted": "Interrupted",
}

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

# Phase messages printed by run_lego_demo (src/full_demo.jl) and run_simulation! (src/demo_utils.jl).
PHASES = [
    ("Constructing model spec", "Reading the LEGO model"),
    ("Constructing scene tree", "Building the assembly tree"),
    ("Computing approximate geometry", "Computing part geometry"),
    ("Configuring transport units", "Configuring transport teams"),
    ("Validating scene tree", "Validating the assembly tree"),
    ("Constructing partial schedule", "Building the construction schedule"),
    ("Generating staging plan", "Planning the site layout"),
    ("Placing objects at starting locations", "Placing parts at their start positions"),
    ("Assigning robots", "Assigning tasks to robots"),
    ("Animating preprocessing step", "Recording the build-plan animation"),
    ("Simulating...", "Simulating robot motion"),
    ("PROJECT COMPLETE!", "Project complete, saving results"),
    ("PROJECT INCOMPLETE!", "Simulation stopped without finishing"),
]


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def tail_text(path: Path, max_bytes: int = 200_000) -> str:
    """Last `max_bytes` of a (possibly still growing) log file."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def read_text(path: Path, max_bytes: int = 5_000_000) -> str:
    try:
        with open(path, "rb") as f:
            return f.read(max_bytes).decode("utf-8", errors="replace")
    except OSError:
        return ""


@dataclass
class Progress:
    phase: str = "Waiting for the simulation engine"
    phase_index: int = -1
    closed: int | None = None
    total: int | None = None
    sim_step: int | None = None
    warming_up: bool = False

    @property
    def fraction(self) -> float | None:
        if self.closed is None or not self.total:
            return None
        return max(0.0, min(1.0, self.closed / self.total))


def parse_progress(stdout_text: str, stderr_text: str, warmup_active: bool = False) -> Progress:
    """Current phase from the simulator's phase messages, and, while simulating, the number of
    completed schedule tasks reported by its progress meter (n_closed of n_total)."""
    p = Progress()
    out = strip_ansi(stdout_text)
    err = strip_ansi(stderr_text)
    best = -1
    for i, (marker, label) in enumerate(PHASES):
        if marker in out or marker in err:
            best = i
    if best >= 0:
        p.phase, p.phase_index = PHASES[best][1], best
    elif warmup_active:
        p.phase, p.warming_up = "Warming up the engine (untimed run to compile this code path)", True
    else:
        p.phase = "Loading the LEGO model file and part geometry"
    closed = re.findall(r"n_closed:\s*(\d+)", err)
    total = re.findall(r"n_total:\s*(\d+)", err)
    step = re.findall(r"step_num:\s*(\d+)", err)
    if closed and total:
        p.closed, p.total = int(closed[-1]), int(total[-1])
    if step:
        p.sim_step = int(step[-1])
    return p


@dataclass
class SolverReport:
    termination: str = ""          # optimal | time_limit | infeasible | no_solution | unknown
    label: str = ""
    short: str = ""
    primal_bound: float | None = None
    dual_bound: float | None = None
    gap_percent: float | None = None
    warm_start_objective: float | None = None


def _num(s: str) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


_SOLVER_LABELS = {
    "optimal": "Optimal (proven within the solver's tolerance)",
    "time_limit": "Stopped at the time limit: feasible schedule, not proven optimal",
    "no_solution": "Stopped at the time limit without a feasible schedule",
    "infeasible": "Reported infeasible",
    "unknown": "Not determined from the solver log",
}
_SOLVER_SHORTS = {"optimal": "optimal", "time_limit": "time limit", "no_solution": "no schedule",
                  "infeasible": "infeasible", "unknown": "unknown"}


def _label_report(r: SolverReport) -> SolverReport:
    if r.termination:
        r.label = _SOLVER_LABELS[r.termination]
        r.short = _SOLVER_SHORTS[r.termination]
        if r.termination == "time_limit" and r.gap_percent is not None:
            r.label += f" (gap {r.gap_percent:.1f}%)"
            r.short += f", gap {r.gap_percent:.1f}%"
    return r


def apply_recorded_status(r: SolverReport, result: dict[str, Any]) -> SolverReport:
    """The solver status recorded by the simulator replaces what was read from the log (runs from before it
    was recorded keep the values from the log)."""
    status = result.get("solver_termination_status")
    if not status:
        return r
    no_solution = result.get("solver_primal_status") == "NO_SOLUTION"
    r.termination = {"OPTIMAL": "optimal", "LOCALLY_SOLVED": "optimal", "INFEASIBLE": "infeasible",
                     "TIME_LIMIT": "no_solution" if no_solution else "time_limit"}.get(str(status), "unknown")
    for attr, key in (("primal_bound", "solver_objective"), ("dual_bound", "solver_bound")):
        if isinstance(result.get(key), (int, float)):
            setattr(r, attr, float(result[key]))
    if isinstance(result.get("solver_gap"), (int, float)):
        r.gap_percent = 100 * float(result["solver_gap"])
    return _label_report(r)


def parse_solver_log(stdout_text: str, solver: str) -> SolverReport:
    """Termination status of the MILP solver, read from its own log in the simulator output."""
    t = strip_ansi(stdout_text)
    r = SolverReport()
    if solver == "highs":
        m = re.search(r"MIP start solution is feasible, objective value is\s+([-\d.eE+]+)", t)
        if m:
            r.warm_start_objective = _num(m.group(1))
        reports = list(re.finditer(r"Solving report(.*?)(?:\n\s*Timing|\Z)", t, re.S))
        if reports:
            block = reports[-1].group(1)
            status = re.search(r"Status\s+([^\n]+)", block)
            sol = re.search(r"Solution status\s+([^\n]+)", block)
            r.primal_bound = _num((re.search(r"Primal bound\s+([-\d.eE+inf]+)", block) or [None, None])[1])
            r.dual_bound = _num((re.search(r"Dual bound\s+([-\d.eE+inf]+)", block) or [None, None])[1])
            gap = re.search(r"Gap\s+([-\d.eE+]+)%", block)
            r.gap_percent = _num(gap.group(1)) if gap else None
            s = (status.group(1).strip().lower() if status else "")
            feasible = bool(sol and "feasible" in sol.group(1).lower() and "infeasible" not in sol.group(1).lower())
            if s == "optimal":
                r.termination = "optimal"
            elif "time limit" in s:
                r.termination = "time_limit" if feasible else "no_solution"
            elif "infeasible" in s:
                r.termination = "infeasible"
            else:
                r.termination = "unknown"
    elif solver == "glpk":
        if "INTEGER OPTIMAL SOLUTION FOUND" in t:
            r.termination = "optimal"
        elif "TIME LIMIT EXCEEDED" in t:
            r.termination = "time_limit"
            gaps = re.findall(r"mip\s*=\s*([-\d.eE+]+)\s*[<>]=\s*([-\d.eE+]+|tree is empty)\s+([\d.]+)%", t)
            if gaps:
                r.primal_bound, r.dual_bound, r.gap_percent = _num(gaps[-1][0]), _num(gaps[-1][1]), _num(gaps[-1][2])
        elif "PROBLEM HAS NO INTEGER FEASIBLE SOLUTION" in t:
            r.termination = "infeasible"
        else:
            r.termination = "unknown"
    elif solver == "gurobi":
        if re.search(r"Optimal solution found", t):
            r.termination = "optimal"
        elif re.search(r"Time limit reached", t):
            r.termination = "time_limit"
        elif re.search(r"Model is infeasible", t):
            r.termination = "infeasible"
        else:
            r.termination = "unknown"
        m = re.findall(r"Best objective\s+([-\d.eE+]+),\s*best bound\s+([-\d.eE+]+),\s*gap\s+([\d.]+)%", t)
        if m:
            r.primal_bound, r.dual_bound, r.gap_percent = _num(m[-1][0]), _num(m[-1][1]), _num(m[-1][2])
    return _label_report(r)


@dataclass
class RunRecord:
    run_id: str
    folder: Path
    state: str = "unknown"
    detail: str = ""
    created_at: str = ""
    started_at: str = ""
    finished_at: str = ""
    settings: dict[str, Any] = field(default_factory=dict)
    resolved: dict[str, Any] = field(default_factory=dict)
    arguments: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)

    # --- convenient views -------------------------------------------------------------
    @property
    def state_label(self) -> str:
        return STATE_LABELS.get(self.state, self.state.title())

    @property
    def is_final(self) -> bool:
        return self.state in FINAL_STATES

    @property
    def label(self) -> str:
        """Configuration label (no seed), including any non-default step limits."""
        from .validation import limits_suffix
        label = str(self.resolved.get("label", self.run_id))
        for part in limits_suffix(self.settings.get("max_steps"), self.settings.get("max_iters_no_progress")):
            if part not in label:
                label += " | " + part
        return label

    @property
    def model_name(self) -> str:
        return str(self.resolved.get("model_name", self.settings.get("model_key", "")))

    @property
    def source_hash(self) -> str | None:
        """Which code produced this run. Runs from before this was recorded have none."""
        return self.result.get("software", {}).get("source_hash")

    def metric(self, key: str) -> float | None:
        v = self.result.get(key)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    @property
    def animation_path(self) -> Path | None:
        rel = self.result.get("animation_file")
        if rel:
            p = (self.folder / rel).resolve()
            if p.is_file() and self.folder.resolve() in p.parents:
                return p
        return None

    @property
    def stdout_path(self) -> Path:
        return self.folder / "simulator_stdout.log"

    @property
    def stderr_path(self) -> Path:
        return self.folder / "simulator_stderr.log"

    def solver_report(self) -> SolverReport | None:
        """None when the run used no solver, or never reached the solver (e.g. rejected settings)."""
        solver = self.resolved.get("solver_key")
        if not solver or not self.stdout_path.exists():
            return None
        return apply_recorded_status(parse_solver_log(read_text(self.stdout_path), solver), self.result)

    def progress(self) -> Progress:
        warm = (self.folder / "warmup_stdout.log").exists() and not self.stdout_path.exists()
        return parse_progress(tail_text(self.stdout_path, 400_000) if self.stdout_path.exists() else "",
                              tail_text(self.stderr_path, 20_000), warmup_active=warm)

    def elapsed_seconds(self) -> float | None:
        start = _parse_time(self.started_at)
        if start is None:
            return None
        end = _parse_time(self.finished_at) or datetime.now()
        return max(0.0, (end - start).total_seconds())


def _parse_time(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s))
    except ValueError:
        return None


def load_run(folder: Path) -> RunRecord | None:
    folder = Path(folder)
    if not RUN_ID_RE.match(folder.name) or not folder.is_dir():
        return None
    try:
        config = read_toml(folder / "config.toml") or {}
        status = read_toml(folder / "status.toml") or {}
        result = read_toml(folder / "result.toml") or {}
    except Exception:  # an unreadable record is skipped rather than breaking every page
        return None
    if not config:
        return None
    rec = RunRecord(
        run_id=folder.name, folder=folder,
        state=str(status.get("state", "unknown")), detail=str(status.get("detail", "")),
        created_at=str(config.get("created_at", "")), started_at=str(status.get("started_at", result.get("started_at", ""))),
        finished_at=str(status.get("finished_at", result.get("finished_at", ""))),
        settings=dict(config.get("settings", {})), resolved=dict(config.get("resolved", {})),
        arguments=dict(config.get("run_lego_demo_arguments", {})), result=dict(result))
    return rec


def list_runs(paths: Paths) -> list[RunRecord]:
    """All run records, newest first."""
    if not paths.runs.exists():
        return []
    runs = [r for r in (load_run(d) for d in paths.runs.iterdir() if d.is_dir()) if r is not None]
    runs.sort(key=lambda r: (r.created_at, r.run_id), reverse=True)
    return runs


# -----------------------------------------------------------------------------
# Tables and CSV
# -----------------------------------------------------------------------------

# (column, header in CSV/tables, description). Times are seconds; "sim" = simulated, "cpu" = wall-clock computer time.
COLUMNS = [
    ("run_id", "run_id", "Unique run identifier (also the run folder name)"),
    ("created_at", "created_at", "When the run was created"),
    ("status", "status", "Completed / Incomplete / Failed / Rejected / Cancelled / Timed out / Interrupted"),
    ("status_detail", "status_detail", "Explanation of the status"),
    ("label", "label", "Configuration label (seed not included, so repeated trials share a label)"),
    ("batch_id", "batch_id", "Study (batch) the run belongs to"),
    ("model", "model", "Model name"),
    ("model_key", "model_key", "Registry key in src/project_params.jl"),
    ("num_robots", "num_robots", "Number of robots"),
    ("robots_source", "robots_source", "model default or custom"),
    ("assignment_method", "assignment_method", "Task assignment method"),
    ("assignment_mode", "assignment_mode", "run_lego_demo assignment_mode"),
    ("solver", "solver", "MILP solver, or 'not used'"),
    ("optimizer_time_limit_s", "optimizer_time_limit_s", "Solver time limit [s]"),
    ("solver_termination", "solver_termination", "Solver status read from its log"),
    ("solver_gap_percent", "solver_gap_percent", "Relative MIP gap at termination [%]"),
    ("movement_profile", "movement_profile", "Movement profile"),
    ("rvo_flag", "rvo_flag", "RVO2 collision avoidance"),
    ("tangent_bug_flag", "tangent_bug_flag", "Tangent Bug site avoidance"),
    ("dispersion_flag", "dispersion_flag", "Dispersion potential field"),
    ("random_seed", "random_seed", "Seed of the simulator's random number generator (robot start positions)"),
    ("makespan_sim_s", "makespan_sim_s", "Simulated time until the model was fully built [simulated s]"),
    ("planned_makespan_sim_s", "planned_makespan_sim_s", "Schedule estimate after assignment, ignoring traffic (OptimisticMakespan) [simulated s]"),
    ("robot_min_gap_m", "robot_min_gap_m", "Smallest gap between two free robots over the run; negative means they overlapped [m]"),
    ("robot_overlap_steps", "robot_overlap_steps", "Simulation steps in which two free robots overlapped"),
    ("min_gap_m", "min_gap_m", "Smallest gap among free robots and transport teams (teams as bounding circles, so conservative) [m]"),
    ("overlap_steps", "overlap_steps", "Simulation steps with an overlap among free robots and transport teams"),
    ("position_swaps", "position_swaps", "Times two robots instantly exchanged positions"),
    ("max_speed_mps", "max_speed_mps", "Fastest agent, leaving out position swaps [m/s]"),
    ("assignment_time_cpu_s", "assignment_time_cpu_s", "Computer time spent assigning tasks (AssignmentTime) [s]"),
    ("pre_execution_time_cpu_s", "pre_execution_time_cpu_s", "Computer time from loading the model to finishing assignment (PreExecutionRuntime) [s]"),
    ("execution_time_cpu_s", "execution_time_cpu_s", "Computer time spent simulating robot motion (ExecutionRuntime) [s]"),
    ("total_time_cpu_s", "total_time_cpu_s", "Computer time for the whole run_lego_demo call [s]"),
    ("includes_compilation", "includes_compilation", "True if this was the first run of its code path in the engine session"),
    ("valid_milp_solution", "valid_milp_solution", "Whether the assignment step produced a valid solution"),
    ("num_objects", "num_objects", "Parts in the model (from the simulator)"),
    ("num_assemblies", "num_assemblies", "Assemblies in the model (from the simulator)"),
    ("max_steps", "max_steps", "Simulation step limit"),
    ("save_animation", "save_animation", "Whether a 3D animation was saved"),
    ("source_hash", "source_hash", "Hash of the simulator's source files and package versions"),
    ("git_commit", "git_commit", "Git commit of the repository, and whether src/ had uncommitted changes (+dirty)"),
    ("run_folder", "run_folder", "Run folder relative to the repository"),
    ("animation_file", "animation_file", "Animation file relative to the repository"),
]


def record_row(rec: RunRecord, paths: Paths) -> dict[str, Any]:
    s, r, res = rec.settings, rec.resolved, rec.result
    solver_rep = rec.solver_report() if rec.is_final else None
    anim = rec.animation_path
    row = {
        "run_id": rec.run_id,
        "created_at": rec.created_at,
        "status": rec.state_label,
        "status_detail": rec.detail,
        "label": rec.label,
        "batch_id": s.get("batch_id", ""),
        "model": rec.model_name,
        "model_key": s.get("model_key", ""),
        "num_robots": r.get("num_robots"),
        "robots_source": r.get("robots_source", ""),
        "assignment_method": r.get("assignment_label", ""),
        "assignment_mode": r.get("assignment_key", ""),
        "solver": r.get("solver_label", "not used"),
        "optimizer_time_limit_s": s.get("optimizer_time_limit_s") if r.get("solver_key") else None,
        "solver_termination": solver_rep.termination if solver_rep else "",
        "solver_gap_percent": solver_rep.gap_percent if solver_rep else None,
        "movement_profile": r.get("movement_label", ""),
        "rvo_flag": r.get("rvo"),
        "tangent_bug_flag": r.get("tangent_bug"),
        "dispersion_flag": r.get("dispersion"),
        "random_seed": s.get("seed"),
        "makespan_sim_s": rec.metric("makespan_s"),
        "planned_makespan_sim_s": rec.metric("optimistic_makespan_s"),
        "robot_min_gap_m": rec.metric("robot_min_gap_m"),
        "robot_overlap_steps": res.get("robot_overlap_steps"),
        "min_gap_m": rec.metric("min_gap_m"),
        "overlap_steps": res.get("overlap_steps"),
        "position_swaps": res.get("position_swaps"),
        "max_speed_mps": rec.metric("max_speed_mps"),
        "assignment_time_cpu_s": rec.metric("assignment_time_s"),
        "pre_execution_time_cpu_s": rec.metric("pre_execution_runtime_s"),
        "execution_time_cpu_s": rec.metric("execution_runtime_s"),
        "total_time_cpu_s": rec.metric("total_wall_time_s"),
        "includes_compilation": res.get("includes_compilation"),
        "valid_milp_solution": res.get("valid_milp_solution") if r.get("solver_key") else None,
        "num_objects": res.get("num_objects"),
        "num_assemblies": res.get("num_assemblies"),
        "max_steps": s.get("max_steps"),
        "save_animation": s.get("save_animation"),
        "source_hash": rec.source_hash or "",
        "git_commit": str(res.get("software", {}).get("git_commit", "")) +
                      ("+dirty" if res.get("software", {}).get("git_dirty") else ""),
        "run_folder": paths.display(rec.folder),
        "animation_file": paths.display(anim) if anim else "",
    }
    return row


def records_to_frame(records: list[RunRecord], paths: Paths):
    import pandas as pd
    rows = [record_row(r, paths) for r in records]
    df = pd.DataFrame(rows, columns=[c[0] for c in COLUMNS])
    for c in ("num_robots", "optimizer_time_limit_s", "solver_gap_percent", "random_seed", "makespan_sim_s",
              "planned_makespan_sim_s", "robot_min_gap_m", "robot_overlap_steps", "min_gap_m", "overlap_steps",
              "position_swaps", "max_speed_mps", "assignment_time_cpu_s", "pre_execution_time_cpu_s", "execution_time_cpu_s",
              "total_time_cpu_s", "num_objects", "num_assemblies", "max_steps"):
        df[c] = pd.to_numeric(df[c], errors="coerce")   # missing values become blank cells, never "None" or 0
    return df


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return ""
        return repr(round(v, 6))
    return str(v)


def to_csv_bytes(records: list[RunRecord], paths: Paths) -> bytes:
    """CSV (UTF-8 with BOM so Excel detects the encoding). Empty cell = not available."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow([c[1] for c in COLUMNS])
    for rec in records:
        row = record_row(rec, paths)
        w.writerow([_cell(row[c[0]]) for c in COLUMNS])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def unique_export_path(paths: Paths, stem: str) -> Path:
    """A new file name in the exports folder that does not exist yet (exports are never overwritten)."""
    paths.exports.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("_") or "export"
    base = f"{safe}_{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    p = paths.exports / f"{base}.csv"
    i = 2
    while p.exists():
        p = paths.exports / f"{base}_{i}.csv"
        i += 1
    return p


def save_export(records: list[RunRecord], paths: Paths, stem: str) -> Path:
    p = unique_export_path(paths, stem)
    with open(p, "xb") as f:      # "x": fail rather than replace an existing file
        f.write(to_csv_bytes(records, paths))
    return p
