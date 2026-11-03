"""Experiment history: browse, filter, inspect, replay, export and (recoverably) delete runs."""
from __future__ import annotations

import shutil
from html import escape
from datetime import datetime

import streamlit as st

from simulation.results import STATE_LABELS, RunRecord, read_text, records_to_frame, save_export, strip_ansi, \
    tail_text, to_csv_bytes
from simulation.artifact_server import animation_files
from ui import nav, services, theme
from ui.theme import fmt_duration, fmt_num

P = "session"

TABLE_COLUMNS = {
    "status": st.column_config.TextColumn("Status", width="small"),
    "created_at": st.column_config.TextColumn("Created", width="small"),
    "model": st.column_config.TextColumn("Model"),
    "num_robots": st.column_config.NumberColumn("Robots", width="small"),
    "assignment_method": st.column_config.TextColumn("Assignment"),
    "solver": st.column_config.TextColumn("Solver", width="small"),
    "movement_profile": st.column_config.TextColumn("Movement"),
    "random_seed": st.column_config.NumberColumn("Seed", width="small"),
    "makespan_sim_s": st.column_config.NumberColumn("Completion [sim s]", format="%.2f",
                                                    help="Simulated time until the model was fully built (makespan)"),
    "planned_makespan_sim_s": st.column_config.NumberColumn("Planned [sim s]", format="%.2f",
                                                            help="Schedule estimate after assignment, ignoring traffic"),
    "robot_min_gap_m": st.column_config.NumberColumn("Robot gap [m]", format="%.3f",
                                                     help="Smallest gap between two free robots; negative means overlap"),
    "position_swaps": st.column_config.NumberColumn("Swaps", width="small",
                                                    help="Times two robots instantly exchanged positions"),
    "assignment_time_cpu_s": st.column_config.NumberColumn("Assignment [cpu s]", format="%.2f",
                                                           help="Computer time spent on task assignment"),
    "total_time_cpu_s": st.column_config.NumberColumn("Total [cpu s]", format="%.1f",
                                                      help="Computer time for the whole simulator call"),
    "run_id": st.column_config.TextColumn("Run ID"),
}


def _filtered(records: list[RunRecord]) -> list[RunRecord]:
    s = st.session_state
    q = (s.get("hist_q") or "").strip().lower()
    out = []
    for r in records:
        if q and q not in r.run_id.lower() and q not in r.label.lower() and q not in r.model_name.lower():
            continue
        if s.get("hist_models") and r.model_name not in s["hist_models"]:
            continue
        if s.get("hist_methods") and r.resolved.get("assignment_label") not in s["hist_methods"]:
            continue
        if s.get("hist_status") and r.state_label not in s["hist_status"]:
            continue
        out.append(r)
    return out


def _delete(rec: RunRecord) -> str:
    paths = services.paths()
    target = paths.deleted / rec.run_id
    if target.exists():
        target = paths.deleted / f"{rec.run_id}_{datetime.now():%Y%m%d%H%M%S}"
    shutil.move(str(rec.folder), str(target))
    return paths.display(target)


