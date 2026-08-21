"""Metric extraction from SUMO output. Never hardcode a number.

Three outputs, three metrics:
  --tripinfo-output  -> average travel time, completed vehicles
  --queue-output     -> queue length
  --summary-output   -> sanity cross-check

queue-output is large (every lane, every timestep), so it is streamed with
iterparse rather than loaded whole.
"""
from __future__ import annotations

import math
import statistics
from pathlib import Path
from typing import Any

from lxml import etree


def parse_tripinfo(path: str | Path) -> dict[str, Any]:
    """Average travel time, time loss and completed-vehicle count."""
    durations: list[float] = []
    losses: list[float] = []
    waits: list[float] = []

    for _, el in etree.iterparse(str(path), tag="tripinfo"):
        try:
            durations.append(float(el.get("duration")))
            losses.append(float(el.get("timeLoss", 0.0)))
            waits.append(float(el.get("waitingTime", 0.0)))
        except (TypeError, ValueError):
            pass
        el.clear()

    if not durations:
        return {"completed_vehicles": 0, "avg_travel_time_s": None,
                "avg_time_loss_s": None, "avg_waiting_time_s": None}

    return {
        "completed_vehicles": len(durations),
        "avg_travel_time_s": round(statistics.fmean(durations), 2),
        "avg_time_loss_s": round(statistics.fmean(losses), 2),
        "avg_waiting_time_s": round(statistics.fmean(waits), 2),
    }


def parse_queue(path: str | Path, edge_filter: str | None = None) -> dict[str, Any]:
    """Queue length from --queue-output.

    Reports the mean over timesteps of the maximum lane queue, which is the
    number a traffic engineer means by "queue length", plus the absolute peak.
    Pass edge_filter to restrict to lanes of one edge (e.g. the closed edge).
    """
    per_step_max: list[float] = []
    cur = 0.0
    seen = False

    for event, el in etree.iterparse(str(path), events=("start", "end")):
        if event == "end" and el.tag == "lane":
            lid = el.get("id") or ""
            if edge_filter is None or lid.rsplit("_", 1)[0] == edge_filter:
                try:
                    cur = max(cur, float(el.get("queueing_length", 0.0)))
                    seen = True
                except (TypeError, ValueError):
                    pass
        elif event == "end" and el.tag == "data":
            if seen:
                per_step_max.append(cur)
            cur, seen = 0.0, False
            el.clear()

    if not per_step_max:
        return {"mean_queue_length_m": None, "max_queue_length_m": None}
    return {
        "mean_queue_length_m": round(statistics.fmean(per_step_max), 2),
        "max_queue_length_m": round(max(per_step_max), 2),
    }


def parse_summary(path: str | Path) -> dict[str, Any]:
    """Final-step totals, used as a cross-check on tripinfo."""
    last = None
    for _, el in etree.iterparse(str(path), tag="step"):
        last = dict(el.attrib)
        el.clear()
    if not last:
        return {}
    def _f(k):
        try:
            return float(last.get(k))
        except (TypeError, ValueError):
            return None
    return {
        "loaded": _f("loaded"),
        "inserted": _f("inserted"),
        "ended": _f("ended"),
        "still_running_at_end": _f("running"),
        "teleports": _f("teleports"),
        "collisions": _f("collisions"),
        # Network-wide mean speed at the final step. This is the variable that
        # separates "the network absorbed the closure" from "the network broke
        # down" -- see classify_breakdown().
        "mean_speed_end": _f("meanSpeed"),
    }


def collect_run(out_dir: str | Path, edge_filter: str | None = None) -> dict[str, Any]:
    """All metrics for one simulation run."""
    out_dir = Path(out_dir)
    m: dict[str, Any] = {}
    m.update(parse_tripinfo(out_dir / "tripinfo.xml"))
    m.update(parse_queue(out_dir / "queue.xml", edge_filter=edge_filter))
    m["_summary"] = parse_summary(out_dir / "summary.xml")

    # Promote the breakdown indicators so aggregate()/compare() can reach them
    # without re-parsing. These are raw SUMO values, copied not computed.
    s = m["_summary"] or {}
    m["teleports"] = s.get("teleports")
    m["still_running_at_end"] = s.get("still_running_at_end")
    m["mean_speed_end"] = s.get("mean_speed_end")

    # A high teleport count means gridlock/blocked vehicles, i.e. your metrics
    # are describing a broken simulation rather than congestion. Surface it.
    tp = (m["_summary"] or {}).get("teleports") or 0
    if tp > 0.05 * max(m.get("completed_vehicles") or 1, 1):
        m["_warning"] = (
            f"{tp:.0f} teleports -- vehicles are getting stuck. Metrics are "
            "unreliable. Reduce demand or check junction connectivity."
        )
    return m


