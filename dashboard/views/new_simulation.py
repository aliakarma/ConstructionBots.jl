"""New simulation: configure, run and watch one experiment, or a study that varies one factor."""
from __future__ import annotations

import secrets
import time
from datetime import datetime
from html import escape

import streamlit as st

from simulation.catalog import (ASSIGNMENT_METHODS, MOVEMENT_METHODS_EXPLAINED, MOVEMENT_PROFILES, SAFETY_NOTE,
                                SOLVERS, Catalog, option)
from simulation.results import read_text, tail_text
from simulation.validation import (LIVE_PREVIEW_LABELS, MAX_RUNS_PER_STUDY, MAX_SEEDS_PER_STUDY, MAX_TIMEOUT_MIN,
                                   NO_TIME_LIMIT, STUDY_FACTORS, RunConfig, Validation, expand_study, parse_int_list,
                                   resolve_movement, validate)
from ui import nav, services, theme
from ui.theme import fmt_duration, fmt_num

P = "session"   # widget values survive page switches


# -----------------------------------------------------------------------------
# Form state
# -----------------------------------------------------------------------------

def _init_state(cat: Catalog) -> None:
    s = st.session_state
    model = cat.model(s.get("f_model", cat.default_model_key)) if cat.has(s.get("f_model", "")) else \
        cat.model(cat.default_model_key)
    defaults = {
        "f_mode": "single", "f_model": model.key, "f_robots_mode": "default", "f_robots": model.default_robots,
        "f_seed": 1, "f_assignment": "greedy", "f_solver": "highs", "f_time_limit": 60, "f_movement": "recommended",
        "f_search_iters": 25, "f_search_pop": 16,
        "f_c_rvo": True, "f_c_tb": True, "f_c_disp": True, "f_anim": True, "f_smooth": False,
        "f_live": "normal" if model.size in ("small", "medium") else "off",
        "f_max_steps": 100_000, "f_max_noprog": 10_000, "f_timeout": NO_TIME_LIMIT,
        "f_warmup": False, "f_label": "", "f_confirm_large": False,
        "f_factor": "assignment", "f_lv_assignment": [o.key for o in ASSIGNMENT_METHODS],
        "f_lv_solver": ["highs", "glpk"], "f_lv_movement": [p.key for p in MOVEMENT_PROFILES],
        "f_lv_robots": "", "f_seeds": "1", "f_study_warmup": True,
    }
    for k, v in defaults.items():
        s.setdefault(k, v)
    if not s["f_lv_robots"]:
        d = model.default_robots
        s["f_lv_robots"] = ", ".join(str(x) for x in sorted({max(1, round(d * 0.6)), d, round(d * 1.4)}))


def _on_model_change() -> None:
    cat = services.catalog()
    m = cat.model(st.session_state["f_model"])
    st.session_state["f_robots"] = m.default_robots
    st.session_state["f_timeout"] = NO_TIME_LIMIT
    st.session_state["f_confirm_large"] = False
    st.session_state["f_live"] = "normal" if m.size in ("small", "medium") else "off"
    d = m.default_robots
    st.session_state["f_lv_robots"] = ", ".join(str(x) for x in sorted({max(1, round(d * 0.6)), d, round(d * 1.4)}))


def _config_from_state() -> RunConfig:
    s = st.session_state
    return RunConfig(
        model_key=s["f_model"], num_robots=None if s["f_robots_mode"] == "default" else int(s["f_robots"]),
        seed=int(s["f_seed"]), assignment=s["f_assignment"], solver=s["f_solver"], movement=s["f_movement"],
        custom_rvo=bool(s["f_c_rvo"]), custom_tangent_bug=bool(s["f_c_tb"]), custom_dispersion=bool(s["f_c_disp"]),
        optimizer_time_limit_s=int(s["f_time_limit"]), search_iterations=int(s["f_search_iters"]),
        search_population=int(s["f_search_pop"]), max_steps=int(s["f_max_steps"]),
        max_iters_no_progress=int(s["f_max_noprog"]), save_animation=bool(s["f_anim"]),
        smooth_animation=bool(s["f_smooth"]), live_preview=s["f_live"], timeout_min=int(s["f_timeout"]),
        warm_up=bool(s["f_warmup"]), confirm_large=bool(s["f_confirm_large"]), label=str(s["f_label"]).strip())


