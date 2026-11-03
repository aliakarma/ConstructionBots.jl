"""Engine manager behaviour that does not need Julia: queueing, cancelling, ownership, recovery."""
import os
import time

import pytest

from conftest import ENV_OK
from simulation import engine as engine_mod
from simulation.engine import EngineManager
from simulation.results import load_run
from simulation.tomlio import read_toml, write_toml_atomic
from simulation.validation import RunConfig, validate


@pytest.fixture
def no_julia(monkeypatch, tmp_path):
    monkeypatch.setenv("CONSTRUCTIONLAB_JULIA", str(tmp_path / "no-julia-here.exe"))


def _resolved(catalog, **kw):
    v = validate(RunConfig(**kw), catalog, ENV_OK)
    assert v.ok, v.errors
    return v.resolved


def test_submit_creates_unique_queued_runs_with_exact_arguments(tmp_paths, catalog, no_julia):
    eng = EngineManager(tmp_paths)
    try:
        ids = eng.submit([_resolved(catalog), _resolved(catalog, seed=2)])
        assert len(set(ids)) == 2
        time.sleep(1.0)
        for rid in ids:
            rec = load_run(tmp_paths.runs / rid)
            assert rec is not None and rec.state == "queued"
            cfg = read_toml(tmp_paths.runs / rid / "config.toml")
            assert cfg["job"]["model_key"] == "tractor" and cfg["run_lego_demo_arguments"]["ldraw_file"] == "tractor.mpd"
        # Without Julia the engine reports an error instead of pretending to run.
        snap = eng.snapshot()
        assert snap.state == "error" and "Julia was not found" in snap.last_error
        ok, _ = eng.cancel(ids[0])
        assert ok and load_run(tmp_paths.runs / ids[0]).state == "canceled"
        assert eng.cancel_queue() == 1
        assert load_run(tmp_paths.runs / ids[1]).state == "canceled"
    finally:
        eng.shutdown()


def test_final_states_are_never_overwritten(tmp_paths, catalog, no_julia):
    eng = EngineManager(tmp_paths)
    try:
        [rid] = eng.submit([_resolved(catalog)])
        write_toml_atomic(tmp_paths.runs / rid / "status.toml", {"state": "success", "detail": "done"})
        eng._finalize(rid, "canceled", "should not replace a real outcome")
        assert load_run(tmp_paths.runs / rid).state == "success"
    finally:
        eng.shutdown()


def test_interrupted_runs_are_marked_on_startup(tmp_paths, catalog, no_julia):
    eng = EngineManager(tmp_paths)
    [rid] = eng.submit([_resolved(catalog)])
    eng._stop_event.set()
    eng.queue.clear()            # simulate a crash: the run stays "queued" on disk
    write_toml_atomic(tmp_paths.engine / "owner.toml", {"pid": 0})
    eng2 = EngineManager(tmp_paths)
    try:
        rec = load_run(tmp_paths.runs / rid)
        assert rec.state == "interrupted"
    finally:
        eng2.shutdown()


def test_second_dashboard_is_read_only(tmp_paths, catalog, no_julia):
    write_toml_atomic(tmp_paths.engine / "owner.toml", {"pid": os.getppid()})   # a live process that is not us
    eng = EngineManager(tmp_paths)
    try:
        assert eng.snapshot().state == "read_only"
        with pytest.raises(RuntimeError):
            eng.submit([_resolved(catalog)])
    finally:
        eng.shutdown()
    assert read_toml(tmp_paths.engine / "owner.toml")["pid"] == os.getppid()   # the owner's claim is untouched


def test_pid_alive():
    assert engine_mod.pid_alive(os.getpid())
    assert not engine_mod.pid_alive(0)
