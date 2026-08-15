"""Metric extraction from SUMO output. Never hardcode a number.

Three outputs, three metrics:
  --tripinfo-output  -> average travel time, completed vehicles
  --queue-output     -> queue length
  --summary-output   -> sanity cross-check

queue-output is large (every lane, every timestep), so it is streamed with
iterparse rather than loaded whole.
"""
from __future__ import annotations

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
    }


def collect_run(out_dir: str | Path, edge_filter: str | None = None) -> dict[str, Any]:
    """All metrics for one simulation run."""
    out_dir = Path(out_dir)
    m: dict[str, Any] = {}
    m.update(parse_tripinfo(out_dir / "tripinfo.xml"))
    m.update(parse_queue(out_dir / "queue.xml", edge_filter=edge_filter))
    m["_summary"] = parse_summary(out_dir / "summary.xml")

    # A high teleport count means gridlock/blocked vehicles, i.e. your metrics
    # are describing a broken simulation rather than congestion. Surface it.
    tp = (m["_summary"] or {}).get("teleports") or 0
    if tp > 0.05 * max(m.get("completed_vehicles") or 1, 1):
        m["_warning"] = (
            f"{tp:.0f} teleports -- vehicles are getting stuck. Metrics are "
            "unreliable. Reduce demand or check junction connectivity."
        )
    return m


def aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Mean and spread across seeds.

    Reporting a single seed makes your result an anecdote. Five seeds and a
    standard deviation makes it a measurement, and costs ~20 seconds.
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
    return agg


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
    tt_sd = max(baseline.get("avg_travel_time_s_sd") or 0,
                scenario.get("avg_travel_time_s_sd") or 0)
    tt_delta = abs((scenario.get("avg_travel_time_s") or 0)
                   - (baseline.get("avg_travel_time_s") or 0))
    significant = tt_sd == 0 or tt_delta > 2 * tt_sd

    return {
        "rows": rows,
        "n_seeds": baseline.get("n_seeds"),
        "significant": bool(significant),
        "verdict": (
            "Closure produced a change larger than seed-to-seed variation."
            if significant else
            "Change is within seed noise. Increase demand (lower `period`) "
            "or pick a more critical edge -- do not present this as a result."
        ),
    }


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
    lines.append(f"mean of {cmp.get('n_seeds')} seeds | {cmp['verdict']}")
    return "\n".join(lines)