def _details(rec: RunRecord) -> None:
    paths = services.paths()
    st.html(f'<div class="cl-runhead">{theme.pill(rec.state_label, rec.state)}<span class="title">'
            f'{escape(rec.label)}</span><span class="cl-muted">{escape(rec.run_id)}</span></div>')
    st.caption(rec.detail)
    tabs = st.tabs(["Summary", "Replay", "Configuration", "Logs", "Files"])
    with tabs[0]:
        items = [("Completion time", fmt_num(rec.metric("makespan_s"), 2, "s"), "simulated (makespan)"),
                 ("Planned completion", fmt_num(rec.metric("optimistic_makespan_s"), 2, "s"), "simulated, schedule estimate"),
                 ("Smallest robot gap", fmt_num(rec.metric("robot_min_gap_m"), 3, "m"), "negative means overlap"),
                 ("Assignment time", fmt_num(rec.metric("assignment_time_s"), 2, "s"), "computer time"),
                 ("Preparation time", fmt_num(rec.metric("pre_execution_runtime_s"), 1, "s"), "computer time"),
                 ("Execution time", fmt_num(rec.metric("execution_runtime_s"), 1, "s"), "computer time"),
                 ("Total run time", fmt_duration(rec.metric("total_wall_time_s")), "computer time")]
        theme.metric_strip(items)
        rows = [("Created", rec.created_at.replace("T", " ")), ("Started", rec.started_at.replace("T", " ")),
                ("Finished", rec.finished_at.replace("T", " ")),
                ("Parts / assemblies (simulator)", f"{rec.result.get('num_objects', '—')} / {rec.result.get('num_assemblies', '—')}")]
        if rec.result.get("robot_overlap_steps") is not None:
            rows.append(("Safety", f"{rec.result.get('robot_overlap_steps')} steps with overlapping robots, "
                                   f"{rec.result.get('overlap_steps')} including transport teams, "
                                   f"{rec.result.get('position_swaps')} position swaps, top speed "
                                   f"{fmt_num(rec.metric('max_speed_mps'), 2, 'm/s')}"))
        if rec.source_hash:
            rows.append(("Code version", f"source {rec.source_hash}, commit {rec.result['software'].get('git_commit', '—')}"
                                         + (" with uncommitted changes" if rec.result['software'].get('git_dirty') else "")))
        rep = rec.solver_report()
        if rep:
            rows.append(("Solver result", rep.label or "—"))
            if rep.warm_start_objective is not None:
                rows.append(("Warm start objective", fmt_num(rep.warm_start_objective, 3)))
            if rep.primal_bound is not None:
                rows.append(("Best schedule found (solver objective)", fmt_num(rep.primal_bound, 3)))
            if rep.dual_bound is not None:
                rows.append(("Lower bound (solver)", fmt_num(rep.dual_bound, 3)))
        rows.append(("Includes compilation", {True: "yes (first run of this kind in the engine session)",
                                              False: "no"}.get(rec.result.get("includes_compilation"), "—")))
        if rec.result.get("warm_up"):
            rows.append(("Warm-up", rec.result.get("warm_up")))
        theme.kv_table(rows)
    with tabs[1]:
        final, snaps = animation_files(rec.folder, settle=not rec.is_final)
        if final or snaps or not rec.is_final:
            st.iframe(services.viewer_server().player_url(rec.run_id), height=560)
        elif not rec.settings.get("save_animation"):
            theme.empty_state("No animation for this run", "3D animation recording was switched off for this run.")
        else:
            theme.empty_state("No animation for this run",
                              f"The run ended with status “{rec.state_label}” before an animation was saved.")
    with tabs[2]:
        r = rec.resolved
        theme.kv_table([("Model", f"{r.get('model_name')} ({r.get('ldraw_file')}, scale {r.get('model_scale')})"),
                        ("Robots", f"{r.get('num_robots')} ({r.get('robots_source')})"),
                        ("Assignment", r.get("assignment_label")), ("Solver", r.get("solver_label")),
                        ("Movement", f"{r.get('movement_label')} (RVO2 {r.get('rvo')}, Tangent Bug {r.get('tangent_bug')}, "
                                     f"Dispersion {r.get('dispersion')})"),
                        ("Random seed", rec.settings.get("seed")), ("Wall-clock limit", f"{r.get('timeout_min')} min" if r.get("timeout_min") else "No limit")])
        st.markdown("**Exact arguments passed to `ConstructionBots.run_lego_demo`**")
        theme.kv_table([(k, f"code:{v}") for k, v in sorted(rec.arguments.items())])
        sw = rec.result.get("software") or {}
        if sw:
            st.markdown("**Software used**")
            theme.kv_table([(k, ", ".join(v) if isinstance(v, list) else v) for k, v in sorted(sw.items())])
    with tabs[3]:
        out = tail_text(rec.stdout_path, 60_000)
        err = tail_text(rec.stderr_path, 20_000)
        if not out and not err:
            st.caption("No simulator output was recorded for this run.")
        if out:
            st.markdown("**Simulator output** (end of `simulator_stdout.log`)")
            st.code(strip_ansi(out)[-20_000:], language=None, height=320)
        if err:
            st.markdown("**Progress and warnings** (end of `simulator_stderr.log`)")
            st.code(strip_ansi(err)[-6_000:], language=None, height=200)
        e = read_text(rec.folder / "error.txt", 40_000)
        if e:
            st.markdown("**Error** (`error.txt`)")
            st.code(e[-12_000:], language=None, height=260)
    with tabs[4]:
        st.markdown(f"Run folder: `{paths.display(rec.folder)}`")
        files = sorted(p for p in rec.folder.rglob("*") if p.is_file())
        theme.kv_table([(p.relative_to(rec.folder).as_posix(), f"{p.stat().st_size / 1e6:.2f} MB") for p in files],
                       header=("File", "Size"))
        st.download_button("Download this run as CSV", to_csv_bytes([rec], paths), file_name=f"{rec.run_id}.csv",
                           mime="text/csv", icon=":material/download:", key=f"dl_one_{rec.run_id}")


