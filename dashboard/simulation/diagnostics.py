"""Environment diagnostics: Julia-side checks (run by julia_worker.jl in `check` mode)
plus dashboard-side checks. Results are cached so pages can show them without waiting."""
from __future__ import annotations

import importlib.metadata as md
import os
import platform
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .paths import WORKER_SCRIPT, Paths, find_julia, julia_child_env
from .tomlio import read_toml

STATUS_LABELS = {"ok": "Available", "warn": "Needs attention", "fail": "Missing", "unavailable": "Optional, unavailable",
                 "info": "Information", "unchecked": "Not checked"}


@dataclass
class Check:
    id: str
    label: str
    category: str      # required | optional
    status: str        # ok | warn | fail | unavailable | info | unchecked
    detail: str
    action: str = ""

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)


@dataclass
class Report:
    checks: list[Check]
    generated_at: str | None
    julia_report: dict | None
    error: str = ""

    def status_of(self, check_id: str) -> str | None:
        for c in self.checks:
            if c.id == check_id:
                return c.status
        return None

    def env_status(self) -> dict[str, str]:
        """Statuses used by settings validation (only checks that were actually run)."""
        return {c.id: c.status for c in self.checks if c.status != "unchecked"}

    @property
    def required_ok(self) -> bool:
        return all(c.status in ("ok", "info") for c in self.checks if c.category == "required")

    @property
    def checked(self) -> bool:
        return self.julia_report is not None


def _cache(paths: Paths) -> Path:
    return paths.cache / "diagnostics.toml"


def run_julia_checks(paths: Paths, timeout_s: int = 600) -> tuple[bool, str]:
    """Run the Julia-side checks now (about 10–60 s, depending on whether packages are precompiled)."""
    paths.ensure()
    julia = find_julia(paths.repo)
    if julia.path is None:
        return False, "Julia was not found."
    out = _cache(paths)
    try:
        proc = subprocess.run(
            [str(julia.path), f"--project={paths.repo}", "--startup-file=no", "--history-file=no", "--color=no",
             str(WORKER_SCRIPT), "check", "--repo", str(paths.repo), "--out", str(out)],
            capture_output=True, text=True, timeout=timeout_s, env=julia_child_env(), cwd=str(paths.repo))
    except subprocess.TimeoutExpired:
        return False, f"The Julia checks did not finish within {timeout_s} s."
    except OSError as e:
        return False, f"Julia could not be started: {e}"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-8:]
        return False, "The Julia checks failed:\n" + "\n".join(tail)
    return True, ""


def _pkg_version(name: str) -> str:
    try:
        return md.version(name)
    except md.PackageNotFoundError:
        return "not installed"


def dashboard_checks(paths: Paths) -> list[Check]:
    checks: list[Check] = []
    julia = find_julia(paths.repo)
    if julia.path is None:
        checks.append(Check("julia_exe", "Julia executable", "required", "fail", "Julia was not found.",
                            "Install Julia 1.10 with juliaup (dashboard/README.md), or set the environment variable "
                            "CONSTRUCTIONLAB_JULIA to the full path of julia."))
    else:
        checks.append(Check("julia_exe", "Julia executable", "required", "ok", f"{julia.path} (found via {julia.source})"))
    writable = True
    try:
        paths.ensure()
        probe = paths.results_root / f".write_test_{os.getpid()}"
        probe.write_text("ok")
        probe.unlink()
    except OSError:
        writable = False
    checks.append(Check("results_dir", "Results folder", "required", "ok" if writable else "fail",
                        f"{paths.display(paths.results_root)} ({'writable' if writable else 'not writable'})",
                        "" if writable else "Make the results folder writable or start the dashboard as a user who can write there."))
    versions = ", ".join(f"{n} {_pkg_version(n)}" for n in ("streamlit", "pandas", "altair"))
    checks.append(Check("dashboard_python", "Dashboard Python packages", "required", "ok",
                        f"Python {platform.python_version()} · {versions}"))
    return checks


def load_report(paths: Paths) -> Report:
    checks = dashboard_checks(paths)
    data = read_toml(_cache(paths)) if _cache(paths).exists() else None
    if data:
        for c in data.get("checks", []):
            checks.append(Check(str(c.get("id")), str(c.get("label")), str(c.get("category", "required")),
                                str(c.get("status")), str(c.get("detail", "")), str(c.get("action", ""))))
        julia = find_julia(paths.repo)
        expected = julia.expected_version
        found = data.get("julia_version")
        if expected and found and found != expected:
            checks.append(Check("julia_version", "Julia version", "required", "warn",
                                f"Julia {found} is used, but Manifest.toml was created with Julia {expected}.",
                                f"Install Julia {expected} (juliaup add {expected}) so package versions match."))
    else:
        for cid, label, cat in (("rvo2", "RVO2 collision-avoidance module", "required"),
                                ("ldraw", "LDraw Parts Library", "required"),
                                ("solver_highs", "Solver: HiGHS", "required"),
                                ("solver_glpk", "Solver: GLPK", "optional"),
                                ("solver_gurobi", "Solver: Gurobi", "optional")):
            checks.append(Check(cid, label, cat, "unchecked", "Run the system checks to test this."))
    return Report(checks=checks, generated_at=(data or {}).get("generated_at"), julia_report=data)


def report_age_text(report: Report) -> str:
    if not report.generated_at:
        return "never"
    try:
        t = datetime.fromisoformat(report.generated_at)
    except ValueError:
        return report.generated_at
    mins = (datetime.now() - t).total_seconds() / 60
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins:.0f} min ago"
    if mins < 48 * 60:
        return f"{mins / 60:.0f} h ago"
    return t.strftime("%Y-%m-%d %H:%M")