# -----------------------------------------------------------------------------
# Configuration column
# -----------------------------------------------------------------------------

def _model_section(cat: Catalog, history) -> None:
    theme.section("Model", "what the robots build", 1)
    st.selectbox("Construction model", [m.key for m in cat.models], key="f_model", on_change=_on_model_change,
                 persist_state=P, format_func=lambda k: _model_option_label(cat, k),
                 help="Models come from the repository's registry (src/project_params.jl). Part and assembly "
                      "counts are the authors' notes in that file.")
    m = cat.model(st.session_state["f_model"])
    verified = [r for r in history if r.settings.get("model_key") == m.key and r.state == "success"
                and r.result.get("num_objects") is not None]
    items = [(f"{m.reference_parts} parts", None), (f"{m.reference_assemblies} assemblies", None),
             (f"{m.size_label} experiment", None), (f"default {m.default_robots} robots", None)]
    if m.reference_time:
        items.append((f"reference time ≈ {m.reference_time}", None))
    st.html(theme.chips(items))
    caption = f"File LDraw_files/{m.file_name} · scale {m.model_scale}."
    if verified:
        r = verified[0]
        caption += (f" Confirmed by a completed run here: {r.result.get('num_objects')} parts, "
                    f"{r.result.get('num_assemblies')} assemblies.")
    st.caption(caption + " Reference times were measured by the authors on their hardware with Greedy assignment.")
    if not m.file_exists:
        theme.note(f"The model file LDraw_files/{m.file_name} is missing.", "err")
    if m.size in ("large", "very_large"):
        st.checkbox(f"I understand that {m.name} is a {m.size_label.lower()} model and may run for a long time",
                    key="f_confirm_large", persist_state=P)


def _model_option_label(cat: Catalog, key: str) -> str:
    m = cat.model(key)
    parts = f"{m.reference_parts} parts" if m.reference_parts else "parts not noted"
    return f"{m.name}  ·  {parts}  ·  {m.size_label.lower()}"


def _robots_section(cat: Catalog) -> None:
    theme.section("Robots", "fleet size and starting layout", 2)
    m = cat.model(st.session_state["f_model"])
    c1, c2 = st.columns([3, 2], vertical_alignment="bottom")
    with c1:
        st.radio("Number of robots", ["default", "custom"], key="f_robots_mode", horizontal=True, persist_state=P,
                 format_func=lambda x: f"Model default ({m.default_robots})" if x == "default" else "Custom number")
    with c2:
        st.number_input("Robots", min_value=1, max_value=500, step=1, key="f_robots", persist_state=P,
                        disabled=st.session_state["f_robots_mode"] == "default", label_visibility="collapsed",
                        help="1 to 500 robots.")
    st.number_input("Random seed", min_value=0, max_value=2_147_483_647, step=1, key="f_seed", persist_state=P,
                    help="Passed to the simulator as rng = MersenneTwister(seed). It decides the robots' starting "
                         "positions. Runs with the same settings and seed start from the same layout.")
    if st.session_state["f_robots_mode"] == "custom" and int(st.session_state["f_robots"]) != m.default_robots:
        st.caption(f"Differs from the model's default of {m.default_robots} robots.")


