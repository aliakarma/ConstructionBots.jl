"""Page registry so pages can link to each other (filled in by app.py on every run)."""
from __future__ import annotations

import streamlit as st

PAGES: dict[str, "st.Page"] = {}


def go(key: str, **state) -> None:
    """Switch to another page, optionally handing it some session values."""
    for k, v in state.items():
        st.session_state[k] = v
    st.switch_page(PAGES[key])


def link(key: str, label: str, icon: str | None = None) -> None:
    st.page_link(PAGES[key], label=label, icon=icon)
