"""The simulation engine: one persistent Julia process running julia_worker.jl.

Loading and compiling the simulator takes one to two minutes, so the engine is kept
running between runs and executes one run at a time from a queue. Cancelling or
timing out a run stops the engine process (Julia cannot safely abort a computation in
progress); the next run starts a fresh engine. The engine also stops when the
dashboard process ends: on Windows through a Job Object, everywhere through a
parent-process watchdog inside the worker.
"""
from __future__ import annotations

import atexit
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .catalog import ASSIGNMENT_TAGS
from .paths import WORKER_SCRIPT, Paths, find_julia, julia_child_env
from .results import ACTIVE_STATES, FINAL_STATES, RUN_ID_RE, tail_text
from .tomlio import read_toml, write_toml_atomic
from .validation import Resolved

IDLE_STOP_MIN = float(os.environ.get("CONSTRUCTIONLAB_ENGINE_IDLE_MIN", "60"))
MAX_QUEUE = 100
KILL_WAIT_S = 30


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


# -----------------------------------------------------------------------------
# Process helpers
# -----------------------------------------------------------------------------

def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        h = k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5   # access denied: exists
        code = wintypes.DWORD()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == 259     # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


class _WindowsJob:
    """Job object with KILL_ON_JOB_CLOSE: the OS ends the engine when the dashboard process ends."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes, self.wintypes = ctypes, wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.k32 = k32

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount",
                                                          "OtherOperationCount", "ReadTransferCount",
                                                          "WriteTransferCount", "OtherTransferCount")]

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class EXTENDED(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        self.handle = k32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError("CreateJobObject failed")
        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = 0x2000   # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError("SetInformationJobObject failed")

    def assign(self, proc: subprocess.Popen) -> None:
        if not self.k32.AssignProcessToJobObject(self.handle, int(proc._handle)):
            raise OSError("AssignProcessToJobObject failed")

    def terminate(self) -> None:
        self.k32.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        if self.handle:
            self.k32.CloseHandle(self.handle)
            self.handle = None


# -----------------------------------------------------------------------------
# Engine manager
# -----------------------------------------------------------------------------

@dataclass
class EngineSnapshot:
    state: str                 # stopped | starting | ready | busy | error | read_only
    pid: int | None
    active_run: str | None
    queue: list[str]
    started_at: float | None
    ready_at: float | None
    last_error: str
    julia_path: str
    julia_source: str
    runs_completed: int
    read_only_reason: str

    @property
    def running(self) -> bool:
        return self.state in ("starting", "ready", "busy")


class EngineManager:
    def __init__(self, paths: Paths):
        self.paths = paths
        paths.ensure()
        (paths.engine / "inbox").mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.proc: subprocess.Popen | None = None
        self._job: _WindowsJob | None = None
        self._log_handle = None
        self.log_path: Path | None = None
        self.state = "stopped"
        self.last_error = ""
        self.started_at: float | None = None
        self.ready_at: float | None = None
        self.queue: deque[str] = deque()
        self.active: str | None = None
        self.active_dispatched: float | None = None
        self.runs_completed = 0
        self.last_activity = time.time()
        self.read_only_reason = ""
        self._stop_event = threading.Event()
        self._claim_ownership()
        if not self.read_only_reason:
            self._recover_interrupted_runs()
        self._thread = threading.Thread(target=self._supervise, name="constructionlab-engine", daemon=True)
        self._thread.start()
        atexit.register(self.shutdown)

    # --- ownership of the results folder -------------------------------------------------
    def _claim_ownership(self) -> None:
        owner = self.paths.engine / "owner.toml"
        info = read_toml(owner) or {}
        pid = int(info.get("pid", 0) or 0)
        if pid and pid != os.getpid() and pid_alive(pid):
            self.read_only_reason = (f"Another ConstructionLab dashboard (process {pid}) is using this results folder, "
                                     "so this window cannot start simulations. Close the other dashboard first. If no "
                                     "other dashboard is running, delete results/dashboard/engine/owner.toml.")
            self.state = "read_only"
            return
        write_toml_atomic(owner, {"pid": os.getpid(), "since": now_iso()})

    def _recover_interrupted_runs(self) -> None:
        """Runs left queued/running by a previous dashboard session can no longer finish."""
        if not self.paths.runs.exists():
            return
        for d in self.paths.runs.iterdir():
            st = read_toml(d / "status.toml") if d.is_dir() else None
            if st and st.get("state") in ACTIVE_STATES:
                was_running = st.get("state") == "running"
                st["state"] = "interrupted"
                st["detail"] = ("The dashboard stopped before this run finished. Partial output is kept in the run "
                                "folder." if was_running else "The dashboard stopped before this queued run started.")
                st["finished_at"] = now_iso()
                write_toml_atomic(d / "status.toml", st)
        for f in (self.paths.engine / "inbox").glob("*.toml"):
            f.unlink(missing_ok=True)

    # --- public API ------------------------------------------------------------------------
    def snapshot(self) -> EngineSnapshot:
        with self._lock:
            julia = find_julia(self.paths.repo)
            return EngineSnapshot(
                state=self.state, pid=self.proc.pid if self.proc and self.proc.poll() is None else None,
                active_run=self.active, queue=list(self.queue), started_at=self.started_at, ready_at=self.ready_at,
                last_error=self.last_error, julia_path=str(julia.path or ""), julia_source=julia.source,
                runs_completed=self.runs_completed, read_only_reason=self.read_only_reason)

    def start(self) -> None:
        with self._lock:
            if self.read_only_reason:
                return
            if self.proc is not None and self.proc.poll() is None:
                return
            julia = find_julia(self.paths.repo)
            if julia.path is None:
                self.state, self.last_error = "error", ("Julia was not found. Install Julia (see dashboard/README.md) or "
                                                        "set CONSTRUCTIONLAB_JULIA to the julia executable.")
                return
            inbox = self.paths.engine / "inbox"
            for f in inbox.glob("*.toml"):
                f.unlink(missing_ok=True)
            (self.paths.engine / "engine.toml").unlink(missing_ok=True)
            self._rotate_logs()
            self.log_path = self.paths.engine / f"engine_{datetime.now():%Y%m%d-%H%M%S}.log"
            self._log_handle = open(self.log_path, "w", encoding="utf-8")
            cmd = [str(julia.path), f"--project={self.paths.repo}", "--threads=2", "--startup-file=no",
                   "--history-file=no", "--color=no", str(WORKER_SCRIPT), "serve",
                   "--repo", str(self.paths.repo), "--engine-dir", str(self.paths.engine),
                   "--runs-dir", str(self.paths.runs), "--parent-pid", str(os.getpid())]
            kwargs = dict(stdout=self._log_handle, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                          cwd=str(self.paths.repo), env=julia_child_env())
            if os.name == "nt":
                kwargs["creationflags"] = 0x08000000           # CREATE_NO_WINDOW
            else:
                kwargs["start_new_session"] = True
            try:
                self.proc = subprocess.Popen(cmd, **kwargs)
            except OSError as e:
                self.state, self.last_error = "error", f"Could not start Julia: {e}"
                self._close_log()
                return
            if os.name == "nt":
                try:
                    self._job = _WindowsJob()
                    self._job.assign(self.proc)
                except OSError:
                    self._job = None   # the worker's own parent watchdog still applies
            self.state, self.last_error = "starting", ""
            self.started_at, self.ready_at = time.time(), None
            self.last_activity = time.time()

    def stop(self) -> bool:
        """Stop the engine. Refused while a run is active (cancel the run instead)."""
        with self._lock:
            if self.active:
                return False
            self._kill_process()
            return True

    def submit(self, items: list[Resolved]) -> list[str]:
        """Create run folders (state "queued") and queue them. Returns the new run IDs."""
        with self._lock:
            if self.read_only_reason:
                raise RuntimeError(self.read_only_reason)
            if len(self.queue) + len(items) > MAX_QUEUE:
                raise RuntimeError(f"At most {MAX_QUEUE} runs can wait in the queue.")
            ids = []
            for r in items:
                run_id, run_dir = self._new_run_folder(r)
                write_toml_atomic(run_dir / "config.toml", self._config_record(r, run_id, run_dir))
                write_toml_atomic(run_dir / "status.toml", {"run_id": run_id, "state": "queued",
                                                            "detail": "Waiting for the simulation engine.",
                                                            "created_at": now_iso()})
                self.queue.append(run_id)
                ids.append(run_id)
            self.last_activity = time.time()
        self._tick()
        return ids

    def cancel(self, run_id: str) -> tuple[bool, str]:
        with self._lock:
            if run_id in self.queue:
                self.queue.remove(run_id)
                self._finalize(run_id, "canceled", "Cancelled before it started.")
                return True, "The queued run was cancelled."
            if run_id == self.active:
                ok = self._kill_process(final_state="canceled",
                                        detail="Cancelled by the user while running. The simulation engine was "
                                               "stopped; partial output is kept in the run folder.")
                if ok:
                    return True, "The run was stopped and the engine process has exited."
                return False, "The engine process did not exit yet; the run is not reported as cancelled."
            return False, "This run is not queued or running."

    def cancel_queue(self, batch_id: str | None = None) -> int:
        with self._lock:
            n = 0
            for run_id in list(self.queue):
                cfg = read_toml(self.paths.runs / run_id / "config.toml") or {}
                if batch_id is None or cfg.get("settings", {}).get("batch_id") == batch_id:
                    self.queue.remove(run_id)
                    self._finalize(run_id, "canceled", "Cancelled before it started.")
                    n += 1
            return n

    def engine_log_tail(self, max_bytes: int = 20_000) -> str:
        return tail_text(self.log_path, max_bytes) if self.log_path else ""

    def shutdown(self) -> None:
        self._stop_event.set()
        with self._lock:
            if self.active:
                self._kill_process(final_state="interrupted", detail="The dashboard was closed during this run.")
            else:
                self._kill_process()
            for run_id in list(self.queue):
                self._finalize(run_id, "interrupted", "The dashboard was closed before this queued run started.")
            self.queue.clear()
            owner = self.paths.engine / "owner.toml"
            info = read_toml(owner) or {}
            if not self.read_only_reason and int(info.get("pid", 0) or 0) == os.getpid():
                owner.unlink(missing_ok=True)

    # --- internals -------------------------------------------------------------------------
    def _new_run_folder(self, r: Resolved) -> tuple[str, Path]:
        tag = ASSIGNMENT_TAGS[r.assignment.key]
        if r.solver:
            tag += "-" + r.solver.key
        for _ in range(20):
            run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{r.model.key}-{tag}-{secrets.token_hex(2)}"
            run_dir = self.paths.runs / run_id
            try:
                run_dir.mkdir(parents=False, exist_ok=False)   # never reuse an existing folder
                return run_id, run_dir
            except FileExistsError:
                continue
        raise RuntimeError("Could not create a unique run folder.")

    def _config_record(self, r: Resolved, run_id: str, run_dir: Path) -> dict:
        c = r.config
        return {
            "run_id": run_id,
            "created_at": now_iso(),
            "settings": {k: v for k, v in c.to_dict().items() if v is not None},
            "resolved": {
                "label": r.label, "model_key": r.model.key, "model_name": r.model.name,
                "ldraw_file": r.model.file_name, "model_scale": r.model.model_scale,
                "num_robots": r.num_robots, "robots_source": r.robots_source, "default_robots": r.model.default_robots,
                "assignment_key": r.assignment.key, "assignment_label": r.assignment.label,
                "solver_key": r.solver.key if r.solver else "", "solver_label": r.solver.label if r.solver else "not used",
                "movement_key": r.movement.key, "movement_label": r.movement.label,
                "rvo": r.movement.rvo, "tangent_bug": r.movement.tangent_bug, "dispersion": r.movement.dispersion,
                "timeout_min": r.timeout_min, "live_preview_interval": r.live_interval,
            },
            "run_lego_demo_arguments": r.demo_arguments(),
            "job": r.job_request(run_id, str(run_dir)),
        }

    def _finalize(self, run_id: str, state: str, detail: str) -> None:
        if not RUN_ID_RE.match(run_id):
            return
        p = self.paths.runs / run_id / "status.toml"
        st = read_toml(p) or {"run_id": run_id}
        if st.get("state") in FINAL_STATES:   # the worker already recorded the outcome; never overwrite it
            return
        st.update({"state": state, "detail": detail, "finished_at": now_iso()})
        write_toml_atomic(p, st)

    def _dispatch(self, run_id: str) -> None:
        cfg = read_toml(self.paths.runs / run_id / "config.toml") or {}
        job = cfg.get("job")
        if not job:
            self._finalize(run_id, "failed", "The run's configuration file is missing or unreadable.")
            return
        inbox = self.paths.engine / "inbox"
        write_toml_atomic(inbox / f"{int(time.time() * 1000)}_{run_id}.toml", job)
        self.active, self.active_dispatched = run_id, time.time()
        st = read_toml(self.paths.runs / run_id / "status.toml") or {}
        st.update({"detail": "Sent to the simulation engine."})
        write_toml_atomic(self.paths.runs / run_id / "status.toml", st)

    def _kill_process(self, final_state: str | None = None, detail: str = "") -> bool:
        """Stop the engine process tree and wait until it has exited. Returns True when confirmed."""
        proc = self.proc
        if proc is None:
            return True
        if proc.poll() is None:
            try:
                if self._job is not None:
                    self._job.terminate()
                elif os.name == "nt":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=30)
                else:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (OSError, subprocess.TimeoutExpired):
                pass
            try:
                proc.wait(timeout=KILL_WAIT_S)
            except subprocess.TimeoutExpired:
                self.last_error = f"The engine process {proc.pid} did not exit within {KILL_WAIT_S} s."
                self.state = "error"
                return False
        if final_state and self.active:
            self._finalize(self.active, final_state, detail)
            self.active = None
        self.proc = None
        if self._job is not None:
            self._job.close()
            self._job = None
        self._close_log()
        self.state = "stopped"
        self.started_at = self.ready_at = None
        (self.paths.engine / "engine.toml").unlink(missing_ok=True)
        return True

    def _close_log(self) -> None:
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except OSError:
                pass
            self._log_handle = None

    def _rotate_logs(self, keep: int = 10) -> None:
        logs = sorted(self.paths.engine.glob("engine_*.log"))
        for old in logs[:-keep]:
            try:
                old.unlink()
            except OSError:
                pass

    def _supervise(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as e:   # keep supervising; surface the problem in the UI
                self.last_error = f"Supervisor error: {e}"
            self._stop_event.wait(0.5)

    def _tick(self) -> None:
        with self._lock:
            if self.read_only_reason:
                return
            proc = self.proc
            # Engine process ended on its own?
            if proc is not None and proc.poll() is not None:
                code = proc.returncode
                if self.active:
                    self._finalize(self.active, "failed",
                                   f"The simulation engine stopped unexpectedly (exit code {code}) during this run. "
                                   "See the engine log on the System Diagnostics page.")
                    self.active = None
                if self.state == "starting":
                    tail = self.engine_log_tail(3000).strip().splitlines()[-6:]
                    self.last_error = "The engine failed to start. " + " ".join(tail)
                self.proc = None
                if self._job is not None:
                    self._job.close()
                    self._job = None
                self._close_log()
                self.state = "error" if self.last_error else "stopped"
                self.started_at = self.ready_at = None
                proc = None
            if proc is not None:
                est = read_toml(self.paths.engine / "engine.toml") or {}
                if int(est.get("pid", 0) or 0) == proc.pid:
                    if est.get("state") == "ready":
                        self.state = "ready"
                        self.ready_at = self.ready_at or time.time()
                    elif est.get("state") == "busy":
                        self.state = "busy"
                    self.runs_completed = int(est.get("runs_completed", 0) or 0)
            # Active run finished or exceeded its time limit?
            if self.active:
                st = read_toml(self.paths.runs / self.active / "status.toml") or {}
                if st.get("state") in FINAL_STATES:
                    self.active = None
                    self.last_activity = time.time()
                else:
                    cfg = read_toml(self.paths.runs / self.active / "config.toml") or {}
                    timeout_s = 60 * float(cfg.get("resolved", {}).get("timeout_min", 0) or 0)   # 0 = no limit
                    if timeout_s and self.active_dispatched and time.time() - self.active_dispatched > timeout_s:
                        self._kill_process(final_state="timed_out",
                                           detail=f"Stopped after exceeding the wall-clock limit of "
                                                  f"{timeout_s / 60:.0f} min. Partial output is kept in the run folder.")
            # Start the engine or dispatch the next queued run.
            if not self.active and self.queue:
                if self.proc is None and self.state != "error":
                    self.start()
                elif self.proc is not None and self.state == "ready":
                    self._dispatch(self.queue.popleft())
            # Stop an idle engine after a while to free memory.
            if (self.proc is not None and self.state == "ready" and not self.active and not self.queue
                    and time.time() - self.last_activity > IDLE_STOP_MIN * 60):
                self._kill_process()

    def clear_error(self) -> None:
        with self._lock:
            if self.state == "error":
                self.state, self.last_error = "stopped", ""


_REGISTRY_ATTR = "_constructionlab_engines"


def get_engine(paths: Paths) -> EngineManager:
    """One manager per results folder per process (survives Streamlit module reloads)."""
    registry = getattr(sys, _REGISTRY_ATTR, None)
    if registry is None:
        registry = {}
        setattr(sys, _REGISTRY_ATTR, registry)
    key = str(paths.results_root.resolve())
    mgr = registry.get(key)
    if mgr is None:
        mgr = EngineManager(paths)
        registry[key] = mgr
    return mgr