def aggregate(runs: list[dict[str, Any]],
              seeds: list[int] | None = None) -> dict[str, Any]:
    """Mean and spread across seeds, plus the per-seed values themselves.

    Reporting a single seed makes your result an anecdote. Five seeds and a
    standard deviation makes it a measurement, and costs ~20 seconds.

    `seeds` keys the per-seed record. Baseline and closure use the SAME seed
    list and the SAME routes file, so each closure run is naturally paired with
    its baseline run -- compare() depends on that pairing, which is why the
    per-seed values have to survive aggregation rather than being collapsed.
    """
    keys = [
        "avg_travel_time_s", "avg_time_loss_s", "avg_waiting_time_s",
        "mean_queue_length_m", "max_queue_length_m", "completed_vehicles",
    ]
    agg: dict[str, Any] = {"n_seeds": len(runs)}
    for k in keys:
        vals = [r[k] for r in runs if r.get(k) is not None]
        if not vals:
            agg[k] = None
            continue
        agg[k] = round(statistics.fmean(vals), 2)
        agg[f"{k}_sd"] = round(statistics.pstdev(vals), 2) if len(vals) > 1 else 0.0

    if seeds is not None and len(seeds) == len(runs):
        agg["per_seed"] = {
            int(s): {
                "avg_travel_time_s": r.get("avg_travel_time_s"),
                "mean_queue_length_m": r.get("mean_queue_length_m"),
                "completed_vehicles": r.get("completed_vehicles"),
                "teleports": r.get("teleports"),
                "still_running_at_end": r.get("still_running_at_end"),
                "mean_speed_end": r.get("mean_speed_end"),
            }
            for s, r in zip(seeds, runs)
        }
    return agg


# Two-sided 95% critical values of Student's t, indexed by degrees of freedom.
# Hardcoded because scipy is deliberately not a dependency (ADR-011 keeps the
# frozen sidecar small). Beyond the table we fall back to the normal
# approximation, which is what t converges to.
_T_CRIT_95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
    8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145,
    15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056,
    27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042, 40: 2.021, 60: 2.000,
    120: 1.980,
}


def _t_crit_95(df: int) -> float:
    if df in _T_CRIT_95:
        return _T_CRIT_95[df]
    for k in sorted(_T_CRIT_95):
        if df < k:
            return _T_CRIT_95[k]
    return 1.960


def paired_effect(baseline: dict[str, Any], scenario: dict[str, Any],
                  key: str = "avg_travel_time_s") -> dict[str, Any] | None:
    """Paired analysis of the closure effect, matched seed by seed.

    WHY PAIRED. The experiment holds the network, the route file and the seed
    list fixed across both arms; the only difference is the closure. Seed 46's
    closure run is therefore the same traffic as seed 46's baseline run, and
    the two are not independent samples. Comparing arm-level spreads discards
    that structure and asks a question the experiment was not built to answer
    -- "are these two populations far apart?" rather than "does the closure
    change each run?".

    It also fails in a specific, diagnosable way on this benchmark. The closure
    is what CREATES the between-seed spread: roughly a quarter of seeds tip
    into network-wide breakdown while the rest absorb the closure, so closure
    sd runs several times baseline sd. A rule keyed to max(baseline_sd,
    closure_sd) therefore gets HARDER to satisfy the more strongly the closure
    bites -- removing a measurement bias and recovering the censored vehicles
    pushed it further from passing, not closer. Pairing cancels the
    between-seed variation both arms share and tests the differences directly.

    METHOD. One-sample two-sided t-test on the per-seed differences at the
    conventional 95% level: significant when the confidence interval for the
    mean difference excludes zero. This is not a weaker bar than the previous
    2-sigma rule; it is the matched-design question, and it would report a
    significant NEGATIVE effect (a closure that speeds the network up, which
    signals a broken experiment) just as readily.

    Returns None when pairing is impossible -- no per-seed data, or fewer than
    two shared seeds -- so compare() can fall back to the unpaired rule.
    """
    b_ps, s_ps = baseline.get("per_seed"), scenario.get("per_seed")
    if not b_ps or not s_ps:
        return None
    shared = sorted(set(b_ps) & set(s_ps))
    pairs = [(s, b_ps[s].get(key), s_ps[s].get(key)) for s in shared]
    pairs = [(s, b, c) for s, b, c in pairs if b is not None and c is not None]
    if len(pairs) < 2:
        return None

    deltas = [c - b for _, b, c in pairs]
    n = len(deltas)
    mean = statistics.fmean(deltas)
    sd = statistics.stdev(deltas)
    se = sd / math.sqrt(n)
    tcrit = _t_crit_95(n - 1)
    lo, hi = mean - tcrit * se, mean + tcrit * se
    t_stat = (mean / se) if se > 0 else 0.0

    return {
        "method": "paired two-sided t-test on per-seed differences, 95%",
        "metric": key,
        "n_pairs": n,
        "seeds": [s for s, _, _ in pairs],
        "per_seed_delta": {s: round(c - b, 2) for s, b, c in pairs},
        "mean_delta": round(mean, 2),
        "median_delta": round(statistics.median(deltas), 2),
        "sd_delta": round(sd, 2),
        "se_delta": round(se, 2),
        "t_stat": round(t_stat, 3),
        "t_crit_95": tcrit,
        "ci95": [round(lo, 2), round(hi, 2)],
        "n_positive": sum(1 for d in deltas if d > 0),
        "n_negative": sum(1 for d in deltas if d < 0),
        # CI excluding zero is equivalent to |t| > t_crit; stated as a CI
        # because that is what gets reported to a reader.
        "significant": (lo > 0) or (hi < 0),
        "direction": "increase" if mean > 0 else ("decrease" if mean < 0 else "none"),
    }


