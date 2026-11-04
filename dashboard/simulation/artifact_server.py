"""Local viewer server for simulation animations.

The simulator saves animations as self-contained MeshCat HTML files (all JavaScript and
scene data inline). This server shows them inside the dashboard through a small player
page. It listens on 127.0.0.1 only, answers GET requests only, and serves nothing but:

  /player/<run_id>                 the player page for one run
  /api/runs/<run_id>/viewer        JSON: which animation files of that run are ready
  /runs/<run_id>/file/<name>       one animation file of that run, validated by name pattern

Run IDs and file names are checked against strict patterns and every resolved path must
lie inside the run's own folder, so no other file on the computer can be reached.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .paths import Paths
from .results import RUN_ID_RE, load_run

ANIMATION_RE = re.compile(r"^\d{8}_\d{6}_visualization(?:_(\d+|preprocessing))?\.html$")
PLAYER_TEMPLATE = Path(__file__).with_name("player.html")
SNAPSHOT_SETTLE_S = 1.0
# Only pages served from this computer (the dashboard and this server) may embed the viewer.
FRAME_ANCESTORS = "frame-ancestors 'self' http://localhost:* http://127.0.0.1:*"


def animation_files(run_dir: Path, settle: bool = True) -> tuple[Path | None, list[tuple[Path, int | None]]]:
    """(final animation, [(snapshot, simulation step or None for the build-plan snapshot)]) of a run.
    While a run is active (`settle`), files that may still be being written are left out."""
    out = run_dir / "simulator_output"
    final, snaps = None, []
    if not out.is_dir():
        return None, []
    for sub in out.iterdir():
        if not sub.is_dir():
            continue
        for f in sub.iterdir():
            m = ANIMATION_RE.match(f.name)
            if not m or not f.is_file():
                continue
            if m.group(1) is None:
                final = f if final is None or f.name > final.name else final
            elif _complete(f, settle):
                snaps.append((f, None if m.group(1) == "preprocessing" else int(m.group(1))))
    if final is not None and not _complete(final, settle):
        final = None
    snaps.sort(key=lambda s: -1 if s[1] is None else s[1])
    return final, snaps


def _complete(f: Path, settle: bool = True) -> bool:
    """A MeshCat file is complete once it ends with </html> and, while its run is still active,
    has not changed for a moment. (The worker records a final status only after all files are written.)"""
    try:
        st = f.stat()
        if settle and time.time() - st.st_mtime < SNAPSHOT_SETTLE_S:
            return False
        with open(f, "rb") as h:
            h.seek(max(0, st.st_size - 256))
            return b"</html>" in h.read()
    except OSError:
        return False


class ArtifactServer:
    def __init__(self, paths: Paths, host: str = "127.0.0.1"):
        self.paths = paths
        self.host = host
        handler = self._make_handler()
        self.httpd = ThreadingHTTPServer((host, 0), handler)   # port chosen by the OS
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="constructionlab-viewer", daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def player_url(self, run_id: str) -> str:
        return f"{self.base_url}/player/{run_id}"

    def shutdown(self) -> None:
        self.httpd.shutdown()

    def viewer_state(self, run_id: str) -> dict | None:
        rec = load_run(self.paths.runs / run_id)
        if rec is None:
            return None
        final, snaps = animation_files(rec.folder, settle=not rec.is_final)
        prog = rec.progress() if rec.state in ("queued", "running") else None
        base = f"/runs/{run_id}/file/"
        return {
            "run_id": run_id,
            "state": rec.state,
            "state_label": rec.state_label,
            "is_final": rec.is_final,
            "detail": rec.detail,
            "model_name": rec.model_name,
            "label": rec.label,
            "animation_enabled": bool(rec.settings.get("save_animation", False)),
            "live_enabled": bool(rec.settings.get("save_animation", False)) and int(rec.resolved.get("live_preview_interval", 0) or 0) > 0,
            "final": ({"url": base + final.name, "name": final.name, "size_mb": final.stat().st_size / 1e6}
                      if final else None),
            "snapshots": [{"url": base + f.name, "name": f.name, "step": step, "size_mb": f.stat().st_size / 1e6}
                          for f, step in snaps],
            "progress": ({"phase": prog.phase, "closed": prog.closed, "total": prog.total} if prog else None),
            "makespan_s": rec.metric("makespan_s"),
            "sim_time_step_s": rec.metric("sim_time_step_s"),
            "sim_steps": rec.metric("sim_steps"),
        }

    def _resolve_file(self, run_id: str, name: str) -> Path | None:
        if not ANIMATION_RE.match(name):
            return None
        run_dir = (self.paths.runs / run_id).resolve()
        rec = load_run(run_dir)
        final, snaps = animation_files(run_dir, settle=not (rec is not None and rec.is_final))
        for f in [final] + [s[0] for s in snaps]:
            if f is not None and f.name == name:
                p = f.resolve()
                if run_dir in p.parents:
                    return p
        return None

    def _make_handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "ConstructionLabViewer"
            sys_version = ""

            def log_message(self, *args):   # keep the console quiet
                pass

            def _host_ok(self) -> bool:
                host = (self.headers.get("Host") or "").lower()
                return host in (f"127.0.0.1:{server.port}", f"localhost:{server.port}")

            def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None, head_only=False):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                if not head_only:
                    self.wfile.write(body)

            def _error(self, code: int, msg: str, head_only=False):
                self._send(code, msg.encode(), "text/plain; charset=utf-8", head_only=head_only)

            def do_HEAD(self):
                self._route(head_only=True)

            def do_GET(self):
                self._route(head_only=False)

            def do_POST(self):
                self._error(405, "Method not allowed")

            do_PUT = do_DELETE = do_PATCH = do_POST

            def _route(self, head_only: bool):
                if not self._host_ok():
                    return self._error(403, "Forbidden", head_only)
                path = unquote(urlsplit(self.path).path)
                parts = [p for p in path.split("/") if p]
                if len(parts) == 2 and parts[0] == "player" and RUN_ID_RE.match(parts[1]):
                    if not (server.paths.runs / parts[1]).is_dir():
                        return self._error(404, "Unknown run", head_only)
                    html = PLAYER_TEMPLATE.read_text(encoding="utf-8").replace("__RUN_ID__", json.dumps(parts[1]))
                    return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8",
                                      {"Cache-Control": "no-store",
                                       "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                                       "style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-src 'self'; "
                                       + FRAME_ANCESTORS}, head_only)
                if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "viewer" and RUN_ID_RE.match(parts[2]):
                    st = server.viewer_state(parts[2])
                    if st is None:
                        return self._error(404, "Unknown run", head_only)
                    return self._send(200, json.dumps(st).encode(), "application/json", {"Cache-Control": "no-store"},
                                      head_only)
                if len(parts) == 4 and parts[0] == "runs" and parts[2] == "file" and RUN_ID_RE.match(parts[1]):
                    f = server._resolve_file(parts[1], parts[3])
                    if f is None:
                        return self._error(404, "Not found", head_only)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(f.stat().st_size))
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("Cache-Control", "no-cache")
                    # frame-ancestors is checked against every ancestor, including the dashboard page itself.
                    self.send_header("Content-Security-Policy", FRAME_ANCESTORS)
                    self.end_headers()
                    if not head_only:
                        with open(f, "rb") as src:
                            shutil.copyfileobj(src, self.wfile, 1 << 20)
                    return
                return self._error(404, "Not found", head_only)

        return Handler


_ATTR = "_constructionlab_viewer_servers"


def get_artifact_server(paths: Paths) -> ArtifactServer:
    """One viewer server per results folder per process (survives Streamlit module reloads)."""
    import sys
    reg = getattr(sys, _ATTR, None)
    if reg is None:
        reg = {}
        setattr(sys, _ATTR, reg)
    key = str(paths.results_root.resolve())
    srv = reg.get(key)
    if srv is None or not srv.thread.is_alive():
        srv = ArtifactServer(paths)
        reg[key] = srv
    return srv
