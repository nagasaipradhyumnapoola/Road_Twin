"""Deterministic candidate generation (P13).

Candidates are derived from the ACTUAL network + scenario (and P12 impact when
available), never invented. Same inputs → same candidates → same ids. Only the
two V1 types are produced: a lane-configuration change on the bottleneck, and an
alternative-routing diversion around it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from config import INTERVENTION
from core.intervention.models import ALT_ROUTING, LANE_CONFIG, Candidate
from core.scenario.models import LANE_CLOSURE, ROAD_CLOSURE, Scenario
from core.sim.scenario import read_net_edges, upstream_edges


def _iid(n: int) -> str:
    return f"int-{n:03d}"


def _two_hop_upstream(net_file: str | Path, edge_id: str, hops: int) -> list[str]:
    """Edges up to `hops` upstream of edge_id (excluding it). Deterministic."""
    frontier = {edge_id}
    seen: set[str] = set()
    for _ in range(max(1, hops)):
        nxt: set[str] = set()
        for e in frontier:
            for u in upstream_edges(net_file, e):
                if u != edge_id and u not in seen:
                    nxt.add(u)
        seen |= nxt
        frontier = nxt
    return sorted(seen)


def generate(scenario: Scenario, net_file: str | Path,
             impact: dict | None = None, cfg: dict = INTERVENTION) -> list[Candidate]:
    """Generate candidate interventions for a scenario.

    V1 targets closure scenarios (lane/road closure); other types get no
    candidates (nothing to mitigate with these two levers). Returns [] rather
    than fabricating options.
    """
    if scenario.type not in (LANE_CLOSURE, ROAD_CLOSURE):
        return []

    edges = read_net_edges(net_file)
    closed = (scenario.parameters or {}).get("edge_id")
    if not closed or closed not in edges:
        return []

    out: list[Candidate] = []
    n = 1

    # --- 1. Lane configuration: add a lane to the closed corridor ------------
    cur = edges[closed]["num_lanes"]
    target_lanes = min(cur + cfg["lane_config_delta"], cfg["lane_config_max"])
    if target_lanes > cur:
        out.append(Candidate(
            intervention_id=_iid(n), scenario_id=scenario.scenario_id,
            type=LANE_CONFIG,
            name=f"Add a lane to {closed} ({cur}→{target_lanes})",
            parameters={"edge_id": closed, "from_lanes": cur, "to_lanes": target_lanes},
        ))
        n += 1

    # --- 2. Alternative routing: divert around the closed corridor -----------
    trigger = _two_hop_upstream(net_file, closed, cfg["diversion_upstream_hops"])
    if trigger:
        out.append(Candidate(
            intervention_id=_iid(n), scenario_id=scenario.scenario_id,
            type=ALT_ROUTING,
            name=f"Divert traffic around {closed} (earlier reroute)",
            parameters={"avoid_edge": closed, "trigger_edges": trigger},
        ))
        n += 1

    # --- 3. (optional) widen the worst SECONDARY edge, if P12 found one -------
    if impact and n <= cfg["max_candidates"]:
        secondary = _worst_secondary(impact, closed, edges)
        if secondary:
            cur2 = edges[secondary]["num_lanes"]
            tgt2 = min(cur2 + cfg["lane_config_delta"], cfg["lane_config_max"])
            if tgt2 > cur2:
                out.append(Candidate(
                    intervention_id=_iid(n), scenario_id=scenario.scenario_id,
                    type=LANE_CONFIG,
                    name=f"Widen congested {secondary} ({cur2}→{tgt2})",
                    parameters={"edge_id": secondary, "from_lanes": cur2, "to_lanes": tgt2},
                ))
                n += 1

    return out[: cfg["max_candidates"]]


def _worst_secondary(impact: dict, closed: str, edges: dict) -> str | None:
    """The secondarily-affected edge with the largest queue increase (real P12)."""
    best, best_q = None, 0.0
    for e in impact.get("edges", []):
        if (e.get("attribution") == "SECONDARILY_AFFECTED"
                and e.get("edge_id") != closed
                and e.get("edge_id") in edges
                and edges[e["edge_id"]]["num_lanes"] >= 1):
            q = e.get("queue_delta_m") or 0.0
            if q > best_q:
                best, best_q = e["edge_id"], q
    return best