def _assignment_section(report) -> None:
    theme.section("Task assignment", "which robot team does which task", 3)
    st.selectbox("Assignment method", [o.key for o in ASSIGNMENT_METHODS], key="f_assignment", persist_state=P,
                 format_func=lambda k: f"{option(ASSIGNMENT_METHODS, k).family} · {option(ASSIGNMENT_METHODS, k).label}",
                 help="Heuristic rules decide instantly; MILP methods ask an optimization solver; metaheuristics "
                      "search over task orders within a budget.")
    a = option(ASSIGNMENT_METHODS, st.session_state["f_assignment"])
    st.caption(a.description)
    if a.search:
        c1, c2, c3 = st.columns(3)
        c1.number_input("Iterations", min_value=1, max_value=1000, step=5, key="f_search_iters", persist_state=P,
                        help="run_lego_demo metaheuristic_iterations: generations (GA, PSO) or temperature steps (SA).")
        c2.number_input("Population", min_value=2, max_value=500, step=2, key="f_search_pop", persist_state=P,
                        help="run_lego_demo metaheuristic_population: candidate schedules per iteration.")
        c3.number_input("Time limit (seconds)", min_value=1, max_value=86_400, step=10, key="f_time_limit",
                        persist_state=P, help="The search stops here and keeps the best schedule found so far.")
        st.caption(f"Budget: about {int(st.session_state['f_search_iters']) * int(st.session_state['f_search_pop']):,} "
                   "candidate schedules (a few seconds on the Tractor). Each metaheuristic gets the same budget, so "
                   "they can be compared fairly.")
        return
    st.segmented_control("Optimization solver", [o.key for o in SOLVERS], key="f_solver", required=True,
                         persist_state=P, format_func=lambda k: option(SOLVERS, k).label, disabled=not a.uses_solver,
                         width="stretch",
                         help="Only MILP-based methods use a solver. HiGHS is free and recommended.")
    if not a.uses_solver:
        st.caption(f"{a.label} does not use an optimization solver, so the solver setting does not apply.")
        return
    s = option(SOLVERS, st.session_state["f_solver"])
    status = report.status_of(f"solver_{s.key}")
    availability = {"ok": "available on this computer", "unavailable": "not available on this computer",
                    "fail": "not available on this computer", "unchecked": "availability not checked yet"}.get(status, "")
    st.caption(f"{s.description}" + (f" Status: {availability}." if availability else ""))
    st.number_input("Optimizer time limit (seconds)", min_value=1, max_value=86_400, step=10, key="f_time_limit",
                    persist_state=P,
                    help="The solver stops at this limit and returns the best schedule found so far, which may not "
                         "be optimal. Longer limits can give better schedules but take longer.")


def _movement_section() -> None:
    theme.section("Movement", "how robots drive and avoid each other", 4)
    keys = [p.key for p in MOVEMENT_PROFILES] + ["custom"]
    labels = {p.key: p.label for p in MOVEMENT_PROFILES} | {"custom": "Custom combination"}
    st.selectbox("Movement profile", keys, key="f_movement", persist_state=P, format_func=lambda k: labels[k])
    if st.session_state["f_movement"] == "custom":
        c1, c2, c3 = st.columns(3)
        c1.toggle("RVO2", key="f_c_rvo", persist_state=P)
        c2.toggle("Tangent Bug", key="f_c_tb", persist_state=P)
        c3.toggle("Dispersion", key="f_c_disp", persist_state=P)
    prof = resolve_movement(_config_from_state())
    st.html(theme.chips([("RVO2", prof.rvo), ("Tangent Bug", prof.tangent_bug), ("Dispersion", prof.dispersion)]))
    st.caption(prof.description)
    if prof.note:
        theme.note(prof.note, "info")
    if prof.unsafe:
        theme.note(SAFETY_NOTE, "warn", "Safety limitation.")
    elif prof.avoidance_reduced:
        theme.note("This profile switches off part of the collision-avoidance stack. Use it as an ablation, and "
                   "judge it together with the animation, not by completion time alone.", "warn")
    with st.expander("What do RVO2, Tangent Bug and Dispersion do?"):
        for k, v in MOVEMENT_METHODS_EXPLAINED.items():
            st.markdown(f"**{k}.** {v}")
        st.markdown("Movement methods decide *how* robots drive. Task assignment decides *which* robot carries "
                    "*which* part. They solve different problems and can be combined freely.")


