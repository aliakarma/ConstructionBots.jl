"""Overview: what this tool is, where to start, recent experiments and system readiness."""
from __future__ import annotations

import streamlit as st

from simulation.diagnostics import report_age_text
from ui import nav, services, theme
from ui.theme import fmt_num

READINESS = [
    ("julia_exe", "Julia"),
    ("constructionbots", "ConstructionBots module"),
    ("ldraw", "LDraw Parts Library"),
    ("rvo2", "RVO2 (collision avoidance)"),
    ("solver_highs", "HiGHS solver"),
    ("meshcat", "3D viewer assets"),
    ("results_dir", "Results folder"),
    ("solver_glpk", "GLPK solver (optional)"),
    ("solver_gurobi", "Gurobi solver (optional)"),
]


def render() -> None:
    paths = services.paths()
    runs = services.runs()
    report = services.diagnostics()

    theme.page_header("ConstructionLab", "Plan, run and compare multi-robot LEGO assembly experiments with the "
                      "ConstructionBots simulator: robot teams are assigned construction tasks, drive around active "
                      "build sites, and assemble the model in simulation.", eyebrow="Multi-Robot Construction Simulation & Research")

    c1, c2, c3, _ = st.columns([1.3, 1.3, 1.3, 3])
    if c1.button("New simulation", type="primary", icon=":material/play_arrow:", width="stretch"):
        nav.go("new")
    if c2.button("Compare experiments", icon=":material/compare_arrows:", width="stretch"):
        nav.go("compare")
    if c3.button("Experiment history", icon=":material/history:", width="stretch"):
        nav.go("history")

    left, right = st.columns([7, 4], gap="large")
    with left:
        theme.section("Recent experiments")
        if not runs:
            theme.empty_state(
                "No experiments yet",
                "Start with the default experiment: the Tractor model with 10 robots, Greedy task assignment and the "
                "recommended movement profile. The very first run takes about two minutes because Julia loads and "
                "compiles the simulator; later runs are faster.")
            st.space("small")
            if st.button("Set up the first simulation", icon=":material/arrow_forward:"):
                nav.go("new")
        else:
            rows = []
            for r in runs[:8]:
                ms = r.metric("makespan_s")
                rows.append((r.created_at.replace("T", " ")[:16],
                             "html:" + theme.pill(r.state_label, r.state),
                             r.label, fmt_num(ms, 2, "s") if ms is not None else "—"))
            theme.kv_table(rows, header=("Created", "Status", "Configuration", "Completion (simulated)"))
            st.caption(f"{len(runs)} run(s) saved in total. Completion time is the simulated makespan; it is empty for "
                       "runs that did not finish.")
            nav.link("history", "Open the full experiment history", icon=":material/history:")
    with right:
        theme.section("System readiness")
        rows = []
        for cid, label in READINESS:
            status = report.status_of(cid) or "unchecked"
            text = {"ok": "Available", "fail": "Missing", "warn": "Needs configuration", "unavailable": "Optional, unavailable",
                    "unchecked": "Not checked", "info": "Information"}.get(status, status)
            rows.append((label, "html:" + theme.pill(text, status)))
        theme.kv_table(rows)
        st.caption(f"Last full check: {report_age_text(report)}.")
        if not report.checked:
            theme.note("The Julia-side checks have not been run on this computer yet. They take about 10–60 seconds.",
                       "info")
        elif not report.required_ok:
            theme.note("A required component is missing or needs attention. Simulations may fail until it is fixed.",
                       "warn")
        else:
            st.caption("Everything required for the default open-source configuration (HiGHS, no Gurobi) is available.")
        nav.link("diagnostics", "Open System diagnostics", icon=":material/monitor_heart:")

        theme.section("Where results are saved")
        st.markdown(f"Every run gets its own folder under `{paths.display(paths.runs)}`. CSV exports are saved to "
                    f"`{paths.display(paths.exports)}`. Nothing is ever overwritten.")
