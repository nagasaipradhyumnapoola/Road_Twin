"""Reject an impossible scenario before any SUMO run.

Fail fast with a clear message at the request boundary, so a bad edge or lane
never reaches the (expensive) simulation and the UI gets an actionable error
rather than a mid-run stack trace.
"""
from __future__ import annotations

from pathlib import Path

from core.scenario.models import (
    BASELINE,
    LANE_CLOSURE,
    ROAD_CLOSURE,
    SCENARIO_TYPES,
    TRAFFIC_INCREASE,
    Scenario,
)
from core.sim.scenario import read_net_edges


def validate(scenario: Scenario, net_file: str | Path) -> None:
    """Raise ValueError if the scenario cannot be run on this network."""
    if scenario.type not in SCENARIO_TYPES:
        raise ValueError(
            f"Unknown scenario type '{scenario.type}'. "
            f"Expected one of: {', '.join(SCENARIO_TYPES)}"
        )
    if not scenario.seeds or not all(isinstance(s, int) for s in scenario.seeds):
        raise ValueError("A scenario needs a non-empty list of integer seeds.")

    p = scenario.parameters or {}

    if scenario.type == BASELINE:
        return  # no parameters to check

    if scenario.type in (LANE_CLOSURE, ROAD_CLOSURE):
        edge_id = p.get("edge_id")
        if not edge_id:
            raise ValueError("This scenario needs an 'edge_id'.")
        edges = read_net_edges(net_file)
        if edge_id not in edges:
            raise ValueError(
                f"Edge '{edge_id}' is not in the network. "
                f"Available (first 10): {list(edges)[:10]}"
            )
        if scenario.type == LANE_CLOSURE:
            n = edges[edge_id]["num_lanes"]
            if n < 2:
                raise ValueError(
                    f"Edge '{edge_id}' has {n} lane(s). A lane closure needs a "
                    "multi-lane edge; model a single-lane road as a Road Closure."
                )
            li = p.get("lane_index")
            if li is None:
                raise ValueError("Lane closure needs a 'lane_index'.")
            if not (0 <= int(li) < n):
                raise ValueError(
                    f"lane_index {li} out of range for '{edge_id}' (0..{n - 1})."
                )
        return

    if scenario.type == TRAFFIC_INCREASE:
        m = p.get("demand_multiplier")
        if m is None:
            raise ValueError("Traffic increase needs a 'demand_multiplier'.")
        if float(m) <= 1.0:
            raise ValueError(
                f"demand_multiplier must be > 1.0 (got {m}); a value <= 1 is not "
                "an increase."
            )
        return
