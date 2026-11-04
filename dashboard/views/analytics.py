"""Analytics: aggregate views over all saved runs of one model."""
from __future__ import annotations

from collections import Counter

import pandas as pd
import streamlit as st

from simulation.compare import config_key, config_label
from simulation.results import RunRecord
from ui import charts, nav, services, theme

P = "session"


def render() -> None:
    theme.page_header("Analytics", "Aggregate views over every saved run of one model: how each configuration "
                      "performed, how far execution drifted from the plan, and what planning time bought.",
                      eyebrow="Results")
    records = [r for r in services.runs() if r.is_final]
    if not records:
        theme.empty_state("No finished runs yet", "Analytics summarise finished runs. Start with a simulation or a "
                          "comparison study.")
        nav.link("new", "Go to New simulation", icon=":material/play_circle:")
        return
    by_model = Counter(r.model_name for r in records)
    models = [m for m, _ in by_model.most_common()]
    st.session_state.setdefault("an_model", models[0])
    if st.session_state["an_model"] not in models:
        st.session_state["an_model"] = models[0]
    c1, c2 = st.columns([2, 3])
    c1.selectbox("Model", models, key="an_model", persist_state=P,
                 format_func=lambda m: f"{m} ({by_model[m]} finished runs)",
                 help="Completion times of different models are not comparable, so analytics are per model.")
    with c2:
        st.space("small")
        st.caption("All charts use only runs of this model. Statistics use successful runs; other outcomes are "
                   "counted separately.")
    runs = [r for r in records if r.model_name == st.session_state["an_model"]]

    # 1. Per-configuration summary --------------------------------------------------------
    theme.section("Configurations", "one row per configuration; repeated seeds are grouped")
    groups: dict[tuple, list[RunRecord]] = {}
    for r in runs:
        groups.setdefault(config_key(r), []).append(r)   # every simulation setting except the seed
    rows = []
    for rs in groups.values():
        label = config_label(rs[0])
        ok = [r for r in rs if r.state == "success" and r.metric("makespan_s") is not None]
        vals = [r.metric("makespan_s") for r in ok]
        mean = sum(vals) / len(vals) if vals else None
        sd = None
        if len(vals) > 1:
            sd = (sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5
        cpu = [r.metric("total_wall_time_s") for r in ok if r.metric("total_wall_time_s") is not None]
        rows.append({"Configuration": label, "Runs": len(rs), "Completed": len(ok),
                     "Completion rate": len(ok) / len(rs) if rs else None,
                     "Mean completion [sim s]": mean, "Std. dev. [sim s]": sd,
                     "Best [sim s]": min(vals) if vals else None, "Worst [sim s]": max(vals) if vals else None,
                     "Mean total [cpu s]": sum(cpu) / len(cpu) if cpu else None,
                     "Seeds": ", ".join(str(x) for x in sorted({r.settings.get("seed") for r in rs}))})
    table = pd.DataFrame(rows)
    for c in ("Completion rate", "Mean completion [sim s]", "Std. dev. [sim s]", "Best [sim s]", "Worst [sim s]",
              "Mean total [cpu s]"):
        table[c] = pd.to_numeric(table[c], errors="coerce")
    table = table.sort_values("Mean completion [sim s]", na_position="last")
    st.dataframe(table, hide_index=True, column_config={
        "Completion rate": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
        **{c: st.column_config.NumberColumn(format="%.2f") for c in
           ("Mean completion [sim s]", "Std. dev. [sim s]", "Best [sim s]", "Worst [sim s]")},
        "Mean total [cpu s]": st.column_config.NumberColumn(format="%.1f")})
    st.caption("With fewer than about five seeds per configuration, differences may be due to chance.")

    df = pd.DataFrame([{
        "run_id": r.run_id, "label": r.label, "random_seed": r.settings.get("seed"),
        "assignment": r.resolved.get("assignment_label", ""), "movement": r.resolved.get("movement_label", ""),
        "makespan": r.metric("makespan_s"), "planned": r.metric("optimistic_makespan_s"),
        "cpu": r.metric("total_wall_time_s"), "status": r.state_label,
    } for r in runs if r.state == "success"])

    left, right = st.columns(2, gap="large")
    with left:
        theme.section("Plan versus execution", "simulated seconds")
        d = df.dropna(subset=["makespan", "planned"]) if len(df) else df
        if len(d):
            st.altair_chart(charts.scatter(d, "planned", "makespan", "Planned completion [sim s]",
                                           "Executed completion [sim s]", "assignment", "Assignment",
                                           shape="movement", shape_title="Movement", diagonal=True), width="stretch")
            st.caption("The grey line marks execution = plan. Points above it took longer in simulation than the "
                       "schedule predicted, mostly because robots had to wait for, or steer around, each other and "
                       "active build sites.")
        else:
            theme.empty_state("No completed runs", "This chart needs completed runs of this model.")
    with right:
        theme.section("Outcome versus computer time", "is extra planning time paying off?")
        d = df.dropna(subset=["makespan", "cpu"]) if len(df) else df
        if len(d):
            st.altair_chart(charts.scatter(d, "cpu", "makespan", "Total computer time [s]",
                                           "Completion time [sim s]", "assignment", "Assignment",
                                           shape="movement", shape_title="Movement"), width="stretch")
            st.caption("Lower is better on both axes. Computer time includes one-time compilation for the first run "
                       "of each kind in an engine session.")
        else:
            theme.empty_state("No completed runs", "This chart needs completed runs of this model.")

    theme.section("Run outcomes", "every finished run of this model, including failures")
    counts = pd.DataFrame(Counter(r.state_label for r in runs).most_common(), columns=["status", "runs"])
    a, b = st.columns([3, 4], gap="large")
    with a:
        st.altair_chart(charts.status_bars(counts, height=max(120, 46 * len(counts))), width="stretch")
    with b:
        reasons = Counter((r.state_label, r.detail) for r in runs if r.state != "success")
        if reasons:
            st.dataframe(pd.DataFrame([{"Outcome": s, "Reason": d, "Runs": n} for (s, d), n in reasons.most_common()]),
                         hide_index=True)
        else:
            st.caption("Every finished run of this model completed the project.")