def _advanced_section(cat: Catalog) -> None:
    m = cat.model(st.session_state["f_model"])
    with st.expander("Advanced settings"):
        st.toggle("Save 3D animation", key="f_anim", persist_state=P,
                  help="Records the simulator's MeshCat animation so you can watch and replay the run.")
        c1, c2 = st.columns(2)
        c1.toggle("Smooth animation (every step)", key="f_smooth", persist_state=P, disabled=not st.session_state["f_anim"],
                  help="Records every simulation step (run_lego_demo update_anim_at_every_step). Shows collision "
                       "avoidance faithfully, but makes the run and the file much larger. Off: positions are recorded "
                       "when tasks complete and drawn as straight lines in between.")
        with c2:
            st.segmented_control("Live preview", list(LIVE_PREVIEW_LABELS), key="f_live", required=True,
                                 persist_state=P, format_func=LIVE_PREVIEW_LABELS.get,
                                 disabled=not st.session_state["f_anim"],
                                 help="While running, the simulator periodically saves the animation so far "
                                      "(save_animation_along_the_way) and the viewer follows the newest snapshot.")
        c3, c4 = st.columns(2)
        c3.number_input("Maximum simulation steps", min_value=100, max_value=100_000_000, step=1000,
                        key="f_max_steps", persist_state=P, help="run_lego_demo max_steps (default 100,000).")
        c4.number_input("Maximum steps without progress", min_value=10, max_value=100_000_000, step=500,
                        key="f_max_noprog", persist_state=P,
                        help="run_lego_demo max_num_iters_no_progress (default 10,000). The run stops as incomplete "
                             "if no task finishes for this many steps.")
        c5, c6 = st.columns(2)
        c5.number_input("Wall-clock limit (minutes, 0 = no limit)", min_value=0, max_value=MAX_TIMEOUT_MIN, step=5,
                        key="f_timeout", persist_state=P,
                        help="The dashboard stops the run if it takes longer than this. 0 (the default) lets the run "
                             "finish however long it takes. Set a limit only to stop a run you do not want to wait for.")
        with c6:
            st.space("small")
            st.checkbox("Warm up first (untimed)", key="f_warmup", persist_state=P,
                        help="Before the run, the engine does an untimed Tractor run on the same code path so that "
                             "one-time compilation is not included in this run's computer-time measurements.")
        st.text_input("Label (optional)", key="f_label", max_chars=120, persist_state=P,
                      placeholder="e.g. pilot run, thesis figure 3",
                      help="Shown in the history and comparison tables instead of the automatic label.")


def _study_section(base: RunConfig) -> tuple[list[RunConfig], list[str]]:
    """Study settings. Returns (planned configurations, problems)."""
    theme.section("Study design", "vary one factor, keep everything else fixed", 5)
    st.selectbox("Factor to compare", list(STUDY_FACTORS), key="f_factor", persist_state=P,
                 format_func=STUDY_FACTORS.get)
    factor = st.session_state["f_factor"]
    problems: list[str] = []
    levels: list = []
    if factor == "assignment":
        levels = st.multiselect("Assignment methods", [o.key for o in ASSIGNMENT_METHODS], key="f_lv_assignment",
                                persist_state=P, format_func=lambda k: option(ASSIGNMENT_METHODS, k).label)
        st.caption("MILP methods use the solver chosen in step 3; metaheuristics share one search budget "
                   "(25 × 16 by default, or the values set in step 3) and the time limit.")
    elif factor == "solver":
        levels = st.multiselect("Solvers", [o.key for o in SOLVERS], key="f_lv_solver", persist_state=P,
                                format_func=lambda k: option(SOLVERS, k).label)
        if not option(ASSIGNMENT_METHODS, base.assignment).uses_solver:
            problems.append("To compare solvers, choose MILP or Greedy + MILP warm start in step 3.")
    elif factor == "movement":
        levels = st.multiselect("Movement profiles", [p.key for p in MOVEMENT_PROFILES], key="f_lv_movement",
                                persist_state=P, format_func=lambda k: next(p.label for p in MOVEMENT_PROFILES if p.key == k))
    elif factor == "num_robots":
        text = st.text_input("Robot counts", key="f_lv_robots", persist_state=P, help="For example: 6, 10, 14")
        levels, err = parse_int_list(text, 1, 500, 12)
        if err:
            problems.append(f"Robot counts: {err}")
    if factor != "seed" and not levels:
        problems.append("Choose at least one value to compare.")
    seeds_text = st.text_input("Random seeds (repeated trials)", key="f_seeds", persist_state=P,
                               help="Every configuration runs once per seed, with the same seeds for all "
                                    "configurations (matched trials). Examples: 1   or   1-5   or   1, 2, 7")
    seeds, err = parse_int_list(seeds_text, 0, 2_147_483_647, MAX_SEEDS_PER_STUDY)
    if err:
        problems.append(f"Seeds: {err}")
    if factor == "seed" and len(seeds) < 2:
        problems.append("Repeated trials need at least two seeds, e.g. 1-5.")
    st.checkbox("Warm up each code path first (recommended for fair computer-time comparisons)",
                key="f_study_warmup", persist_state=P)
    if problems:
        return [], problems
    planned = expand_study(base, factor, levels, seeds, batch_id="")
    for c in planned:
        c.warm_up = bool(st.session_state["f_study_warmup"])
    if len(planned) > MAX_RUNS_PER_STUDY:
        problems.append(f"This study has {len(planned)} runs; the limit is {MAX_RUNS_PER_STUDY}.")
    return planned, problems


