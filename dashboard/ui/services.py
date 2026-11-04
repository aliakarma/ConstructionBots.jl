"""Shared services for all pages (one instance per dashboard process) and session helpers."""
from __future__ import annotations

import streamlit as st

from simulation.artifact_server import ArtifactServer, get_artifact_server
from simulation.catalog import Catalog, load_catalog
from simulation.diagnostics import Report, load_report
from simulation.engine import EngineManager, get_engine
from simulation.paths import Paths
from simulation.results import RunRecord, list_runs, load_run


@st.cache_resource(show_spinner=False)
def paths() -> Paths:
    p = Paths.default()
    p.ensure()
    return p


def engine() -> EngineManager:
    return get_engine(paths())


def viewer_server() -> ArtifactServer:
    return get_artifact_server(paths())


@st.cache_data(show_spinner=False, ttl=600)
def _catalog_cached(refresh_token: int) -> Catalog:
    return load_catalog(paths())


def catalog() -> Catalog:
    return _catalog_cached(st.session_state.get("_catalog_token", 0))


def diagnostics() -> Report:
    return load_report(paths())


def runs() -> list[RunRecord]:
    return list_runs(paths())


def run(run_id: str) -> RunRecord | None:
    return load_run(paths().runs / run_id)