def classify_breakdown(baseline: dict[str, Any], scenario: dict[str, Any],
                       speed_ratio: float = 0.5) -> dict[str, Any] | None:
    """Count seeds in which the closure caused network-wide traffic breakdown.

    Reported SEPARATELY from the significance test, because it is a different
    claim. The t-test says "the closure changes travel time". This says "and in
    some runs it does not merely slow the network, it collapses it" -- which is
    the part a traffic engineer actually needs, and which a single mean hides.

    A seed counts as breakdown when its closure run's network mean speed falls
    below `speed_ratio` of its OWN baseline run's. The criterion is relative,
    so it transfers across networks and demand levels instead of encoding an
    absolute m/s threshold fitted to one benchmark. On this benchmark the two
    regimes separate cleanly -- breakdown seeds sit at 0.33-0.40 of baseline
    speed, normal seeds at 0.81-0.97, with nothing between -- so a 0.5 cut does
    not slice through a cluster.

    Severity is CONDITIONAL: it describes the breakdown runs only, and reports
    vehicles still driving when the simulation stopped, because those are trips
    the travel-time mean never counted.
    """
    b_ps, s_ps = baseline.get("per_seed"), scenario.get("per_seed")
    if not b_ps or not s_ps:
        return None
    shared = sorted(set(b_ps) & set(s_ps))
    if not shared:
        return None

    broke, ratios = [], {}
    for s in shared:
        bs, cs = b_ps[s].get("mean_speed_end"), s_ps[s].get("mean_speed_end")
        if bs is None or cs is None or bs <= 0:
            continue
        ratios[s] = round(cs / bs, 3)
        if cs < speed_ratio * bs:
            broke.append(s)
    if not ratios:
        return None

    def _mean_of(seeds, ps, key):
        v = [ps[s].get(key) for s in seeds if ps[s].get(key) is not None]
        return round(statistics.fmean(v), 2) if v else None

    out: dict[str, Any] = {
        "criterion": f"closure network mean speed < {speed_ratio:g} x its own baseline",
        "n_evaluated": len(ratios),
        "n_breakdown": len(broke),
        "breakdown_seeds": broke,
        "breakdown_probability": round(len(broke) / len(ratios), 3),
        "speed_ratio_per_seed": ratios,
    }
    if broke:
        b_tt = _mean_of(broke, b_ps, "avg_travel_time_s")
        c_tt = _mean_of(broke, s_ps, "avg_travel_time_s")
        out["conditional_severity"] = {
            "baseline_travel_time_s": b_tt,
            "closure_travel_time_s": c_tt,
            "delta_pct": round(100 * (c_tt - b_tt) / b_tt, 1) if b_tt else None,
            "closure_teleports": _mean_of(broke, s_ps, "teleports"),
            "closure_still_running_at_end": _mean_of(broke, s_ps, "still_running_at_end"),
            "baseline_still_running_at_end": _mean_of(broke, b_ps, "still_running_at_end"),
        }
    normal = [s for s in ratios if s not in broke]
    if normal:
        b_tt = _mean_of(normal, b_ps, "avg_travel_time_s")
        c_tt = _mean_of(normal, s_ps, "avg_travel_time_s")
        out["normal_regime"] = {
            "n": len(normal),
            "baseline_travel_time_s": b_tt,
            "closure_travel_time_s": c_tt,
            "delta_pct": round(100 * (c_tt - b_tt) / b_tt, 1) if b_tt else None,
        }
    return out



