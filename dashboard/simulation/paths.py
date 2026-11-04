"""Where things live: the repository, the dashboard's results folder, and the Julia executable.

Nothing here is specific to one computer. The Julia executable is found from, in order:
  1. the CONSTRUCTIONLAB_JULIA environment variable,
  2. a juliaup installation matching the Julia version recorded in Manifest.toml,
  3. `julia` on the PATH.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_DIR = REPO_ROOT / "dashboard"
WORKER_SCRIPT = DASHBOARD_DIR / "simulation" / "julia_worker.jl"


@dataclass(frozen=True)
class Paths:
    """Folders used by the dashboard. All generated output stays under `results_root`."""

    repo: Path
    results_root: Path

    @classmethod
    def default(cls) -> "Paths":
        """<repo>/results/dashboard, or CONSTRUCTIONLAB_RESULTS_DIR if set (used by the tests)."""
        override = os.environ.get("CONSTRUCTIONLAB_RESULTS_DIR", "").strip()
        root = Path(override) if override else REPO_ROOT / "results" / "dashboard"
        return cls(repo=REPO_ROOT, results_root=root)

    @property
    def runs(self) -> Path:
        return self.results_root / "runs"

    @property
    def engine(self) -> Path:
        return self.results_root / "engine"

    @property
    def exports(self) -> Path:
        return self.results_root / "exports"

    @property
    def deleted(self) -> Path:
        return self.results_root / "deleted_runs"

    @property
    def cache(self) -> Path:
        return self.results_root / "cache"

    def ensure(self) -> None:
        for p in (self.runs, self.engine, self.exports, self.deleted, self.cache):
            p.mkdir(parents=True, exist_ok=True)

    def display(self, p: Path) -> str:
        """Path relative to the repository (or to the results folder), never an absolute path,
        so exported tables do not contain user names or computer-specific folders."""
        q = Path(p).resolve()
        for base, prefix in ((self.repo.resolve(), ""), (self.results_root.resolve(), "<results>/")):
            try:
                return prefix + q.relative_to(base).as_posix()
            except ValueError:
                continue
        return q.name


@dataclass(frozen=True)
class JuliaInfo:
    path: Path | None
    source: str
    expected_version: str | None


def manifest_julia_version(repo: Path = REPO_ROOT) -> str | None:
    manifest = repo / "Manifest.toml"
    if not manifest.exists():
        return None
    try:
        with open(manifest, "rb") as f:
            return tomllib.load(f).get("julia_version")
    except (OSError, tomllib.TOMLDecodeError):
        return None


def _version_tuple(name: str) -> tuple[int, ...]:
    m = re.match(r"julia-(\d+)\.(\d+)\.(\d+)", name)
    return tuple(int(x) for x in m.groups()) if m else (0,)


def find_julia(repo: Path = REPO_ROOT) -> JuliaInfo:
    expected = manifest_julia_version(repo)
    env = os.environ.get("CONSTRUCTIONLAB_JULIA", "").strip()
    if env:
        p = Path(env)
        return JuliaInfo(p if p.is_file() else None, "CONSTRUCTIONLAB_JULIA environment variable", expected)

    exe = "julia.exe" if os.name == "nt" else "julia"
    juliaup = Path.home() / ".julia" / "juliaup"
    if juliaup.is_dir():
        candidates = [d for d in juliaup.iterdir() if d.is_dir() and d.name.startswith("julia-") and (d / "bin" / exe).is_file()]
        if expected:
            exact = [d for d in candidates if d.name.startswith(f"julia-{expected}+") or d.name == f"julia-{expected}"]
            if exact:
                return JuliaInfo(exact[0] / "bin" / exe, f"juliaup (Julia {expected}, as recorded in Manifest.toml)", expected)
        if candidates:
            best = max(candidates, key=lambda d: _version_tuple(d.name))
            return JuliaInfo(best / "bin" / exe, "juliaup (newest installed version)", expected)

    found = shutil.which("julia")
    if found:
        return JuliaInfo(Path(found), "julia on the PATH", expected)
    return JuliaInfo(None, "not found", expected)


def julia_version(path: Path) -> str | None:
    try:
        out = subprocess.run([str(path), "--version"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"(\d+\.\d+\.\d+)", out.stdout)
    return m.group(1) if m else None


def julia_child_env() -> dict[str, str]:
    """Environment for Julia processes.

    PyCall inside Julia must use its own configured Python (the one with RVO2), not
    the Python that runs this dashboard, so Python-specific variables are removed.
    """
    env = dict(os.environ)
    for k in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "VIRTUAL_ENV", "PYTHONEXECUTABLE"):
        env.pop(k, None)
    return env
