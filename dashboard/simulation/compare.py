"""Comparing runs fairly: which settings define a simulation, which runs are comparable,
and summary statistics that never treat a failed run as a zero."""
from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass, field

from .catalog import ASSIGNMENT_METHODS
from .results import RunRecord

SEARCH_KEYS = {o.key for o in ASSIGNMENT_METHODS if o.search}

# Settings that change what is simulated. Animation settings do not change the simulated
# outcome (they only change computer time), so they are reported separately.
SIM_FIELDS = {
    "model": "Model",
    "num_robots": "Robots",
    "assignment": "Assignment",
    "solver": "Solver",
    "time_limit": "Optimizer / search time limit",
    "search": "Search budget",
    "movement": "Movement (RVO2 / Tangent Bug / Dispersion)",
    "seed": "Random seed",
    "max_steps": "Step limit",
    "max_noprog": "Steps-without-progress limit",
    "code": "Code version",
}
TIMING_FIELDS = {"animation": "3D animation recording", "warm_up": "Warm-up before measuring"}

FACTORS = {
    "assignment": "Assignment method",
    "solver": "Optimization solver",
    "movement": "Movement profile",
    "num_robots": "Number of robots",
    "seed": "Repeated trials (seed)",
}


def sim_settings(r: RunRecord) -> dict:
    s, res = r.settings, r.resolved
    uses_solver = bool(res.get("solver_key"))
    search = res.get("assignment_key") in SEARCH_KEYS
    return {
        "model": res.get("model_name", s.get("model_key")),
        "num_robots": res.get("num_robots"),
        "assignment": res.get("assignment_label"),
        "solver": res.get("solver_label") if uses_solver else "not used",
        "time_limit": s.get("optimizer_time_limit_s") if uses_solver or search else "not used",
        "search": f"{s.get('search_iterations', 25)} × {s.get('search_population', 16)}" if search else "not used",
        "movement": f"{res.get('movement_label')} ({_flags(res)})",
        "seed": s.get("seed"),
        "max_steps": s.get("max_steps"),
        "max_noprog": s.get("max_iters_no_progress"),
        "code": r.source_hash or "not recorded",
    }


def config_label(r: RunRecord) -> str:
    """The run's configuration label (RunRecord.label already includes non-default step limits)."""
    return r.label


def config_key(r: RunRecord) -> tuple:
    """Everything that defines what is simulated, except the seed (repeated trials share a key)."""
    s = sim_settings(r)
    return tuple((k, str(s[k])) for k in SIM_FIELDS if k != "seed")


def timing_settings(r: RunRecord) -> dict:
    s = r.settings
    anim = "off" if not s.get("save_animation") else ("smooth" if s.get("smooth_animation") else "on")
    return {"animation": anim, "warm_up": bool(s.get("warm_up"))}


def _flags(res: dict) -> str:
    return "/".join("on" if res.get(k) else "off" for k in ("rvo", "tangent_bug", "dispersion"))


def level_of(r: RunRecord, factor: str) -> str:
    s = sim_settings(r)
    if factor == "assignment":
        if s["solver"] != "not used":
            return f"{s['assignment']} + {s['solver']} ({s['time_limit']} s)"
        if s["search"] != "not used":
            return f"{s['assignment']} ({s['search']}, {s['time_limit']} s)"   # different budgets are different methods
        return str(s["assignment"])
    if factor == "solver":
        return str(s["solver"])
    if factor == "movement":
        return str(r.resolved.get("movement_label"))
    if factor == "num_robots":
        return str(s["num_robots"])
    if factor == "seed":
        return str(s["seed"])
    raise ValueError(factor)


def _excluded(factor: str) -> set[str]:
    return {
        "assignment": {"assignment", "solver", "time_limit", "search", "seed"},
        "solver": {"solver", "seed"},
        "movement": {"movement", "seed"},
        "num_robots": {"num_robots", "seed"},
        "seed": {"seed"},
    }[factor]


def group_key(r: RunRecord, factor: str) -> tuple:
    s = sim_settings(r)
    return tuple((k, str(s[k])) for k in SIM_FIELDS if k not in _excluded(factor))


