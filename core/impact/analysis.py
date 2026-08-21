"""Deterministic impact analysis (P12).

Input: aggregated per-edge metrics for the baseline and scenario arms (real SUMO
edgeData + queue), the scenario's closed edges, and the network topology. Output:
per-edge deltas + class + attribution, ranked critical junctions, and a summary.

Every number is derived from measured values or is None; nothing is invented.
The rules are pure functions of the inputs and the config thresholds, so the same
inputs always produce the same classification.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from config import IMPACT
from core.impact.models import (
    ATTR_UNCHANGED,
    DIRECTLY_AFFECTED,
    LOW,
    SECONDARILY_AFFECTED,
    SEVERE,
    SEVERITY_ORDER,
    UNCHANGED,
    EdgeImpact,
    ImpactResult,
    JunctionImpact,
)
from core.sim.scenario import read_net_edges


# ---------------------------------------------------------------------------
# small numeric helpers
# ---------------------------------------------------------------------------
def _sub(a: float | None, b: float | None) -> float | None:
    """a − b, or None if either side is missing (no measurement to subtract)."""
    if a is None or b is None:
        return None
    return round(a - b, 3)


def _sub0(a: float | None, b: float | None) -> float:
    """a − b treating a missing side as 0. For counts/queue where absent = none."""
    return round((a or 0.0) - (b or 0.0), 3)


def _severity(worsening: float | None, bands: list[float]) -> str | None:
    """Map a positive worsening magnitude to LOW/MODERATE/HIGH/SEVERE via bands.

    bands = [a, b, c] → LOW: 0<w<a · MODERATE: a≤w<b · HIGH: b≤w<c · SEVERE: w≥c.
    Returns None when there is no worsening.
    """
    if worsening is None or worsening <= 0:
        return None
    idx = sum(1 for t in bands if worsening >= t)  # 0..len(bands)
    return SEVERITY_ORDER[min(idx, len(SEVERITY_ORDER) - 1)]


def _worse(class_a: str | None, class_b: str | None) -> str | None:
    """The more severe of two classes (None = no worsening)."""
    order = {c: i for i, c in enumerate(SEVERITY_ORDER)}
    best = None
    for c in (class_a, class_b):
        if c is not None and (best is None or order[c] > order[best]):
            best = c
    return best


# ---------------------------------------------------------------------------
# per-edge
# ---------------------------------------------------------------------------
def edge_impact(edge_id: str, b: dict | None, s: dict | None,
                *, closed: bool, cfg: dict = IMPACT) -> EdgeImpact:
    """Classify one edge from its baseline (b) and scenario (s) metric rows."""
    tt_delta = _sub((s or {}).get("travel_time_s"), (b or {}).get("travel_time_s"))
    base_tt = (b or {}).get("travel_time_s")
    tt_pct = (round(tt_delta / base_tt * 100, 2)
              if tt_delta is not None and base_tt not in (None, 0) else None)
    queue_delta = _sub0((s or {}).get("queue_length_m"), (b or {}).get("queue_length_m"))
    speed_delta = _sub((s or {}).get("speed_mps"), (b or {}).get("speed_mps"))
    wait_delta = _sub0((s or {}).get("waiting_time_s"), (b or {}).get("waiting_time_s"))
    entered_delta = _sub0((s or {}).get("entered"), (b or {}).get("entered"))

    material = (
        (tt_pct is not None and abs(tt_pct) >= cfg["material_travel_time_pct"])
        or (queue_delta >= cfg["material_queue_delta_m"])
    )

    if closed:
        attribution = DIRECTLY_AFFECTED
    elif material:
        attribution = SECONDARILY_AFFECTED
    else:
        attribution = ATTR_UNCHANGED

    if attribution == ATTR_UNCHANGED:
        impact_class = UNCHANGED
    elif closed and (s is None or (s.get("entered") or 0) <= 0.5):
        # Fully closed edge — no scenario flow at all. Worst class by definition.
        impact_class = SEVERE
    else:
        worse = _worse(
            _severity(tt_pct if (tt_pct or 0) > 0 else None, cfg["travel_time_pct_bands"]),
            _severity(queue_delta if queue_delta > 0 else None, cfg["queue_delta_m_bands"]),
        )
        # Affected but only improved (no worsening) still gets the mildest class.
        impact_class = worse or LOW

    return EdgeImpact(
        edge_id=edge_id, attribution=attribution, impact_class=impact_class,
        travel_time_delta_s=tt_delta, travel_time_delta_pct=tt_pct,
        queue_delta_m=queue_delta, speed_delta_mps=speed_delta,
        waiting_time_delta_s=wait_delta, entered_delta=entered_delta,
        baseline=b, scenario=s,
    )


def analyze_edges(baseline_edges: dict, scenario_edges: dict,
                  closed_edges: list[str], *, cfg: dict = IMPACT) -> list[EdgeImpact]:
    closed = set(closed_edges or [])
    out = [
        edge_impact(eid, baseline_edges.get(eid), scenario_edges.get(eid),
                    closed=eid in closed, cfg=cfg)
        for eid in sorted(set(baseline_edges) | set(scenario_edges))
    ]
    return out


# ---------------------------------------------------------------------------
# critical junctions
# ---------------------------------------------------------------------------
def rank_junctions(edge_impacts: list[EdgeImpact], net_file: str | Path,
                   *, cfg: dict = IMPACT) -> list[JunctionImpact]:
    """Rank junctions by the worsening on their incident edges (real deltas)."""
    net_edges = read_net_edges(net_file)
    by_id = {e.edge_id: e for e in edge_impacts}

    # junction_id -> incident edge ids (edges entering OR leaving it)
    incident: dict[str, set[str]] = {}
    for eid, d in net_edges.items():
        for node in (d.get("from"), d.get("to")):
            if node and not node.startswith(":"):
                incident.setdefault(node, set()).add(eid)

    ranked: list[JunctionImpact] = []
    for jid, eids in incident.items():
        q_sum = w_sum = 0.0
        n_aff = 0
        worst_edge, worst_val = None, 0.0
        for eid in eids:
            e = by_id.get(eid)
            if not e:
                continue
            q = max(0.0, e.queue_delta_m or 0.0)
            w = max(0.0, e.waiting_time_delta_s or 0.0)
            q_sum += q
            w_sum += w
            if e.attribution != ATTR_UNCHANGED:
                n_aff += 1
            if q + w > worst_val:
                worst_val, worst_edge = q + w, eid
        score = round(q_sum + w_sum, 3)
        if score >= cfg["junction_min_score"]:
            ranked.append(JunctionImpact(
                junction_id=jid, impact_score=score,
                total_queue_increase_m=round(q_sum, 2),
                total_waiting_increase_s=round(w_sum, 2),
                n_incident_affected=n_aff, worst_edge=worst_edge,
            ))
    ranked.sort(key=lambda j: (-j.impact_score, j.junction_id))
    return ranked[: cfg["junction_top_n"]]


# ---------------------------------------------------------------------------
# summary + top-level
# ---------------------------------------------------------------------------
def _network_pct(comparison: dict | None, label: str) -> float | None:
    for row in (comparison or {}).get("rows", []):
        if row.get("metric") == label:
            return row.get("delta_pct")
    return None


def summarize(edges: list[EdgeImpact], critical: list[JunctionImpact],
              comparison: dict | None) -> dict[str, Any]:
    affected = [e for e in edges if e.attribution != ATTR_UNCHANGED]
    return {
        # Network-level deltas from the aggregate comparison (tripinfo/queue) —
        # the same real numbers P11 already reports.
        "travel_time_delta_pct": _network_pct(comparison, "Average travel time"),
        "queue_delta_pct": _network_pct(comparison, "Queue length"),
        # Edge-level counts, self-consistent with the edges list below.
        "affected_roads": len(affected),
        "directly_affected": sum(1 for e in affected if e.attribution == DIRECTLY_AFFECTED),
        "secondarily_affected": sum(1 for e in affected if e.attribution == SECONDARILY_AFFECTED),
        "critical_junctions": len(critical),
        "edges_measured": len(edges),
    }


def analyze(*, baseline_edges: dict, scenario_edges: dict,
            net_file: str | Path, closed_edges: list[str],
            comparison: dict | None, scenario_id: str,
            seeds: list[int], cfg: dict = IMPACT) -> dict[str, Any]:
    """Full P12 impact result for one scenario, ready to persist inside the
    scenario result. Returns a JSON-native dict."""
    edges = analyze_edges(baseline_edges, scenario_edges, closed_edges, cfg=cfg)
    critical = rank_junctions(edges, net_file, cfg=cfg)
    summary = summarize(edges, critical, comparison)

    result = ImpactResult(
        scenario_id=scenario_id,
        edges=[e.to_dict() for e in edges],
        critical_junctions=[j.to_dict() for j in critical],
        summary=summary,
        provenance={
            "scenario_id": scenario_id,
            "seeds": list(seeds),
            "closed_edges": list(closed_edges or []),
            "metric_source": "SUMO edgeData + queue-output (measured, per-edge, mean over seeds)",
            "thresholds": cfg,
        },
    )
    return result.to_dict()
