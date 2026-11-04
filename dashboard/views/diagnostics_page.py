"""System diagnostics: is everything the simulator needs installed and reachable?"""
from __future__ import annotations

import time

import streamlit as st

from simulation.diagnostics import report_age_text, run_julia_checks
from simulation.paths import find_julia
from ui import services, theme
from ui.theme import fmt_duration


def _table(checks) -> None:
    rows = []
    for c in checks:
        rows.append((c.label, "html:" + theme.pill(c.status_label, c.status), c.detail, c.action or ""))
    theme.kv_table(rows, header=("Component", "Status", "Details", "What to do"))


def render() -> None:
    paths = services.paths()
    theme.page_header("System diagnostics", "Checks that the simulator, its Python collision-avoidance module, the "
                      "LEGO part library and the optimization solvers are installed and usable. Nothing is changed on "
                      "your computer.", eyebrow="System")
    report = services.diagnostics()
    c1, c2 = st.columns([2, 5], vertical_alignment="center")
    if c1.button("Run system checks", type="primary", icon=":material/fact_check:", width="stretch"):
        with st.status("Running the Julia-side checks (about 10–60 s)…", expanded=False) as s:
            t0 = time.time()
            ok, msg = run_julia_checks(paths)
            if ok:
                s.update(label=f"Checks finished in {time.time() - t0:.0f} s", state="complete")
            else:
                s.update(label="The checks could not finish", state="error")
                st.code(msg, language=None)
        st.session_state["_catalog_token"] = st.session_state.get("_catalog_token", 0) + 1
        report = services.diagnostics()
    c2.caption(f"Last full check: {report_age_text(report)}. The results are stored in "
               f"`{paths.display(paths.cache / 'diagnostics.toml')}`.")

    required = [c for c in report.checks if c.category == "required"]
    optional = [c for c in report.checks if c.category != "required"]
    if report.checked and report.required_ok:
        theme.note("Everything required for the default open-source configuration is available.", "ok")
    elif report.checked:
        theme.note("At least one required component is missing or needs attention (see below).", "err")
    theme.section("Required components")
    _table(required)
    theme.section("Optional components")
    _table(optional)
    st.caption("Gurobi is optional. The dashboard never substitutes another solver when Gurobi is requested but "
               "unavailable; such runs are rejected with an explanation.")

    theme.section("Simulation engine")
    eng = services.engine()
    snap = eng.snapshot()
    julia = find_julia(paths.repo)
    rows = [("State", "html:" + theme.pill(snap.state.replace("_", " ").title(), snap.state)),
            ("Process", str(snap.pid) if snap.pid else "not running"),
            ("Julia", f"{julia.path or 'not found'} (found via {julia.source})"),
            ("Expected Julia version", julia.expected_version or "unknown (no Manifest.toml)"),
            ("Runs in this engine session", snap.runs_completed),
            ("Active run", snap.active_run or "none"), ("Queued runs", len(snap.queue))]
    if snap.started_at:
        rows.append(("Running for", fmt_duration(time.time() - snap.started_at)))
    if snap.last_error:
        rows.append(("Last error", snap.last_error))
    if snap.read_only_reason:
        rows.append(("Read-only", snap.read_only_reason))
    theme.kv_table(rows)
    log = eng.engine_log_tail(12_000)
    if log:
        with st.expander("Engine log (end)"):
            st.code(log, language=None)

    theme.section("Viewer and storage")
    srv = services.viewer_server()
    theme.kv_table([
        ("3D viewer server", f"{srv.base_url} (this computer only; serves saved animations of runs)"),
        ("Results folder", paths.display(paths.results_root)),
        ("Model registry", "src/project_params.jl (read by the Julia worker)"),
    ])
    st.caption("Setup instructions: dashboard/README.md (Julia, LDraw library, RVO2 and the optional Gurobi licence).")