# -----------------------------------------------------------------------------
# Run column
# -----------------------------------------------------------------------------

def _summary_sentence(v: Validation) -> str:
    r = v.resolved
    solver = f" with <b>{r.solver.label}</b>" if r.solver else ""
    return (f"<b>{r.model.name}</b> · <b>{r.num_robots}</b> robots ({r.robots_source}) · "
            f"<b>{r.assignment.label}</b>{solver} · <b>{r.movement.label}</b> movement · seed <b>{r.config.seed}</b>")


def _review_rows(v: Validation) -> list[tuple]:
    r, c = v.resolved, v.resolved.config
    args = r.demo_arguments()
    rows = [
        ("Model", f"{r.model.name} ({r.model.reference_parts} parts)", f"code:ldraw_file = {args['ldraw_file']}"),
        ("Robots", f"{r.num_robots} ({r.robots_source})", f"code:num_robots = {r.num_robots}"),
        ("Assignment", r.assignment.label, f"code:assignment_mode = {args['assignment_mode']}"),
        ("Solver", r.solver.label if r.solver else "not used",
         f"code:milp_optimizer = {args['milp_optimizer']}" if r.solver else ""),
    ]
    if r.solver:
        rows.append(("Optimizer time limit", f"{c.optimizer_time_limit_s} s", f"code:optimizer_time_limit = {c.optimizer_time_limit_s}"))
    if r.assignment.search:
        rows.append(("Search budget", f"{c.search_iterations} iterations × {c.search_population}, at most "
                                      f"{c.optimizer_time_limit_s} s",
                     f"code:metaheuristic_iterations = {c.search_iterations}, metaheuristic_population = "
                     f"{c.search_population}, optimizer_time_limit = {c.optimizer_time_limit_s}"))
    rows += [
        ("Movement", r.movement.label, f"code:rvo_flag = {r.movement.rvo}, tangent_bug_flag = {r.movement.tangent_bug}, "
                                       f"dispersion_flag = {r.movement.dispersion}"),
        ("Random seed", c.seed, f"code:rng = MersenneTwister({c.seed})"),
        ("3D animation", ("saved" + (", smooth" if c.smooth_animation else "")) if c.save_animation else "not saved",
         f"code:save_animation = {c.save_animation}"),
        ("Live preview", LIVE_PREVIEW_LABELS[c.live_preview] if c.save_animation else "Off",
         f"code:save_animation_along_the_way = {args['save_animation_along_the_way']}"),
        ("Step limits", f"{c.max_steps:,} steps; stop after {c.max_iters_no_progress:,} without progress",
         f"code:max_steps = {c.max_steps}, max_num_iters_no_progress = {c.max_iters_no_progress}"),
        ("Wall-clock limit", f"{r.timeout_min} min" if r.timeout_min else "No limit",
         "enforced by the dashboard" if r.timeout_min else "not enforced"),
    ]
    return rows


