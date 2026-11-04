"""Charts (Altair). Conventions: thin marks, 2 px lines, ringed dots, solid hairline grids,
tooltips on every mark, text in text colours (never the series colour), and colour that
follows the entity. Failed runs are never plotted as zeros: they are counted in the axis
labels and listed in the tables shown next to each chart."""
from __future__ import annotations

import altair as alt
import pandas as pd

from .theme import PALETTE, SERIES

FONT = "Inter, 'IBM Plex Sans', 'Segoe UI', system-ui, -apple-system, Arial, sans-serif"
SURFACE = "#FFFFFF"
GRID = "#E7EBEC"

# Fixed colour per assignment method (colour follows the entity on every page).
ASSIGNMENT_COLORS = {"Greedy": SERIES[0], "MILP": SERIES[1], "Greedy + MILP warm start": SERIES[2],
                     "Most complex first": "#5B9BB0", "Nearest station first": "#6A994E",
                     "Genetic algorithm": SERIES[3], "Particle swarm": "#B8574A", "Simulated annealing": "#A68A2B"}


def _style(chart: alt.Chart, height: int = 300) -> alt.Chart:
    return (chart.properties(height=height, width="container", background=SURFACE,
                             padding={"left": 8, "right": 12, "top": 10, "bottom": 6})
            .configure(font=FONT)
            .configure_view(stroke=None)
            .configure_axis(gridColor=GRID, gridWidth=1, domainColor="#C9D1D4", tickColor="#C9D1D4",
                            labelColor=PALETTE["muted"], titleColor=PALETTE["text"], labelFontSize=11.5,
                            titleFontSize=12, titleFontWeight=600, labelLimit=220)
            .configure_legend(labelColor=PALETTE["text"], titleColor=PALETTE["muted"], labelFontSize=12,
                              titleFontSize=11.5, orient="top", direction="horizontal", symbolSize=90)
            .configure_title(color=PALETTE["text"], fontSize=13, fontWeight=600, anchor="start"))


def outcome_by_level(runs: pd.DataFrame, summary: pd.DataFrame, value: str, y_title: str, level_title: str,
                     order: list[str], height: int = 300) -> alt.Chart:
    """Dot plot: every successful run as a dot, the mean as a short dark tick, the min–max range as a rule.
    `runs` columns: level, axis_label, value, run_id, seed, status; `summary`: level, axis_label, mean, min, max."""
    labels = [summary.loc[summary["level"] == lv, "axis_label"].iloc[0] for lv in order if lv in set(summary["level"])]
    x = alt.X("axis_label:N", sort=labels, title=level_title,
              axis=alt.Axis(labelAngle=0, labelExpr="split(datum.label, '|')", labelLineHeight=14))
    ok = summary.dropna(subset=["mean"])
    rng = (alt.Chart(ok).mark_rule(color=PALETTE["muted"], strokeWidth=1.5)
           .encode(x=x, y=alt.Y("min:Q"), y2="max:Q"))
    dots = (alt.Chart(runs.dropna(subset=["value"])).mark_circle(size=80, color=SERIES[0], opacity=0.9,
                                                                 stroke=SURFACE, strokeWidth=2)
            .encode(x=x, y=alt.Y("value:Q", title=y_title, scale=alt.Scale(zero=True)),
                    tooltip=[alt.Tooltip("level:N", title=level_title), alt.Tooltip("value:Q", title=y_title, format=".2f"),
                             alt.Tooltip("seed:Q", title="Seed"), alt.Tooltip("run_id:N", title="Run")]))
    mean = (alt.Chart(ok).mark_tick(color=PALETTE["navy"], thickness=2.5, size=30)
            .encode(x=x, y="mean:Q",
                    tooltip=[alt.Tooltip("level:N", title=level_title), alt.Tooltip("mean:Q", title="Mean", format=".2f"),
                             alt.Tooltip("n:Q", title="Successful runs")]))
    label = (alt.Chart(ok).mark_text(align="left", dx=20, fontSize=11.5, color=PALETTE["text"])
             .encode(x=x, y="mean:Q", text=alt.Text("mean:Q", format=".2f")))
    return _style(alt.layer(rng, dots, mean, label), height)


