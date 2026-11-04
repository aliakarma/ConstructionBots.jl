"""ConstructionLab: multi-robot construction simulation & research dashboard.

Start from the dashboard folder:   python -m streamlit run app.py
"""
from __future__ import annotations

import sys
import time
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="ConstructionLab", page_icon=str(HERE / "assets" / "mark.svg"), layout="wide",
                   initial_sidebar_state="expanded")

from ui import nav, services, theme  # noqa: E402
from ui.theme import fmt_duration  # noqa: E402
from views import analytics, compare, diagnostics_page, help_page, history, new_simulation, overview  # noqa: E402

theme.inject_css()
st.logo(str(HERE / "assets" / "logo.svg"), size="large", icon_image=str(HERE / "assets" / "mark.svg"))

nav.PAGES.update({
    "overview": st.Page(overview.render, title="Overview", icon=":material/space_dashboard:", url_path="overview", default=True),
    "new": st.Page(new_simulation.render, title="New simulation", icon=":material/play_circle:", url_path="new-simulation"),
    "compare": st.Page(compare.render, title="Compare experiments", icon=":material/compare_arrows:", url_path="compare"),
    "history": st.Page(history.render, title="Experiment history", icon=":material/history:", url_path="history"),
    "analytics": st.Page(analytics.render, title="Analytics", icon=":material/insights:", url_path="analytics"),
    "diagnostics": st.Page(diagnostics_page.render, title="System diagnostics", icon=":material/monitor_heart:", url_path="diagnostics"),
    "help": st.Page(help_page.render, title="Help & about", icon=":material/help:", url_path="help"),
})
page = st.navigation({
    "Workspace": [nav.PAGES["overview"], nav.PAGES["new"]],
    "Results": [nav.PAGES["compare"], nav.PAGES["history"], nav.PAGES["analytics"]],
    "System": [nav.PAGES["diagnostics"], nav.PAGES["help"]],
})

ENGINE_TEXT = {
    "stopped": ("Not started", "#8FA3B3", "Starts automatically with the first run. Loading takes about 20–60 s."),
    "starting": ("Starting", "#C88A43", "Loading Julia and the simulator packages."),
    "ready": ("Ready", "#5FB38A", "Idle. Runs start immediately."),
    "busy": ("Running", "#7CC3C6", ""),
    "error": ("Needs attention", "#E08A8A", ""),
    "read_only": ("Read-only window", "#C88A43", ""),
}


@st.fragment(run_every=2.0)
def engine_card() -> None:
    eng = services.engine()
    snap = eng.snapshot()
    label, color, detail = ENGINE_TEXT.get(snap.state, (snap.state, "#8FA3B3", ""))
    if snap.state == "starting" and snap.started_at:
        detail = f"Loading Julia and the simulator packages ({fmt_duration(time.time() - snap.started_at)})."
    elif snap.state == "busy" and snap.active_run:
        rec = services.run(snap.active_run)
        detail = (rec.label if rec else snap.active_run)
        if snap.queue:
            detail += f" · {len(snap.queue)} more queued"
    elif snap.state == "ready" and snap.runs_completed:
        detail = f"Idle · {snap.runs_completed} run(s) in this engine session."
    elif snap.state == "error":
        detail = snap.last_error[:220]
    elif snap.state == "read_only":
        detail = snap.read_only_reason
    st.html(f'<div class="cl-engine"><div class="t">Simulation engine</div>'
            f'<div class="s"><span class="dot" style="background:{color}"></span>{escape(label)}</div>'
            f'<div class="d">{escape(detail)}</div></div>')
    if snap.state == "stopped":
        if st.button("Start engine now", key="eng_start", width="stretch",
                     help="Optional: warm the engine up before your first run."):
            eng.start()
            st.rerun(scope="fragment")
    elif snap.state == "ready" and not snap.queue:
        if st.button("Stop engine", key="eng_stop", width="stretch",
                     help="Frees memory. The next run starts the engine again (about 20–60 s)."):
            eng.stop()
            st.rerun(scope="fragment")
    elif snap.state == "error":
        if st.button("Retry", key="eng_retry", width="stretch"):
            eng.clear_error()
            eng.start()
            st.rerun(scope="fragment")


with st.sidebar:
    engine_card()

page.run()