def _submit(items) -> None:
    try:
        ids = services.engine().submit(items)
    except RuntimeError as e:
        st.session_state["_submit_error"] = str(e)
        return
    st.session_state["current_runs"] = ids
    st.session_state.pop("_submit_error", None)


def _run_panel(cat: Catalog, report) -> None:
    eng = services.engine()
    snap = eng.snapshot()
    busy = bool(snap.active_run or snap.queue)
    base = _config_from_state()
    env = report.env_status()
    mode = st.session_state["f_mode"]

    if mode == "single":
        v = validate(base, cat, env)
        with st.container(border=True):
            if v.ok:
                st.html(f'<div class="cl-summary">{_summary_sentence(v)}</div>')
            for e in v.errors:
                theme.note(e, "err")
            n_warn = len(v.warnings)
            disabled = not v.ok or busy or bool(snap.read_only_reason)
            st.button("Run simulation", type="primary", width="stretch", disabled=disabled, icon=":material/play_arrow:",
                      on_click=_submit, args=([v.resolved],) if v.ok else ([],), key="run_btn")
            _blocked_reason(snap, busy)
            if v.ok:
                with st.expander("Review all settings" + (f" · {n_warn} note(s)" if n_warn else "")):
                    for w in v.warnings:
                        theme.note(w, "warn")
                    theme.kv_table(_review_rows(v), header=("Setting", "Value", "Passed to run_lego_demo as"))
    else:
        planned, problems = st.session_state.get("_planned", ([], []))
        with st.container(border=True):
            vals = [validate(c, cat, env) for c in planned]
            errors = list(dict.fromkeys(e for v in vals for e in v.errors)) + problems
            warnings = list(dict.fromkeys(w for v in vals for w in v.warnings))
            ok = planned and not errors
            if ok:
                factor = STUDY_FACTORS[st.session_state["f_factor"]].lower()
                st.html(f'<div class="cl-summary">Study of <b>{factor}</b> on <b>{vals[0].resolved.model.name}</b>: '
                        f'<b>{len(planned)}</b> runs, everything else fixed.</div>')
            for e in errors:
                theme.note(e, "err")
            batch_id = f"study-{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
            items = []
            if ok:
                for v in vals:
                    v.resolved.config.batch_id = batch_id
                    items.append(v.resolved)
            st.button(f"Run study ({len(planned)} runs)" if planned else "Run study", type="primary", width="stretch",
                      disabled=not ok or busy or bool(snap.read_only_reason), icon=":material/play_arrow:",
                      on_click=_submit, args=(items,), key="run_study_btn")
            _blocked_reason(snap, busy)
            if ok:
                with st.expander("Planned runs" + (f" · {len(warnings)} note(s)" if warnings else "")):
                    for w in warnings:
                        theme.note(w, "warn")
                    theme.kv_table([(i + 1, v.resolved.label, f"seed {v.resolved.config.seed}")
                                    for i, v in enumerate(vals)], header=("#", "Configuration", "Seed"))
    if st.session_state.get("_submit_error"):
        theme.note(st.session_state["_submit_error"], "err")


def _blocked_reason(snap, busy: bool) -> None:
    if snap.read_only_reason:
        st.caption(snap.read_only_reason)
    elif busy:
        n = len(snap.queue) + (1 if snap.active_run else 0)
        st.caption(f"A simulation is in progress ({n} run(s) running or queued). New runs can start when it finishes, "
                   "or cancel it below.")