@dataclass
class Group:
    factor: str
    key: tuple
    runs: list[RunRecord] = field(default_factory=list)

    @property
    def levels(self) -> list[str]:
        out: list[str] = []
        for r in self.runs:
            lv = level_of(r, self.factor)
            if lv not in out:
                out.append(lv)
        if self.factor in ("num_robots", "seed"):
            out.sort(key=lambda x: float(x) if x.replace(".", "", 1).isdigit() else math.inf)
        return out

    @property
    def description(self) -> str:
        d = dict(self.key)
        parts = [str(d.get("model", ""))]
        if "num_robots" in d:
            parts.append(f"{d['num_robots']} robots")
        if "assignment" in d:
            a = d["assignment"]
            if d.get("solver") not in (None, "not used"):
                a += f" + {d['solver']}"
                if d.get("time_limit") not in (None, "not used"):
                    a += f" ({d['time_limit']} s)"
            parts.append(a)
        if "movement" in d:
            parts.append(d["movement"].split(" (")[0] + " movement")
        if "seed" in d:
            parts.append(f"seed {d['seed']}")
        if d.get("code") not in (None, "not recorded"):
            parts.append(f"code {d['code']}")
        return " · ".join(parts)

    @property
    def seeds(self) -> list:
        return sorted({r.settings.get("seed") for r in self.runs}, key=lambda x: (x is None, x))


def find_groups(records: list[RunRecord], factor: str) -> list[Group]:
    """Sets of finished runs that differ only in `factor` (and, for repeated trials, the seed)."""
    groups: dict[tuple, Group] = {}
    for r in records:
        if not r.is_final or r.state in ("rejected", "canceled"):
            continue
        k = group_key(r, factor)
        groups.setdefault(k, Group(factor, k)).runs.append(r)
    out = [g for g in groups.values() if len(g.levels) >= 2]
    out.sort(key=lambda g: (-len(g.runs), g.description))
    return out


def differences(records: list[RunRecord]) -> tuple[list[str], list[str]]:
    """(simulation settings that differ, timing-related settings that differ) among `records`."""
    sim, timing = [], []
    for k, label in SIM_FIELDS.items():
        if len({str(sim_settings(r)[k]) for r in records}) > 1:
            sim.append(label)
    for k, label in TIMING_FIELDS.items():
        if len({str(timing_settings(r)[k]) for r in records}) > 1:
            timing.append(label)
    return sim, timing


def deduplicate(records: list[RunRecord]) -> list[RunRecord]:
    """The newest run per settings, seed and code. A repeat is the same experiment, not more evidence."""
    newest: dict[tuple, RunRecord] = {}
    for r in records:
        k = (config_key(r), str(r.settings.get("seed")))
        if k not in newest or (r.created_at, r.run_id) > (newest[k].created_at, newest[k].run_id):
            newest[k] = r
    return [r for r in records if newest[(config_key(r), str(r.settings.get("seed")))] is r]


# -----------------------------------------------------------------------------
# Statistics. The same methods as src/comparison_statistics.jl (no scipy needed).
# -----------------------------------------------------------------------------

def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _sd(xs):
    if len(xs) < 2:
        return None
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def bootstrap_ci(xs: list[float], level: float = 0.95, n_samples: int = 4000) -> tuple[float | None, float | None]:
    """Percentile bootstrap interval of the mean. None below 3 values, where it would mean little."""
    if len(xs) < 3:
        return None, None
    rng = random.Random(0)
    means = sorted(sum(rng.choices(xs, k=len(xs))) / len(xs) for _ in range(n_samples))
    alpha = (1 - level) / 2
    return means[int(alpha * n_samples)], means[min(n_samples - 1, int((1 - alpha) * n_samples))]


def sign_flip_p(diffs: list[float], max_exact: int = 16, n_samples: int = 100_000) -> float:
    """Two-sided paired sign-flip permutation test: exact up to `max_exact` pairs, otherwise sampled."""
    nonzero = [d for d in diffs if d != 0]
    if not nonzero:
        return 1.0
    observed = abs(sum(nonzero)) - 1e-12
    if len(nonzero) <= max_exact:
        hits = sum(abs(sum(s * d for s, d in zip(signs, nonzero))) >= observed
                   for signs in itertools.product((1, -1), repeat=len(nonzero)))
        return hits / 2 ** len(nonzero)
    rng = random.Random(0)
    hits = sum(abs(sum(d if rng.random() < 0.5 else -d for d in nonzero)) >= observed for _ in range(n_samples))
    return (hits + 1) / (n_samples + 1)


def holm_adjust(ps: list[float]) -> list[float]:
    """Holm's step-down correction for several tests against one baseline."""
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    out, running = [0.0] * len(ps), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(ps) - rank) * ps[i]))
        out[i] = running
    return out


