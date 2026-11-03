"""ConstructionLab design system: palette, one stylesheet, and small HTML components.

All dynamic text passed to these helpers is HTML-escaped. Status is always shown as
text plus colour, never colour alone.
"""
from __future__ import annotations

from html import escape

import streamlit as st

PALETTE = {
    "page": "#F5F5F2", "surface": "#FFFFFF", "text": "#202A32", "muted": "#687581", "navy": "#17324D",
    "teal": "#147D83", "slate": "#456A8A", "amber": "#C88A43", "success": "#267653", "warning": "#9A6418",
    "error": "#B54747", "border": "#DDE2E4", "panel": "#EDF1EE",
}

# Categorical chart colours, in fixed order. Validated with the dataviz palette checker
# (light surface, all pairs): lightness band, chroma floor, colour-blind separation and the
# normal-vision floor pass; slot 2 is below 3:1 contrast, so charts always carry labels and a table.
SERIES = ["#2E6DA4", "#D08A35", "#1A9E80", "#8E4673"]

CSS = """
<style>
:root { --cl-text:#202A32; --cl-muted:#687581; --cl-navy:#17324D; --cl-teal:#147D83; --cl-slate:#456A8A;
        --cl-amber:#C88A43; --cl-ok:#267653; --cl-warn:#9A6418; --cl-err:#B54747; --cl-border:#DDE2E4;
        --cl-panel:#EDF1EE; --cl-surface:#FFFFFF; }
.block-container { padding-top: 2.0rem; padding-bottom: 3rem; max-width: 1440px; }
[data-testid="stSidebarNav"] { padding-top: .25rem; }
[data-testid="stSidebar"] [data-testid="stSidebarNavSeparator"] { border-color: #2C4A68; }
[data-testid="stSidebarHeader"] { padding-bottom: .5rem; }
footer { visibility: hidden; }
h1, h2, h3 { letter-spacing: -0.01em; }
.cl-eyebrow { text-transform: uppercase; letter-spacing: .08em; font-size: .72rem; font-weight: 600; color: var(--cl-teal); margin-bottom: .15rem; }
.cl-header { margin-bottom: 1.1rem; }
.cl-header h1 { font-size: 1.65rem; font-weight: 650; color: var(--cl-navy); margin: 0; padding: 0; line-height: 1.25; }
.cl-header p { color: var(--cl-muted); margin: .3rem 0 0; font-size: .95rem; max-width: 70ch; }
.cl-section { display: flex; align-items: baseline; gap: .6rem; margin: 1.1rem 0 .55rem; padding-bottom: .35rem; border-bottom: 1px solid var(--cl-border); }
.cl-section .num { display: inline-flex; align-items: center; justify-content: center; width: 1.25rem; height: 1.25rem; border-radius: 50%;
                   background: var(--cl-navy); color: #fff; font-size: .72rem; font-weight: 600; flex: none; transform: translateY(-1px); }
.cl-section h3 { font-size: 1rem; font-weight: 600; margin: 0; padding: 0; color: var(--cl-text); }
.cl-section .sub { color: var(--cl-muted); font-size: .84rem; }
.cl-pill { display: inline-flex; align-items: center; gap: .4rem; padding: .08rem .55rem; border-radius: 999px; font-size: .78rem;
           font-weight: 550; border: 1px solid; white-space: nowrap; line-height: 1.5; }
.cl-pill .dot { width: .45rem; height: .45rem; border-radius: 50%; background: currentColor; }
.cl-pill.ok { color: var(--cl-ok); border-color: rgba(38,118,83,.35); background: rgba(38,118,83,.07); }
.cl-pill.warn { color: var(--cl-warn); border-color: rgba(154,100,24,.35); background: rgba(200,138,67,.10); }
.cl-pill.err { color: var(--cl-err); border-color: rgba(181,71,71,.35); background: rgba(181,71,71,.07); }
.cl-pill.info { color: var(--cl-slate); border-color: rgba(69,106,138,.35); background: rgba(69,106,138,.07); }
.cl-pill.idle { color: var(--cl-muted); border-color: var(--cl-border); background: #fff; }
.cl-pill.run { color: var(--cl-teal); border-color: rgba(20,125,131,.4); background: rgba(20,125,131,.08); }
table.cl-kv { width: 100%; border-collapse: collapse; font-size: .86rem; }
table.cl-kv td, table.cl-kv th { padding: .34rem .5rem; border-bottom: 1px solid #E8ECED; vertical-align: top; text-align: left; }
table.cl-kv th { font-weight: 600; color: var(--cl-muted); font-size: .76rem; text-transform: uppercase; letter-spacing: .04em; background: var(--cl-panel); }
table.cl-kv td.k { color: var(--cl-muted); width: 34%; }
table.cl-kv code, .cl-code { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .78rem; color: #2E4A63;
                             background: #F0F3F4; border-radius: 4px; padding: .05rem .3rem; }
.cl-metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(116px, 1fr)); background: #fff; border: 1px solid var(--cl-border);
              border-radius: 8px; overflow: hidden; }
.cl-metric { padding: .65rem .85rem; border-right: 1px solid #EEF1F2; border-bottom: 1px solid #EEF1F2; }
.cl-metric .k { font-size: .76rem; color: var(--cl-muted); }
.cl-metric .v { font-size: 1.22rem; font-weight: 600; color: var(--cl-navy); font-variant-numeric: tabular-nums; line-height: 1.35; }
.cl-metric .u { font-size: .74rem; color: var(--cl-muted); }
.cl-empty { border: 1px dashed #C6CFD3; border-radius: 8px; padding: 1.5rem 1.25rem; text-align: center; color: var(--cl-muted); background: #FAFAF8; }
.cl-empty h4 { color: var(--cl-text); margin: 0 0 .3rem; font-size: 1rem; font-weight: 600; padding: 0; }
.cl-empty p { margin: 0; font-size: .9rem; }
.cl-note { border-left: 3px solid var(--cl-slate); background: #EFF3F6; padding: .5rem .75rem; border-radius: 0 6px 6px 0; font-size: .86rem;
           color: var(--cl-text); margin: .35rem 0; }
.cl-note.warn { border-color: var(--cl-amber); background: #FAF3E8; }
.cl-note.err { border-color: var(--cl-err); background: #FAEEEE; }
.cl-note.ok { border-color: var(--cl-ok); background: #EDF5F0; }
.cl-note b { font-weight: 600; }
.cl-runhead { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem .75rem; }
.cl-runhead .title { font-weight: 600; color: var(--cl-text); font-size: .98rem; }
.cl-muted { color: var(--cl-muted); font-size: .84rem; }
.cl-chips { display: flex; flex-wrap: wrap; gap: .35rem; margin: .2rem 0 .1rem; }
.cl-chip { font-size: .76rem; padding: .05rem .5rem; border-radius: 4px; background: var(--cl-panel); color: #3B4A55; border: 1px solid #E1E7E5; }
.cl-chip.on { background: rgba(20,125,131,.09); color: var(--cl-teal); border-color: rgba(20,125,131,.3); }
.cl-chip.off { background: #F7F7F5; color: #8C979F; text-decoration: line-through; }
.cl-summary { font-size: .92rem; color: var(--cl-text); line-height: 1.5; }
.cl-summary b { color: var(--cl-navy); font-weight: 600; }
.cl-brand { padding: .2rem 0 .6rem; }
.cl-brand .name { font-size: 1.05rem; font-weight: 650; color: #FFFFFF; letter-spacing: .01em; }
.cl-brand .tag { font-size: .74rem; color: #A9BCCB; }
.cl-engine { border: 1px solid #2C4A68; border-radius: 8px; padding: .6rem .7rem; background: #1B3956; font-size: .82rem; color: #DCE5EC; }
.cl-engine .t { font-size: .7rem; text-transform: uppercase; letter-spacing: .07em; color: #9FB4C4; margin-bottom: .25rem; }
.cl-engine .s { display: flex; align-items: center; gap: .45rem; font-weight: 600; color: #fff; }
.cl-engine .d { color: #A9BCCB; margin-top: .2rem; line-height: 1.35; }
.cl-engine .dot { width: .5rem; height: .5rem; border-radius: 50%; }
div[data-testid="stExpander"] details summary p { font-size: .9rem; }
</style>
"""