def _display_run_id() -> str | None:
    """The run shown in the monitor: the first unfinished run of this session's latest submission,
    otherwise its last run; after a page reload, the engine's active run."""
    ids = st.session_state.get("current_runs") or []
    if ids:
        recs = [services.run(i) for i in ids]
        for i, r in zip(ids, recs):
            if r is not None and not r.is_final:
                return i
        return ids[-1]
    snap = services.engine().snapshot()
    if snap.active_run:
        st.session_state["current_runs"] = [snap.active_run] + list(snap.queue)
        return snap.active_run
    # After a browser refresh: keep showing a run that finished within the last hour.
    recent = services.runs()
    if recent:
        try:
            age = (datetime.now() - datetime.fromisoformat(recent[0].created_at)).total_seconds()
        except ValueError:
            age = None
        if age is not None and age < 3600:
            return recent[0].run_id
    return None


@st.fragment(run_every=1.5)
def _monitor() -> None:
    run_id = _display_run_id()
    if run_id != st.session_state.get("_viewer_run"):
        st.session_state["_viewer_run"] = run_id
        st.rerun()   # the viewer below must switch to the new run
    if run_id is None:
        return
    rec = services.run(run_id)
    if rec is None:
        return
    eng = services.engine()
    snap = eng.snapshot()
    ids = st.session_state.get("current_runs") or [run_id]
    batch_note = f" · run {ids.index(run_id) + 1} of {len(ids)}" if len(ids) > 1 and run_id in ids else ""
    elapsed = rec.elapsed_seconds()
    head, action = st.columns([6, 1.4], vertical_alignment="center")
    head.html(f'<div class="cl-runhead">{theme.pill(rec.state_label, rec.state)}<span class="title">'
              f'{escape(rec.label)}</span><span class="cl-muted">{escape(rec.run_id + batch_note)}</span></div>')

    if rec.state == "queued":
        if snap.state == "starting" and snap.started_at:
            st.caption(f"Starting the simulation engine: loading Julia and the simulator "
                       f"({fmt_duration(time.time() - snap.started_at)} so far, usually 20–60 s).")
        elif snap.state == "error":
            theme.note("The simulation engine could not start: " + snap.last_error, "err")
        else:
            st.caption("Waiting for the simulation engine.")
    elif rec.state == "running":
        prog = rec.progress()
        st.markdown(f"**{prog.phase}** · {fmt_duration(elapsed)} elapsed")
        if prog.fraction is not None and prog.phase_index >= 10:
            st.progress(prog.fraction, text=f"Schedule tasks completed: {prog.closed} of {prog.total}")
        else:
            note = "No reliable percentage exists for this phase."
            if snap.runs_completed == 0:
                note += " First run in this engine session: Julia compiles code as it goes (adds 1–2 min)."
            st.caption(note)
    if not rec.is_final:
        with action.popover("Cancel", icon=":material/stop_circle:", width="stretch"):
            st.markdown("Stopping a running simulation stops the simulation engine. Partial output is kept, and the "
                        "next run restarts the engine (about 20–60 s).")
            if st.button("Stop this run", type="primary", key=f"cancel_{run_id}"):
                ok, msg = eng.cancel(run_id)
                st.session_state["_cancel_msg"] = msg
                st.rerun()
            if len(ids) > 1 and st.button("Cancel the remaining queued runs", key=f"cancelq_{run_id}"):
                batch = rec.settings.get("batch_id") or None
                n = eng.cancel_queue(batch)
                st.session_state["_cancel_msg"] = f"{n} queued run(s) cancelled."
                st.rerun()
        if st.session_state.get("_cancel_msg"):
            st.caption(st.session_state.pop("_cancel_msg"))
    else:
        _result_summary(rec)


