"""Reject an impossible candidate before any SUMO run (P13).

Fail fast with a clear reason at the request boundary, so a bad edge or lane
count never reaches the (expensive) simulation and the candidate is stored as
INVALID with an explanation rather than silently dropped.
"""
from __future__ import annotations

from pathlib import Path

from config import INTERVENTION
from core.intervention.models import (
    ALT_ROUTING,
    INTERVENTION_TYPES,
    LANE_CONFIG,
    Candidate,
)
from core.sim.scenario import downstream_edges, read_net_edges


def validate(candidate: Candidate, net_file: str | Path, cfg: dict = INTERVENTION) -> None:
    """Raise ValueError(reason) if the candidate cannot be run on this network."""
    if candidate.type not in INTERVENTION_TYPES:
        raise ValueError(
            f"Unsupported intervention type '{candidate.type}'. "
            f"Expected one of: {', '.join(INTERVENTION_TYPES)}"
        )
    if not candidate.scenario_id:
        raise ValueError("Candidate has no scenario_id.")

    edges = read_net_edges(net_file)
    p = candidate.parameters or {}

    if candidate.type == LANE_CONFIG:
        edge_id = p.get("edge_id")
        if not edge_id:
            raise ValueError("Lane configuration needs an 'edge_id'.")
        if edge_id not in edges:
            raise ValueError(f"Edge '{edge_id}' is not in the network.")
        to_lanes = p.get("to_lanes")
        if to_lanes is None or int(to_lanes) < 1:
            raise ValueError("Lane configuration needs a 'to_lanes' >= 1.")
        if int(to_lanes) > cfg["lane_config_max"]:
            raise ValueError(
                f"to_lanes {to_lanes} exceeds the cap of {cfg['lane_config_max']} "
                "for a single edge."
            )
        if int(to_lanes) == edges[edge_id]["num_lanes"]:
            raise ValueError(
                f"to_lanes {to_lanes} equals the current lane count — no change."
            )
        return

    if candidate.type == ALT_ROUTING:
        avoid = p.get("avoid_edge")
        if not avoid:
            raise ValueError("Alternative routing needs an 'avoid_edge'.")
        if avoid not in edges:
            raise ValueError(f"avoid_edge '{avoid}' is not in the network.")
        trig = p.get("trigger_edges") or []
        if not trig:
            raise ValueError("Alternative routing needs at least one trigger edge.")
        missing = [e for e in trig if e not in edges]
        if missing:
            raise ValueError(f"trigger_edges not in the network: {missing[:5]}")
        if not downstream_edges(net_file, avoid):
            raise ValueError(
                f"avoid_edge '{avoid}' has no downstream — diverting off it is "
                "impossible (it is a network exit)."
            )
        return
