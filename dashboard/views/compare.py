"""Compare experiments: side-by-side results of runs that differ in one factor."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from simulation.catalog import SAFETY_NOTE
from simulation.compare import (FACTORS, Group, deduplicate, differences, find_groups, level_of, paired_comparison,
                                spearman, summarize)
from simulation.results import RunRecord, save_export, to_csv_bytes
from ui import charts, nav, services, theme

P = "session"

FACTOR_TO_STUDY = {"assignment": "assignment", "solver": "solver", "movement": "movement", "num_robots": "num_robots",
                   "seed": "seed"}


def _run_option(r: RunRecord) -> str:
    return f"{r.label} · seed {r.settings.get('seed')} · {r.state_label} · {r.run_id}"


def _frames(runs: list[RunRecord], factor: str | None, levels: list[str], metric: str):
    summ = summarize(runs, factor, levels)
    rows, srows = [], []
    for s in summ:
        extra = f", {s.other_states}" if s.other_states else ""
        level_name = s.level if factor else next((r.label for r in runs if r.run_id == s.level), s.level)
        axis = f"{_short(level_name)}|n={s.n_success}{extra}"
        rs = [r for r in runs if (level_of(r, factor) if factor else r.run_id) == s.level]
        vals = [r.metric(metric) for r in rs if r.state == "success" and r.metric(metric) is not None]
        for r in rs:
            v = r.metric(metric) if r.state == "success" else None
            rows.append({"level": s.level, "axis_label": axis, "value": v, "run_id": r.run_id,
                         "seed": r.settings.get("seed"), "status": r.state_label,
                         "robots": r.resolved.get("num_robots")})
        srows.append({"level": s.level, "axis_label": axis, "n": len(vals),
                      "mean": sum(vals) / len(vals) if vals else None, "min": min(vals) if vals else None,
                      "max": max(vals) if vals else None,
                      "robots": rs[0].resolved.get("num_robots") if rs else None})
    return pd.DataFrame(rows), pd.DataFrame(srows), summ


def _short(text: str, width: int = 22) -> str:
    """Wrap a label onto lines of about `width` characters ('|' is the chart's line break)."""
    lines, cur = [], ""
    for word in text.split(" "):
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    lines.append(cur)
    return "|".join(lines[:3])


def _runs_table(runs: list[RunRecord], factor: str | None) -> None:
    rows = []
    for r in runs:
        rep = r.solver_report()
        rows.append({
            "Compared value": level_of(r, factor) if factor else r.label,
            "Seed": r.settings.get("seed"), "Status": r.state_label,
            "Completion [sim s]": r.metric("makespan_s"), "Planned [sim s]": r.metric("optimistic_makespan_s"),
            "Robot gap [m]": r.metric("robot_min_gap_m"), "Overlap steps": r.result.get("robot_overlap_steps"),
            "Swaps": r.result.get("position_swaps"),
            "Assignment [cpu s]": r.metric("assignment_time_s"), "Total [cpu s]": r.metric("total_wall_time_s"),
            "Solver result": (rep.short if rep else ("not used" if not r.resolved.get("solver_key") else "—")),
            "Includes compilation": {True: "yes", False: "no"}.get(r.result.get("includes_compilation"), "—"),
            "Run ID": r.run_id,
        })
    df = pd.DataFrame(rows)
    for c in ("Completion [sim s]", "Planned [sim s]", "Robot gap [m]", "Overlap steps", "Swaps", "Assignment [cpu s]", "Total [cpu s]"):
        df[c] = pd.to_numeric(df[c], errors="coerce")   # missing values show as blank, never "None" or 0
    st.dataframe(df, hide_index=True, column_config={
        "Solver result": st.column_config.TextColumn(help="The MILP solver's own status"),
        "Robot gap [m]": st.column_config.NumberColumn(format="%.3f", help="Smallest gap between two free robots; negative means overlap"),
        "Completion [sim s]": st.column_config.NumberColumn(format="%.2f"),
        "Planned [sim s]": st.column_config.NumberColumn(format="%.2f"),
        "Assignment [cpu s]": st.column_config.NumberColumn(format="%.2f"),
        "Total [cpu s]": st.column_config.NumberColumn(format="%.1f"),
    })


def _summary_table(summ) -> None:
    rows = [{"Compared value": s.level, "Successful runs": f"{s.n_success} of {s.n_runs}", "Other runs": s.other_states or "—",
             "Mean [sim s]": s.mean, "95% CI low": s.ci_low, "95% CI high": s.ci_high,
             "Std. dev. [sim s]": s.sd, "Min [sim s]": s.min, "Max [sim s]": s.max,
             "Mean planned [sim s]": s.mean_planned, "Runs with overlap": s.runs_with_overlap,
             "Smallest robot gap [m]": s.min_robot_gap, "Swaps": s.total_swaps,
             "Mean assignment [cpu s]": s.mean_assignment_cpu}
            for s in summ]
    num = ("Mean [sim s]", "95% CI low", "95% CI high", "Std. dev. [sim s]", "Min [sim s]", "Max [sim s]",
           "Mean planned [sim s]", "Smallest robot gap [m]", "Mean assignment [cpu s]")
    df = pd.DataFrame(rows)
    for c in num:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    st.dataframe(df, hide_index=True, column_config={c: st.column_config.NumberColumn(format="%.2f") for c in num})


def _paired_table(runs: list[RunRecord], factor: str, levels: list[str]) -> None:
    baseline = next((lv for lv in levels if lv == "Greedy"), levels[0])
    results = paired_comparison(runs, factor, baseline)
    if not results or max(p.n_pairs for p in results) < 2:
        return
    theme.section(f"Against {baseline}, seed by seed", "positive gain means faster than the baseline")
    df = pd.DataFrame([{"Compared value": p.level, "Matched seeds": p.n_pairs, "Mean gain [sim s]": p.mean_gain,
                        "95% CI low": p.ci_low, "95% CI high": p.ci_high, "Effect size dz": p.effect_size,
                        "Wins / losses": f"{p.wins} / {p.losses}", "p (sign-flip)": p.p_value, "p (Holm)": p.p_holm}
                       for p in results])
    st.dataframe(df, hide_index=True, column_config={c: st.column_config.NumberColumn(format="%.3f") for c in
                 ("Mean gain [sim s]", "95% CI low", "95% CI high", "Effect size dz", "p (sign-flip)", "p (Holm)")})
    if max(p.n_pairs for p in results) < 6:
        st.caption("With fewer than 6 matched seeds this test cannot reach p < 0.05 at all. Run more seeds before "
                   "drawing a conclusion.")
    pairs = [(r.metric("optimistic_makespan_s"), r.metric("makespan_s")) for r in runs if r.state == "success"
             and r.metric("optimistic_makespan_s") is not None and r.metric("makespan_s") is not None]
    if len(pairs) >= 5:
        st.caption(f"Does the plan predict the simulation? Spearman rank correlation of planned and simulated "
                   f"completion time over these {len(pairs)} runs: {spearman(*zip(*pairs)):.2f}. Across different methods "
                   "this is often driven by the worst methods, so a high value does not show that small planned gains "
                   "carry over.")


def _results(runs: list[RunRecord], factor: str | None, levels: list[str]) -> None:
    paths = services.paths()
    if factor:
        unique = deduplicate(runs)
        if len(unique) < len(runs):
            st.caption(f"{len(runs) - len(unique)} repeated run(s) of the same settings, seed and code are hidden: "
                       "a repeat gives the same result, so counting it would overstate the evidence.")
        runs = unique
    sim_diff, timing_diff = differences(runs)
    if factor is None:
        if len(sim_diff) > 1:
            theme.note("These runs differ in more than one setting (" + ", ".join(sim_diff) + "). Differences in the "
                       "results cannot be attributed to a single factor.", "warn", "Not a controlled comparison.")
        elif sim_diff:
            st.caption("Setting that differs between the selected runs: " + sim_diff[0] + ".")
        else:
            st.caption("The selected runs have identical simulation settings.")
    if factor and factor != "seed":
        per_level = {lv: {r.settings.get("seed") for r in runs if level_of(r, factor) == lv} for lv in levels}
        seed_sets = list(per_level.values())
        common = set.intersection(*seed_sets) if seed_sets else set()
        if seed_sets and all(s == seed_sets[0] for s in seed_sets):
            st.caption("Seeds " + ", ".join(str(s) for s in sorted(seed_sets[0])) +
                       " are matched across all compared values (same robot start positions).")
        elif st.toggle("Use only seeds that every compared value was run with (fair comparison)", value=True,
                       key=f"cmp_matched_{factor}"):
            if common:
                hidden = sum(1 for r in runs if r.settings.get("seed") not in common)
                runs = [r for r in runs if r.settings.get("seed") in common]
                st.caption(f"Showing seed(s) {', '.join(str(s) for s in sorted(common))}, shared by all compared values. "
                           f"{hidden} run(s) with other seeds are hidden.")
            else:
                theme.note("No seed was run for every compared value, so all runs are shown and robot start positions "
                           "differ between the compared values.", "warn")
        else:
            theme.note("All seeds are shown: robot start positions differ between the compared values.", "warn")
    _, timing_diff = differences(runs)
    if timing_diff:
        theme.note("Computer-time results mix runs with different settings for: " + ", ".join(timing_diff) +
                   ". Compare computer times with care; simulated times are not affected.", "info")

    rdf, sdf, summ = _frames(runs, factor, levels, "makespan_s")
    if sdf["mean"].notna().sum() == 0:
        theme.empty_state("No completed runs in this selection", "Completion times exist only for runs that finished "
                          "the project. The table below lists what happened to each run.")
    else:
        theme.section("Simulated completion time", "makespan, in simulated seconds; dots are runs, the dark tick is the mean")
        if factor == "num_robots":
            sdf["robots"] = pd.to_numeric(sdf["level"], errors="coerce")
            rdf["robots"] = pd.to_numeric(rdf["level"], errors="coerce")
            st.altair_chart(charts.line_by_robots(rdf, sdf, "Completion time [simulated s]"), width="stretch")
        else:
            order = levels if factor else [r.run_id for r in runs]
            st.altair_chart(charts.outcome_by_level(rdf, sdf, "value", "Completion time [simulated s]",
                                                    FACTORS.get(factor, "Run") if factor else "Run", order),
                            width="stretch")
    cpu_metric = "assignment_time_s" if factor in ("assignment", "solver") else "total_wall_time_s"
    cpu_title = "Assignment computer time [s]" if cpu_metric == "assignment_time_s" else "Total computer time [s]"
    crdf, csdf, _ = _frames(runs, factor, levels, cpu_metric)
    if csdf["mean"].notna().sum() and factor != "num_robots":
        theme.section("Computer time", "wall-clock seconds on this computer, not simulated time")
        order = levels if factor else [r.run_id for r in runs]
        st.altair_chart(charts.outcome_by_level(crdf, csdf, "value", cpu_title,
                                                FACTORS.get(factor, "Run") if factor else "Run", order, height=260),
                        width="stretch")
        if any(r.result.get("includes_compilation") for r in runs if r.state == "success"):
            st.caption("Some runs include one-time code compilation (marked in the table). Use 'Warm up first' when "
                       "computer time matters.")
    if any(r.resolved.get("rvo") is False or (r.result.get("robot_overlap_steps") or 0) > 0 for r in runs):
        theme.note(SAFETY_NOTE + " Do not read a faster completion with collision avoidance switched off as a better "
                   "method.", "warn", "Safety limitation.")
    if any(not r.source_hash for r in runs):
        theme.note("Some of these runs are older than the code-version record, and older builds could give different "
                   "results for the same settings. Treat them as indicative, and rerun before relying on them.", "warn")
    if any(r.resolved.get("solver_key") for r in runs):
        theme.note("MILP runs stop at the optimizer time limit. A schedule found by then is feasible but not "
                   "necessarily optimal (see the solver result column), so a MILP row means \"this solver for this "
                   "long\". With a time limit the outcome can also vary between repeated runs on the same computer.", "info")

    theme.section("Summary", "successful runs only; other outcomes are counted, never averaged in")
    _summary_table(summ)
    if factor and factor != "seed":
        _paired_table(runs, factor, levels)
    theme.section("All runs in this comparison")
    _runs_table(runs, factor)
    c1, c2, _ = st.columns([2, 2, 4])
    c1.download_button("Download comparison (CSV)", to_csv_bytes(runs, paths), file_name="constructionlab_comparison.csv",
                       mime="text/csv", icon=":material/download:", width="stretch")
    if c2.button("Save to exports", icon=":material/save:", width="stretch"):
        p = save_export(runs, paths, f"comparison_{factor or 'selection'}")
        st.toast(f"Saved {paths.display(p)}")


def render() -> None:
    theme.page_header("Compare experiments", "Put runs side by side. Fair comparisons change one factor and keep "
                      "everything else (model, robots, movement, seeds) fixed.", eyebrow="Results")
    records = [r for r in services.runs() if r.is_final]
    if not records:
        theme.empty_state("Nothing to compare yet", "Finished runs appear here. The quickest way to get a fair "
                          "comparison is a Comparison study on the New simulation page.")
        nav.link("new", "Go to New simulation", icon=":material/play_circle:")
        return
    pre = st.session_state.pop("cmp_preselect", None)
    if pre:
        st.session_state["cmp_mode"] = "pick"
        st.session_state["cmp_runs"] = [r for r in pre if any(x.run_id == r for x in records)]
    st.session_state.setdefault("cmp_mode", "guided")
    st.segmented_control("How to choose runs", ["guided", "pick"], key="cmp_mode", required=True, persist_state=P,
                         format_func=lambda k: "Find comparable runs" if k == "guided" else "Pick runs myself")
    if st.session_state["cmp_mode"] == "guided":
        st.session_state.setdefault("cmp_factor", "assignment")
        st.selectbox("Compare by", list(FACTORS), key="cmp_factor", persist_state=P, format_func=FACTORS.get)
        factor = st.session_state["cmp_factor"]
        groups: list[Group] = find_groups(records, factor)
        if not groups:
            theme.empty_state("No comparable runs for this factor yet",
                              f"A comparison by {FACTORS[factor].lower()} needs finished runs that differ only in that "
                              "setting. Plan one as a Comparison study on the New simulation page.")
            if st.button("Plan this study", icon=":material/science:"):
                nav.go("new", f_mode="study", f_factor=FACTOR_TO_STUDY[factor])
            return
        labels = [f"{g.description} — {len(g.levels)} values, {len(g.runs)} runs" for g in groups]
        idx = st.selectbox("Comparable set", range(len(groups)), format_func=lambda i: labels[i], key="cmp_group")
        g = groups[idx or 0]
        held = [f"{k.replace('_', ' ')}: {v}" for k, v in g.key if v not in ("not used",)]
        st.html(theme.chips([("Held fixed", None)] + [(h, None) for h in held]))
        _results(g.runs, factor, g.levels)
    else:
        opts = [r.run_id for r in records]
        st.session_state.setdefault("cmp_runs", [])
        st.multiselect("Runs to compare", opts, key="cmp_runs", persist_state=P,
                       format_func=lambda rid: _run_option(next(r for r in records if r.run_id == rid)),
                       placeholder="Choose two or more runs")
        chosen = [r for r in records if r.run_id in st.session_state["cmp_runs"]]
        if len(chosen) < 2:
            st.caption("Choose at least two runs. Tip: select runs in Experiment history and press Compare selected.")
            return
        _results(chosen, None, [r.run_id for r in chosen])