def _result_summary(rec) -> None:
    if rec.state == "success":
        theme.note(rec.detail, "ok")
    elif rec.state in ("failed", "rejected"):
        theme.note(rec.detail, "err")
    else:
        theme.note(rec.detail, "warn")
    items = []
    if rec.metric("makespan_s") is not None:
        items.append(("Completion time", fmt_num(rec.metric("makespan_s"), 2, "s"), "simulated time (makespan)"))
    if rec.metric("optimistic_makespan_s") is not None:
        items.append(("Planned completion", fmt_num(rec.metric("optimistic_makespan_s"), 2, "s"),
                      "simulated, schedule estimate"))
    if rec.metric("robot_min_gap_m") is not None:
        items.append(("Smallest robot gap", fmt_num(rec.metric("robot_min_gap_m"), 3, "m"), "negative means overlap"))
    if rec.metric("assignment_time_s") is not None:
        items.append(("Assignment time", fmt_num(rec.metric("assignment_time_s"), 2, "s"), "computer time"))
    if rec.metric("total_wall_time_s") is not None:
        items.append(("Total run time", fmt_duration(rec.metric("total_wall_time_s")), "computer time"))
    if items:
        theme.metric_strip(items)
    rep = rec.solver_report()
    notes = []
    if rep and rep.label:
        notes.append(f"Solver: {rep.label}.")
    if rec.result.get("includes_compilation"):
        notes.append("Computer times include one-time code compilation (first run of this kind in the engine session).")
    if rec.result.get("search_evaluations") is not None:
        notes.append(f"Search: {rec.result['search_evaluations']:,} candidate schedules evaluated"
                     + (" before the time limit stopped it." if rec.result.get("search_timed_out") else "."))
    if notes:
        st.caption(" ".join(notes))
    history = rec.result.get("search_history") or []
    if len(history) > 1:
        st.line_chart({"best planned completion [s]": history}, x_label="iteration (0 = Greedy's task order)",
                      y_label="planned completion [s]", height=220)
    if rec.state in ("failed", "rejected"):
        err = read_text(rec.folder / "error.txt", 20_000)
        if err:
            with st.expander("Error details"):
                st.code(err[-6000:], language=None)
        log = tail_text(rec.stdout_path, 6000)
        if log:
            with st.expander("End of the simulator log"):
                st.code(log, language=None)
    c1, c2 = st.columns(2)
    if c1.button("Open in experiment history", key=f"hist_{rec.run_id}", width="stretch"):
        nav.go("history", hist_selected=rec.run_id)
    if c2.button("Compare with other runs", key=f"cmp_{rec.run_id}", width="stretch"):
        nav.go("compare", cmp_preselect=[rec.run_id])


def _viewer() -> None:
    run_id = st.session_state.get("_viewer_run") or _display_run_id()
    st.session_state["_viewer_run"] = run_id
    if run_id is None:
        theme.empty_state("No simulation running",
                          "Choose settings on the left and press Run simulation. The real simulator's 3D output "
                          "appears here: a live preview while it runs, then a replay you can scrub through.")
        return
    url = services.viewer_server().player_url(run_id)
    st.iframe(url, height=600)


# -----------------------------------------------------------------------------
# Page
# -----------------------------------------------------------------------------

def render() -> None:
    cat = services.catalog()
    theme.page_header("New simulation", "Choose a model and methods, run the real ConstructionBots simulator, and "
                      "watch the robots build it.", eyebrow="Workspace")
    if cat.error or not cat.models:
        theme.note(cat.error or "No models were found in the registry.", "err")
        nav.link("diagnostics", "Open System diagnostics", icon=":material/monitor_heart:")
        return
    _init_state(cat)
    report = services.diagnostics()
    history = services.runs()

    left, right = st.columns([5, 7], gap="large")
    with left:
        st.segmented_control("What do you want to run?", ["single", "study"], key="f_mode", required=True,
                             persist_state=P, width="stretch",
                             format_func=lambda k: "Single run" if k == "single" else "Comparison study")
        _model_section(cat, history)
        _robots_section(cat)
        _assignment_section(report)
        _movement_section()
        if st.session_state["f_mode"] == "study":
            st.session_state["_planned"] = _study_section(_config_from_state())
        _advanced_section(cat)
        if not report.checked:
            st.caption("System checks have not been run yet, so solver and RVO2 availability are not verified. "
                       "See System diagnostics.")
    with right:
        _run_panel(cat, report)
        _monitor()
        _viewer()
