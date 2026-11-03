"""Every page renders without exceptions (Streamlit AppTest, temporary results folder, no Julia runs)."""
import pytest
from streamlit.testing.v1 import AppTest

from conftest import DASHBOARD

PAGES = ["overview", "new", "compare", "history", "analytics", "diagnostics", "help"]


def _render_page(dashboard_dir: str, page_key: str) -> None:
    import sys
    if dashboard_dir not in sys.path:
        sys.path.insert(0, dashboard_dir)
    import streamlit as st
    from ui import nav, theme
    from views import analytics, compare, diagnostics_page, help_page, history, new_simulation, overview
    mods = {"overview": overview, "new": new_simulation, "compare": compare, "history": history,
            "analytics": analytics, "diagnostics": diagnostics_page, "help": help_page}
    for key, mod in mods.items():
        nav.PAGES[key] = st.Page(mod.render, title=key, url_path=key, default=key == "overview")
    st.navigation(list(nav.PAGES.values()), position="hidden")
    theme.inject_css()
    mods[page_key].render()


@pytest.fixture
def no_julia(tmp_paths, monkeypatch, tmp_path):
    monkeypatch.setenv("CONSTRUCTIONLAB_JULIA", str(tmp_path / "no-julia-here.exe"))
    monkeypatch.chdir(DASHBOARD)
    return tmp_paths


@pytest.mark.parametrize("page", PAGES)
def test_page_renders(no_julia, page):
    at = AppTest.from_function(_render_page, args=(str(DASHBOARD), page), default_timeout=60)
    at.run()
    assert not at.exception, at.exception


def test_new_simulation_defaults_to_a_valid_tractor_run(no_julia):
    at = AppTest.from_function(_render_page, args=(str(DASHBOARD), "new"), default_timeout=60)
    at.run()
    assert not at.exception
    assert at.session_state["f_model"] == "tractor"
    run_buttons = [b for b in at.button if b.label == "Run simulation"]
    assert run_buttons and not run_buttons[0].disabled


def test_glpk_with_warm_start_disables_run(no_julia):
    at = AppTest.from_function(_render_page, args=(str(DASHBOARD), "new"), default_timeout=60)
    at.run()
    at.session_state["f_assignment"] = "milp_w_greedy_warm_start"
    at.session_state["f_solver"] = "glpk"
    at.run()
    assert not at.exception
    run_button = next(b for b in at.button if b.label == "Run simulation")
    assert run_button.disabled
    assert any("GLPK cannot be combined" in h.proto.body for h in at.get("html"))
