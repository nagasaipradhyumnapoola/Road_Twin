"""Assemble the final decision card (P14 §14.5).

The card is a plain summary of numbers already established elsewhere — the
confirmed location, the scenario definition, the P12 impact summary, the P14
goal search, and the seed count. It computes nothing new: every figure traces
back to a real run. Assumptions and limitations are stated, never hidden.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.scenario.models import Scenario

_SYNTHETIC_DEMAND = "Synthetic demand (randomTrips), not field-measured counts."
_NO_CALIBRATION = "Field calibration unavailable — results are relative, not absolute."


def _critical_junction(impact: dict[str, Any] | None) -> str | None:
    crits = (impact or {}).get("critical_junctions") or []
    return crits[0].get("junction_id") if crits else None


def build(*, scenario: Scenario, location: dict[str, Any] | None,
          impact: dict[str, Any] | None, goal_result: dict[str, Any],
          seeds: list[int]) -> dict[str, Any]:
    """Build the decision card dict, ready to persist and export."""
    summary = (impact or {}).get("summary") or {}
    best = goal_result.get("best_tested_option")

    if best is not None:
        m = best.get("metrics_pct") or {}
        best_block = {
            "intervention_id": best.get("intervention_id"),
            "name": best.get("name"),
            "type": best.get("type"),
            "improvement_pct": best.get("improvement_pct"),
            "result": {
                "travel_time_pct": m.get("travel_time"),
                "queue_pct": m.get("queue"),
                "completed_pct": m.get("completed"),
            },
        }
    else:
        best_block = None

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "location": {
            "name": (location or {}).get("name", "unnamed"),
            "critical_junction": _critical_junction(impact),
        },
        "scenario": {
            "scenario_id": scenario.scenario_id,
            "name": scenario.name,
            "type": scenario.type,
        },
        "impact": {
            "travel_time_pct": summary.get("travel_time_delta_pct"),
            "queue_pct": summary.get("queue_delta_pct"),
            "affected_roads": summary.get("affected_roads"),
            "critical_junctions": summary.get("critical_junctions"),
        },
        "goal": goal_result.get("goal"),
        "objective_label": goal_result.get("objective_label"),
        "achieved": goal_result.get("achieved", False),
        "best_tested_option": best_block,
        "best_result_pct": goal_result.get("best_result_pct"),
        "message": goal_result.get("message"),
        "simulation": {"seeds": len(seeds), "seed_values": list(seeds)},
        "assumptions": [_SYNTHETIC_DEMAND],
        "limitations": [_NO_CALIBRATION],
        "note": goal_result.get("note"),
    }