def line_by_robots(runs: pd.DataFrame, summary: pd.DataFrame, y_title: str, height: int = 300) -> alt.Chart:
    """Mean outcome against the number of robots (2 px line) with every successful run as a dot."""
    line = (alt.Chart(summary.dropna(subset=["mean"])).mark_line(color=SERIES[0], strokeWidth=2, strokeCap="round")
            .encode(x=alt.X("robots:Q", title="Number of robots", axis=alt.Axis(tickMinStep=1, format="d")),
                    y=alt.Y("mean:Q", title=y_title, scale=alt.Scale(zero=True))))
    dots = (alt.Chart(runs.dropna(subset=["value"])).mark_circle(size=80, color=SERIES[0], stroke=SURFACE, strokeWidth=2)
            .encode(x="robots:Q", y="value:Q",
                    tooltip=[alt.Tooltip("robots:Q", title="Robots"), alt.Tooltip("value:Q", title=y_title, format=".2f"),
                             alt.Tooltip("seed:Q", title="Seed"), alt.Tooltip("run_id:N", title="Run")]))
    label = (alt.Chart(summary.dropna(subset=["mean"])).mark_text(dy=-12, fontSize=11.5, color=PALETTE["text"])
             .encode(x="robots:Q", y="mean:Q", text=alt.Text("mean:Q", format=".1f")))
    return _style(alt.layer(line, dots, label), height)


def scatter(df: pd.DataFrame, x: str, y: str, x_title: str, y_title: str, color: str, color_title: str,
            shape: str | None = None, shape_title: str = "", diagonal: bool = False, height: int = 390) -> alt.Chart:
    """Scatter with colour = assignment method (fixed colours) and optional shape = a second category."""
    domain = [k for k in ASSIGNMENT_COLORS if k in set(df[color])]
    extra = [k for k in sorted(set(df[color])) if k not in ASSIGNMENT_COLORS]
    domain += extra
    rng = [ASSIGNMENT_COLORS.get(k, SERIES[3]) for k in domain]
    enc = dict(
        x=alt.X(f"{x}:Q", title=x_title, scale=alt.Scale(zero=True)),
        y=alt.Y(f"{y}:Q", title=y_title, scale=alt.Scale(zero=True)),
        color=alt.Color(f"{color}:N", title=color_title, scale=alt.Scale(domain=domain, range=rng),
                        legend=alt.Legend(orient="top", direction="horizontal")),
        tooltip=[alt.Tooltip("label:N", title="Configuration"), alt.Tooltip(f"{x}:Q", title=x_title, format=".2f"),
                 alt.Tooltip(f"{y}:Q", title=y_title, format=".2f"), alt.Tooltip("random_seed:Q", title="Seed"),
                 alt.Tooltip("run_id:N", title="Run")],
    )
    if shape:
        # Second legend below the plot, wrapped, so both legends stay fully visible at laptop widths.
        enc["shape"] = alt.Shape(f"{shape}:N", title=shape_title,
                                 legend=alt.Legend(orient="bottom", direction="horizontal", columns=2,
                                                   symbolFillColor=PALETTE["muted"], symbolStrokeColor=PALETTE["muted"]))
    pts = alt.Chart(df).mark_point(size=90, filled=True, opacity=0.9, stroke=SURFACE, strokeWidth=1.5).encode(**enc)
    layers = [pts]
    if diagonal and len(df):
        hi = float(max(df[x].max(), df[y].max())) * 1.05
        ref = pd.DataFrame({x: [0.0, hi], y: [0.0, hi]})
        layers.insert(0, alt.Chart(ref).mark_line(color="#AEB8BE", strokeWidth=1).encode(x=f"{x}:Q", y=f"{y}:Q"))
    return _style(alt.layer(*layers), height)


def status_bars(counts: pd.DataFrame, height: int = 220) -> alt.Chart:
    """Horizontal bars of run counts per outcome (one series: slot-1 colour; the label names the outcome)."""
    order = list(counts.sort_values("runs", ascending=False)["status"])
    y = alt.Y("status:N", title=None, sort=order)
    bars = (alt.Chart(counts).mark_bar(color=SERIES[0], size=18, cornerRadiusEnd=4)
            .encode(y=y, x=alt.X("runs:Q", title="Runs", axis=alt.Axis(tickMinStep=1, format="d")),
                    tooltip=[alt.Tooltip("status:N", title="Outcome"), alt.Tooltip("runs:Q", title="Runs")]))
    text = (alt.Chart(counts).mark_text(align="left", dx=5, fontSize=11.5, color=PALETTE["text"])
            .encode(y=y, x="runs:Q", text="runs:Q"))
    return _style(alt.layer(bars, text), height)
