"""The local viewer server serves only known animation files of known runs."""
import http.client
import json
import os
import time

import pytest

from simulation.artifact_server import ArtifactServer, animation_files
from simulation.tomlio import write_toml_atomic

RUN = "20261018-120000-tractor-greedy-abcd"
HTML = "<!DOCTYPE html><html><body>scene</body></html>\n    "


@pytest.fixture
def server(tmp_paths):
    d = tmp_paths.runs / RUN
    out = d / "simulator_output" / "greedy_RVO_Dispersion_TangentBug"
    out.mkdir(parents=True)
    write_toml_atomic(d / "config.toml", {"run_id": RUN, "created_at": "2026-10-18T12:00:00",
                                          "settings": {"save_animation": True}, "resolved": {"model_name": "Tractor",
                                                                                             "live_preview_interval": 60}})
    write_toml_atomic(d / "status.toml", {"state": "running"})
    old = time.time() - 30
    for name in ("20261018_120001_visualization_preprocessing.html", "20261018_120001_visualization_99.html"):
        (out / name).write_text(HTML)
        os.utime(out / name, (old, old))
    (out / "20261018_120001_visualization_150.html").write_text("<html><body>half writ")   # incomplete
    (out / "20261018_120001_stats.toml").write_text("x = 1\n")
    (tmp_paths.repo / "README.md").exists()
    srv = ArtifactServer(tmp_paths)
    yield srv, tmp_paths, out
    srv.shutdown()


def get(srv, path, method="GET", host=None):
    c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
    c.request(method, path, headers={"Host": host or f"127.0.0.1:{srv.port}"})
    r = c.getresponse()
    return r.status, r.read(), dict(r.getheaders())


def test_viewer_state_lists_only_complete_snapshots(server):
    srv, paths, out = server
    status, body, _ = get(srv, f"/api/runs/{RUN}/viewer")
    st = json.loads(body)
    assert status == 200 and st["state"] == "running" and st["final"] is None
    assert [s["step"] for s in st["snapshots"]] == [None, 99]      # the half-written file is not offered


def test_final_animation_is_served_with_safe_headers(server):
    srv, paths, out = server
    (out / "20261018_120001_visualization.html").write_text(HTML)
    write_toml_atomic(paths.runs / RUN / "status.toml", {"state": "success"})
    st = json.loads(get(srv, f"/api/runs/{RUN}/viewer")[1])
    assert st["final"]["name"] == "20261018_120001_visualization.html"
    status, body, headers = get(srv, st["final"]["url"])
    assert status == 200 and b"scene" in body
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors" in headers["Content-Security-Policy"] and "localhost" in headers["Content-Security-Policy"]
    status, body, _ = get(srv, f"/player/{RUN}")
    assert status == 200 and json.dumps(RUN).encode() in body


@pytest.mark.parametrize("path", [
    "/runs/../../README.md", f"/runs/{RUN}/file/..%2F..%2Fconfig.toml", f"/runs/{RUN}/file/20261018_120001_stats.toml",
    f"/runs/{RUN}/file/config.toml", "/runs/nope/file/20261018_120001_visualization.html", "/etc/passwd",
    f"/player/..%2F{RUN}", "/api/runs/nope/viewer", "/player/does-not-exist",
])
def test_nothing_else_is_reachable(server, path):
    srv, _, _ = server
    assert get(srv, path)[0] == 404


def test_foreign_host_and_writes_are_refused(server):
    srv, _, _ = server
    assert get(srv, f"/player/{RUN}", host="evil.example:80")[0] == 403
    assert get(srv, f"/player/{RUN}", method="POST")[0] == 405
    assert get(srv, f"/player/{RUN}", method="DELETE")[0] == 405


def test_animation_files_ignores_unrelated_names(tmp_path):
    out = tmp_path / "simulator_output" / "x"
    out.mkdir(parents=True)
    (out / "evil.html").write_text(HTML)
    assert animation_files(tmp_path, settle=False) == (None, [])