def render() -> None:
    paths = services.paths()
    theme.page_header("Experiment history", "Every run is kept with its exact settings, the simulator's own output, "
                      "logs and animation. Select runs to inspect, replay, compare or export them.", eyebrow="Results")
    records = services.runs()
    if not records:
        theme.empty_state("No runs yet", "Runs you start on the New simulation page appear here.")
        nav.link("new", "Go to New simulation", icon=":material/play_circle:")
        return

    c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
    c1.text_input("Search", key="hist_q", persist_state=P, placeholder="Model, label or run ID")
    c2.multiselect("Model", sorted({r.model_name for r in records}), key="hist_models", persist_state=P)
    c3.multiselect("Assignment", sorted({str(r.resolved.get("assignment_label", "")) for r in records}),
                   key="hist_methods", persist_state=P)
    c4.multiselect("Status", [v for v in STATE_LABELS.values() if v in {r.state_label for r in records}],
                   key="hist_status", persist_state=P)
    shown = _filtered(records)
    df = records_to_frame(shown, paths)
    df["created_at"] = df["created_at"].str.replace("T", " ").str.slice(0, 16)
    preselect = st.session_state.pop("hist_selected", None)
    default = None
    if preselect and preselect in list(df["run_id"]):
        default = {"selection": {"rows": [int(df.index[df["run_id"] == preselect][0])], "columns": []}}
    event = st.dataframe(df[list(TABLE_COLUMNS)], column_config=TABLE_COLUMNS, hide_index=True, on_select="rerun",
                         selection_mode="multi-row", key="hist_table", height=min(420, 38 + 35 * max(len(df), 1)),
                         selection_default=default)
    selected_rows = event.selection.rows if event and event.selection else []
    selected = [shown[i] for i in selected_rows if i < len(shown)]
    st.caption(f"{len(shown)} of {len(records)} run(s) shown. Select rows with the checkboxes on the left. "
               "sim s = simulated seconds; cpu s = computer (wall-clock) seconds; empty = not available.")

    a1, a2, a3, a4 = st.columns([2, 2, 2, 3])
    a1.download_button("Download table (CSV)", to_csv_bytes(shown, paths), file_name="constructionlab_runs.csv",
                       mime="text/csv", icon=":material/download:", width="stretch",
                       help="All runs currently shown, including failed ones.")
    if a2.button("Save table to exports", icon=":material/save:", width="stretch",
                 help="Writes a new CSV file into results/dashboard/exports (never overwrites)."):
        p = save_export(shown, paths, "history")
        st.toast(f"Saved {paths.display(p)}")
    if a3.button(f"Compare selected ({len(selected)})", icon=":material/compare_arrows:", width="stretch",
                 disabled=len(selected) < 2):
        nav.go("compare", cmp_preselect=[r.run_id for r in selected])

    if len(selected) == 1:
        rec = selected[0]
        st.divider()
        _details(rec)
        if rec.is_final:
            with st.popover("Delete this run…", icon=":material/delete:"):
                st.markdown(f"Move **{rec.run_id}** to `{paths.display(paths.deleted)}`? It disappears from the "
                            "dashboard but the files are kept there and can be moved back by hand.")
                confirm = st.checkbox("Yes, move this run out of the history", key=f"del_ok_{rec.run_id}")
                if st.button("Move run", type="primary", disabled=not confirm, key=f"del_{rec.run_id}"):
                    where = _delete(rec)
                    st.toast(f"Moved to {where}")
                    st.rerun()
        else:
            st.caption("Runs that are queued or running cannot be deleted. Cancel them on the New simulation page.")
    elif len(selected) > 1:
        st.divider()
        st.markdown(f"**{len(selected)} runs selected.** Use *Compare selected* to see them side by side.")