_PILL_KIND = {
    "success": "ok", "ok": "ok", "incomplete": "warn", "warn": "warn", "timed_out": "warn", "interrupted": "warn",
    "failed": "err", "fail": "err", "rejected": "err", "error": "err", "canceled": "idle", "queued": "idle",
    "running": "run", "info": "info", "unavailable": "idle", "unchecked": "idle", "stopped": "idle",
    "starting": "run", "ready": "ok", "busy": "run", "read_only": "warn",
}


def inject_css() -> None:
    st.html(CSS)


def pill(text: str, kind: str) -> str:
    return f'<span class="cl-pill {_PILL_KIND.get(kind, kind)}"><span class="dot"></span>{escape(text)}</span>'


def page_header(title: str, subtitle: str = "", eyebrow: str = "") -> None:
    eb = f'<div class="cl-eyebrow">{escape(eyebrow)}</div>' if eyebrow else ""
    sub = f"<p>{escape(subtitle)}</p>" if subtitle else ""
    st.html(f'<div class="cl-header">{eb}<h1>{escape(title)}</h1>{sub}</div>')


def section(title: str, sub: str = "", num: int | None = None) -> None:
    n = f'<span class="num">{num}</span>' if num is not None else ""
    s = f'<span class="sub">{escape(sub)}</span>' if sub else ""
    st.html(f'<div class="cl-section">{n}<h3>{escape(title)}</h3>{s}</div>')