def compare(baseline: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    """Baseline vs scenario with deltas, and a verdict on whether it's signal."""
    rows = []
    for key, label, unit in [
        ("avg_travel_time_s", "Average travel time", "s"),
        ("mean_queue_length_m", "Queue length", "m"),
        ("completed_vehicles", "Completed vehicles", ""),
    ]:
        b, s = baseline.get(key), scenario.get(key)
        if b in (None, 0) or s is None:
            rows.append({"metric": label, "baseline": b, "scenario": s,
                         "delta": None, "delta_pct": None, "unit": unit})
            continue
        rows.append({
            "metric": label, "unit": unit,
            "baseline": b, "scenario": s,
            "delta": round(s - b, 2),
            "delta_pct": round((s - b) / b * 100, 1),
        })

    # Is the change bigger than seed noise? If not, say so rather than
    # presenting noise as a finding.
    b_tt = baseline.get("avg_travel_time_s")
    s_tt = scenario.get("avg_travel_time_s")

    # PRIMARY TEST: paired, because the experiment is paired by construction --
    # same network, same routes, same seeds, closure the only difference. See
    # paired_effect() for why the unpaired rule below is the wrong question for
    # this design and why it tightens as the closure gets stronger.
    # Seed count actually observed. None for hand-built aggregates that carry
    # no n_seeds -- those keep the legacy unpaired path.
    n_obs = baseline.get("n_seeds")
    if n_obs is not None and scenario.get("n_seeds") is not None:
        n_obs = min(n_obs, scenario["n_seeds"])

    paired = paired_effect(baseline, scenario)
    breakdown = classify_breakdown(baseline, scenario)

    if b_tt is None or s_tt is None:
        # A run in which no vehicle completed has no travel time at all.
        # Without this, the `tt_sd == 0` fallback would call that significant
        # and exit 0 -- reporting an empty simulation as a successful result.
        significant = False
        method = "empty-result guard"
    elif n_obs is not None and n_obs < 2:
        # Fewer than two seeds cannot support a significance claim at all:
        # there is no spread to compare a difference against. The unpaired
        # fallback below would happily call it significant, because a single
        # run has sd == 0 and the zero-variance shortcut fires. That made
        # `--seeds 1` exit 0 on any result, including a closure that made the
        # network FASTER. A one-seed run is a smoke test, not an experiment.
        significant = False
        method = f"insufficient seeds ({n_obs}) -- significance needs >= 2"
    elif paired is not None:
        significant = paired["significant"]
        method = paired["method"]
    else:
        # FALLBACK for aggregates with no per-seed data (hand-built dicts,
        # legacy callers). Single-seed runs never reach here -- they are
        # stopped by the seed-count guard above.
        tt_sd = max(baseline.get("avg_travel_time_s_sd") or 0,
                    scenario.get("avg_travel_time_s_sd") or 0)
        tt_delta = abs(s_tt - b_tt)
        significant = tt_sd == 0 or tt_delta > 2 * tt_sd
        method = "unpaired 2-sigma fallback (no per-seed data)"

    if n_obs is not None and n_obs < 2:
        verdict = (
            f"Only {n_obs} seed(s). This is a SMOKE TEST, not an experiment -- "
            "a single run has no spread, so no significance claim is possible. "
            "Run the full seed set for a result."
        )
    elif paired is not None:
        if paired["significant"] and paired["direction"] == "increase":
            verdict = (
                f"Closure increased travel time by {paired['mean_delta']}s "
                f"(95% CI {paired['ci95'][0]} to {paired['ci95'][1]}s, "
                f"{paired['n_positive']}/{paired['n_pairs']} seeds positive)."
            )
        elif paired["significant"]:
            verdict = (
                f"Closure DECREASED travel time by {abs(paired['mean_delta'])}s. "
                "A closure that speeds the network up usually means the network "
                "is gridlocked and the closure is metering inflow, or the closed "
                "edge is a fringe entry edge. Do not present this as a result."
            )
        else:
            verdict = (
                f"Paired effect {paired['mean_delta']}s, 95% CI "
                f"{paired['ci95'][0]} to {paired['ci95'][1]}s -- includes zero. "
                "Not separable from seed noise. Add seeds, increase demand "
                "(lower `period`), or pick a more critical edge."
            )
    else:
        verdict = (
            "Closure produced a change larger than seed-to-seed variation."
            if significant else
            "Change is within seed noise. Increase demand (lower `period`) "
            "or pick a more critical edge -- do not present this as a result."
        )

    return {
        "rows": rows,
        "n_seeds": baseline.get("n_seeds"),
        "significant": bool(significant),
        "method": method,
        "paired": paired,
        "breakdown": breakdown,
        "verdict": verdict,
    }


# ===========================================================================
# P12 — per-edge (edgeData) metrics. These live ALONGSIDE the aggregate
# metrics above; nothing here replaces parse_tripinfo/parse_queue/compare.
# Every value returned is a raw SUMO number or None — never synthesized.
# ===========================================================================
def _fattr(el: Any, key: str) -> float | None:
    try:
        return float(el.get(key))
    except (TypeError, ValueError):
        return None


def parse_edgedata(path: str | Path, *, interval_index: int = -1) -> dict[str, Any]:
    """Per-edge metrics from a SUMO ``edgeData`` output file.

    SUMO writes one ``<interval>`` per aggregation window; we configure a single
    window over the whole run, so the default ``interval_index=-1`` returns that
    one interval. Internal edges (id starts with ':') are skipped. A metric SUMO
    did not report for an edge is represented as None, never guessed.

    Returns ``{edge_id: {travel_time_s, waiting_time_s, time_loss_s, speed_mps,
    density, entered, left, sampled_seconds}}``.
    """
    intervals: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for event, el in etree.iterparse(str(path), events=("start", "end")):
        if event == "start" and el.tag == "interval":
            cur = {}
        elif event == "end" and el.tag == "edge":
            eid = el.get("id")
            if eid and not eid.startswith(":") and cur is not None:
                cur[eid] = {
                    "edge_id": eid,
                    "travel_time_s": _fattr(el, "traveltime"),
                    "waiting_time_s": _fattr(el, "waitingTime"),
                    "time_loss_s": _fattr(el, "timeLoss"),
                    "speed_mps": _fattr(el, "speed"),
                    "density": _fattr(el, "density"),
                    "entered": _fattr(el, "entered"),
                    "left": _fattr(el, "left"),
                    "sampled_seconds": _fattr(el, "sampledSeconds"),
                }
            el.clear()
        elif event == "end" and el.tag == "interval":
            intervals.append(cur or {})
            cur = None
            el.clear()
    if not intervals:
        return {}
    return intervals[interval_index]


def parse_queue_by_edge(path: str | Path) -> dict[str, float]:
    """Per-edge queue length (m) from ``--queue-output``.

    For each timestep an edge's queue is the maximum of its lanes' queues (the
    same definition parse_queue() uses network-wide); the reported number is the
    mean of that over timesteps. ``{edge_id: mean_queue_m}``.
    """
    from collections import defaultdict

    per_edge_steps: dict[str, list[float]] = defaultdict(list)
    cur: dict[str, float] = defaultdict(float)
    seen: set[str] = set()
    for event, el in etree.iterparse(str(path), events=("start", "end")):
        if event == "end" and el.tag == "lane":
            lid = el.get("id") or ""
            eid = lid.rsplit("_", 1)[0]
            if eid and not eid.startswith(":"):
                try:
                    cur[eid] = max(cur[eid], float(el.get("queueing_length", 0.0)))
                    seen.add(eid)
                except (TypeError, ValueError):
                    pass
        elif event == "end" and el.tag == "data":
            for eid in seen:
                per_edge_steps[eid].append(cur[eid])
            cur, seen = defaultdict(float), set()
            el.clear()
    return {eid: round(statistics.fmean(v), 2) for eid, v in per_edge_steps.items() if v}


def collect_edges(out_dir: str | Path) -> dict[str, Any]:
    """Merge one run's per-edge edgeData with its per-edge queue. {edge_id: {...}}."""
    out_dir = Path(out_dir)
    ed = parse_edgedata(out_dir / "edgedata.xml") if (out_dir / "edgedata.xml").exists() else {}
    q = parse_queue_by_edge(out_dir / "queue.xml") if (out_dir / "queue.xml").exists() else {}
    edges: dict[str, Any] = {}
    for eid in set(ed) | set(q):
        row = dict(ed.get(eid) or {"edge_id": eid})
        row["edge_id"] = eid
        row["queue_length_m"] = q.get(eid)
        edges[eid] = row
    return edges


_EDGE_METRIC_KEYS = (
    "travel_time_s", "waiting_time_s", "time_loss_s", "speed_mps",
    "density", "entered", "left", "queue_length_m",
)


def aggregate_edges(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Mean each per-edge metric across seed runs. An edge present in any run is
    kept; a metric absent in every run for that edge stays None."""
    from collections import defaultdict

    acc: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for run in runs:
        for eid, row in run.items():
            for k in _EDGE_METRIC_KEYS:
                v = row.get(k)
                if v is not None:
                    acc[eid][k].append(v)
    out: dict[str, Any] = {}
    for eid, mp in acc.items():
        d: dict[str, Any] = {"edge_id": eid}
        for k in _EDGE_METRIC_KEYS:
            vals = mp.get(k) or []
            d[k] = round(statistics.fmean(vals), 3) if vals else None
        d["_n_seeds"] = max((len(mp.get(k) or []) for k in _EDGE_METRIC_KEYS), default=0)
        out[eid] = d
    return out


def format_table(cmp: dict[str, Any]) -> str:
    """Plain-text comparison table for the notebook and the terminal."""
    w = 22
    lines = [
        f"{'':<{w}}{'BASELINE':>12}{'CLOSURE':>12}{'DELTA':>12}",
        "-" * (w + 36),
    ]
    for r in cmp["rows"]:
        b = "-" if r["baseline"] is None else f"{r['baseline']:.1f}{r['unit']}"
        s = "-" if r["scenario"] is None else f"{r['scenario']:.1f}{r['unit']}"
        d = "-" if r["delta_pct"] is None else f"{r['delta_pct']:+.1f}%"
        lines.append(f"{r['metric']:<{w}}{b:>12}{s:>12}{d:>12}")
    lines.append("-" * (w + 36))
    lines.append(f"mean of {cmp.get('n_seeds')} seeds")

    pa = cmp.get("paired")
    if pa:
        lines += [
            "",
            "PAIRED EFFECT  (matched by seed; same network, routes and demand)",
            f"  method            {pa['method']}",
            f"  mean delta        {pa['mean_delta']:+.2f}s   median {pa['median_delta']:+.2f}s",
            f"  95% CI            [{pa['ci95'][0]:+.2f}, {pa['ci95'][1]:+.2f}]s",
            f"  t / t_crit        {pa['t_stat']:.2f} / {pa['t_crit_95']:.3f}  (n={pa['n_pairs']})",
            f"  seeds up / down   {pa['n_positive']} / {pa['n_negative']}",
            f"  significant       {pa['significant']}",
        ]

    bd = cmp.get("breakdown")
    if bd:
        lines += [
            "",
            "BREAKDOWN REGIME  (reported separately from the significance test)",
            f"  criterion         {bd['criterion']}",
            (f"  breakdown runs    {bd['n_breakdown']}/{bd['n_evaluated']}"
             f"  = {100 * bd['breakdown_probability']:.0f}% of seeds"),
        ]
        if bd.get("breakdown_seeds"):
            lines.append(f"  seeds             {bd['breakdown_seeds']}")
        cs = bd.get("conditional_severity")
        if cs:
            lines.append(
                f"  when it breaks    {cs['baseline_travel_time_s']:.1f}s -> "
                f"{cs['closure_travel_time_s']:.1f}s ({cs['delta_pct']:+.1f}%), "
                f"{cs['closure_teleports']:.0f} teleports, "
                f"{cs['closure_still_running_at_end']:.0f} vehicles unfinished"
            )
        nr = bd.get("normal_regime")
        if nr:
            lines.append(
                f"  when it does not  {nr['baseline_travel_time_s']:.1f}s -> "
                f"{nr['closure_travel_time_s']:.1f}s ({nr['delta_pct']:+.1f}%), "
                f"n={nr['n']}"
            )

    verdict = cmp.get("verdict")
    if verdict:
        lines += ["", verdict]
    return "\n".join(lines)