def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(xs, ys) -> float:
    """Spearman rank correlation. NaN when either side is constant."""
    rx, ry = _ranks(list(xs)), _ranks(list(ys))
    mx, my = _mean(rx), _mean(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx, vy = sum((a - mx) ** 2 for a in rx), sum((b - my) ** 2 for b in ry)
    return cov / math.sqrt(vx * vy) if vx and vy else math.nan


@dataclass
class Summary:
    level: str
    n_runs: int
    n_success: int
    n_other: int
    other_states: str
    mean: float | None
    ci_low: float | None
    ci_high: float | None
    sd: float | None
    min: float | None
    max: float | None
    mean_planned: float | None
    mean_assignment_cpu: float | None
    mean_total_cpu: float | None
    any_compilation: bool
    runs_with_overlap: int | None
    min_robot_gap: float | None
    total_swaps: int | None

    @property
    def success_rate(self) -> float | None:
        return self.n_success / self.n_runs if self.n_runs else None


def summarize(records: list[RunRecord], factor: str | None, levels: list[str] | None = None) -> list[Summary]:
    """Per-level statistics over successful runs only; other outcomes are counted, never averaged in.
    Repeats of the same settings, seed and code count once."""
    by: dict[str, list[RunRecord]] = {}
    for r in deduplicate(records) if factor else records:
        lv = level_of(r, factor) if factor else r.run_id
        by.setdefault(lv, []).append(r)
    order = levels or list(by)
    out = []
    for lv in order:
        rs = by.get(lv, [])
        ok = [r for r in rs if r.state == "success" and r.metric("makespan_s") is not None]
        vals = [v for r in ok if (v := r.metric("makespan_s")) is not None]
        others = [r for r in rs if r not in ok]
        states: dict[str, int] = {}
        for r in others:
            states[r.state_label] = states.get(r.state_label, 0) + 1
        gaps = [r.metric("robot_min_gap_m") for r in ok if r.metric("robot_min_gap_m") is not None]
        safety = [r for r in ok if r.result.get("robot_overlap_steps") is not None]
        ci_low, ci_high = bootstrap_ci(vals)
        out.append(Summary(
            level=lv, n_runs=len(rs), n_success=len(ok), n_other=len(others),
            other_states=", ".join(f"{n} {s.lower()}" for s, n in states.items()),
            mean=_mean(vals), ci_low=ci_low, ci_high=ci_high, sd=_sd(vals),
            min=min(vals) if vals else None, max=max(vals) if vals else None,
            mean_planned=_mean([r.metric("optimistic_makespan_s") for r in ok if r.metric("optimistic_makespan_s") is not None]),
            mean_assignment_cpu=_mean([r.metric("assignment_time_s") for r in ok if r.metric("assignment_time_s") is not None]),
            mean_total_cpu=_mean([r.metric("total_wall_time_s") for r in ok if r.metric("total_wall_time_s") is not None]),
            any_compilation=any(r.result.get("includes_compilation") for r in ok),
            runs_with_overlap=sum(r.result["robot_overlap_steps"] > 0 for r in safety) if safety else None,
            min_robot_gap=min(gaps) if gaps else None,
            total_swaps=sum(r.result.get("position_swaps", 0) for r in safety) if safety else None))
    return out


@dataclass
class PairedResult:
    level: str
    n_pairs: int
    mean_gain: float | None
    ci_low: float | None
    ci_high: float | None
    effect_size: float | None
    wins: int
    losses: int
    p_value: float | None
    p_holm: float | None = None


def paired_comparison(records: list[RunRecord], factor: str, baseline: str) -> list[PairedResult]:
    """Every level against `baseline`, on the seeds where both succeeded. Gain = baseline minus level,
    so positive means faster than the baseline. p values are Holm-corrected over the levels."""
    times: dict[str, dict] = {}
    for r in deduplicate(records):
        if r.state == "success" and r.metric("makespan_s") is not None:
            times.setdefault(level_of(r, factor), {})[r.settings.get("seed")] = r.metric("makespan_s")
    base = times.get(baseline, {})
    out = []
    for lv, ts in times.items():
        if lv == baseline:
            continue
        diffs = [base[s] - ts[s] for s in ts if s in base]
        sd = _sd(diffs)
        ci_low, ci_high = bootstrap_ci(diffs)
        out.append(PairedResult(
            level=lv, n_pairs=len(diffs), mean_gain=_mean(diffs), ci_low=ci_low, ci_high=ci_high,
            effect_size=_mean(diffs) / sd if sd else None, wins=sum(d > 0 for d in diffs),
            losses=sum(d < 0 for d in diffs), p_value=sign_flip_p(diffs) if diffs else None))
    tested = [p for p in out if p.p_value is not None]
    for p, adjusted in zip(tested, holm_adjust([p.p_value for p in tested])):
        p.p_holm = adjusted
    return out