def note(text: str, kind: str = "info", title: str = "") -> None:
    t = f"<b>{escape(title)}</b> " if title else ""
    st.html(f'<div class="cl-note {escape(kind)}">{t}{escape(text)}</div>')


def empty_state(title: str, body: str) -> None:
    st.html(f'<div class="cl-empty"><h4>{escape(title)}</h4><p>{escape(body)}</p></div>')


def kv_table(rows: list[tuple], header: tuple | None = None) -> None:
    """rows of (key, value[, detail]); values are escaped; a value wrapped in `code:` renders as code."""
    def cell(v) -> str:
        if isinstance(v, str) and v.startswith("code:"):
            return f"<code>{escape(v[5:])}</code>"
        if isinstance(v, str) and v.startswith("html:"):
            return v[5:]   # only used with HTML built by this module (e.g. pills)
        return escape("—" if v is None or v == "" else str(v))
    out = ['<table class="cl-kv">']
    if header:
        out.append("<tr>" + "".join(f"<th>{escape(h)}</th>" for h in header) + "</tr>")
    for r in rows:
        tds = [f'<td class="k">{escape(str(r[0]))}</td>'] + [f"<td>{cell(v)}</td>" for v in r[1:]]
        out.append("<tr>" + "".join(tds) + "</tr>")
    out.append("</table>")
    st.html("".join(out))


def metric_strip(items: list[tuple[str, str, str]]) -> None:
    """items of (label, value, unit/explanation)."""
    cells = "".join(f'<div class="cl-metric"><div class="k">{escape(k)}</div><div class="v">{escape(v)}</div>'
                    f'<div class="u">{escape(u)}</div></div>' for k, v, u in items)
    st.html(f'<div class="cl-metrics">{cells}</div>')


def chips(items: list[tuple[str, bool | None]]) -> str:
    out = []
    for text, on in items:
        cls = "on" if on else ("off" if on is False else "")
        out.append(f'<span class="cl-chip {cls}">{escape(text)}</span>')
    return '<div class="cl-chips">' + "".join(out) + "</div>"


def fmt_num(x, digits: int = 2, unit: str = "") -> str:
    if x is None:
        return "—"
    try:
        v = float(x)
    except (TypeError, ValueError):
        return str(x)
    if v != v or v in (float("inf"), float("-inf")):
        return "—"
    s = f"{v:,.{digits}f}" if abs(v) < 1000 else f"{v:,.0f}"
    return f"{s} {unit}".strip()


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    s = int(round(seconds))
    if s < 60:
        return f"{s} s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m} min {s:02d} s"
    h, m = divmod(m, 60)
    return f"{h} h {m:02d} min"
