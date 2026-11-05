"""Which Julia the dashboard picks."""
import os

from simulation.paths import find_julia


def test_recorded_julia_in_programs_beats_a_newer_one_on_the_path(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Manifest.toml").write_text('julia_version = "1.10.12"\n')
    exe = "julia.exe" if os.name == "nt" else "julia"
    recorded = tmp_path / "Programs" / "Julia-1.10.12" / "bin" / exe
    recorded.parent.mkdir(parents=True)
    recorded.write_text("")
    newer = tmp_path / "Julia-1.13.2" / "bin" / exe
    newer.parent.mkdir(parents=True)
    newer.write_text("")
    monkeypatch.delenv("CONSTRUCTIONLAB_JULIA", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("PATH", str(newer.parent))
    assert find_julia(repo).path == recorded
