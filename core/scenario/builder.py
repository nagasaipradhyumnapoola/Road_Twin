"""Turn a Scenario into a concrete SUMO execution.

Returns an execution spec, not metrics — the engine runs it. Each spec names the
routes for each arm, the optional closure additional-file, and the edge to filter
queue metrics on. The canonical network is never edited: closures are rerouter
additional-files, and a traffic increase is a fresh routes file. Both arms load
the same net.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from config import CLOSURE, SIM
from core.scenario.models import (
    BASELINE,
    LANE_CLOSURE,
    ROAD_CLOSURE,
    TRAFFIC_INCREASE,
    Scenario,
)
from core.sim import scenario as SC  # low-level SUMO additional-file writers
from core.sim.demand import generate_routes


def build_execution(
    scenario: Scenario,
    *,
    net_file: str | Path,
    base_routes: str | Path,
    work_dir: str | Path,
) -> dict[str, Any]:
    """Materialise everything a scenario needs to run.

    Keys returned:
      baseline_routes      routes for the reference arm (always the base demand)
      scenario_routes      routes for the scenario arm (base, or heavier demand)
      scenario_additional  closure additional-file path, or None
      edge_filter          edge id to scope queue metrics to, or None
      change               human-readable description of what this scenario does
    """
    net_file = Path(net_file)
    base_routes = Path(base_routes)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    p = scenario.parameters or {}

    spec: dict[str, Any] = {
        "baseline_routes": base_routes,
        "scenario_routes": base_routes,
        "scenario_additional": None,
        "edge_filter": None,
        "change": {"summary": "No modification — canonical baseline."},
    }

    if scenario.type == BASELINE:
        return spec

    if scenario.type == LANE_CLOSURE:
        add = work_dir / "closure.add.xml"
        desc = SC.build_lane_closure(
            net_file, add,
            edge_id=p["edge_id"], lane_index=int(p["lane_index"]),
            begin=CLOSURE["begin"], end=CLOSURE["end"],
        )
        desc["summary"] = (
            f"Lane {p['lane_index']} of {p['edge_id']} closed "
            f"({desc['actual_closed_length_m']} m, t={desc['begin']}–{desc['end']}s)."
        )
        spec.update(scenario_additional=add, edge_filter=p["edge_id"], change=desc)
        return spec

    if scenario.type == ROAD_CLOSURE:
        add = work_dir / "road_closure.add.xml"
        desc = SC.build_road_closure(
            net_file, add,
            edge_id=p["edge_id"],
            begin=CLOSURE["begin"], end=CLOSURE["end"],
        )
        desc["summary"] = (
            f"Edge {p['edge_id']} fully closed "
            f"({desc['actual_closed_length_m']} m, t={desc['begin']}–{desc['end']}s)."
        )
        spec.update(scenario_additional=add, edge_filter=p["edge_id"], change=desc)
        return spec

    if scenario.type == TRAFFIC_INCREASE:
        mult = float(p["demand_multiplier"])
        # LOWER period = MORE traffic, so heavier demand divides the base period.
        heavy_period = round(SIM["period"] / mult, 4)
        d = generate_routes(
            net_file, work_dir,
            begin=SIM["begin"], end=SIM["end"],
            period=heavy_period, fringe_factor=SIM["fringe_factor"],
            seed=scenario.seeds[0], prefix="veh",
        )
        spec.update(
            scenario_routes=d["routes"],
            change={
                "summary": f"Demand ×{mult} (period {SIM['period']} → {heavy_period}).",
                "demand_multiplier": mult,
                "base_period": SIM["period"],
                "scenario_period": heavy_period,
                "scenario_vehicles": d["count"],
            },
        )
        return spec

    # validate() runs first, so this is unreachable in normal flow.
    raise ValueError(f"Cannot build execution for type '{scenario.type}'.")
