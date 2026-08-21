"""Scenario definitions and the type catalogue.

A Scenario is a named, reproducible branch off the canonical twin. It carries
only what is needed to reproduce a run: the type, its parameters, and the seed
set. Metrics are never stored on the Scenario — they live in the separate result
file, keeping the definition immutable and the "reproducible from twin + scenario
+ config + seed" claim honest.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

# Scenario types. Baseline is a first-class type (the unmodified reference), so
# it appears in the list and is runnable like any other.
BASELINE = "baseline"
LANE_CLOSURE = "lane_closure"
ROAD_CLOSURE = "road_closure"
TRAFFIC_INCREASE = "traffic_increase"

SCENARIO_TYPES: tuple[str, ...] = (
    BASELINE, LANE_CLOSURE, ROAD_CLOSURE, TRAFFIC_INCREASE,
)

# One source of truth for what each type needs. Drives BOTH server-side
# validation and the "New Scenario" form in the UI (GET /scenario/types).
# `kind` tells the form how to render each parameter: "edge" = network edge
# selector, "lane" = lane index of the chosen edge, "float"/"int" = number.
TYPE_SPECS: dict[str, dict[str, Any]] = {
    BASELINE: {
        "label": "Baseline",
        "modifies_network": False,
        "help": "The canonical twin with no change — the reference every scenario is measured against.",
        "params": [],
    },
    LANE_CLOSURE: {
        "label": "Lane Closure",
        "modifies_network": False,
        "help": "Close one lane of a multi-lane edge (rerouter, network unchanged).",
        "params": [
            {"name": "edge_id", "kind": "edge", "required": True,
             "label": "Road (edge)"},
            {"name": "lane_index", "kind": "lane", "required": True,
             "label": "Lane to close", "help": "0 = rightmost"},
        ],
    },
    ROAD_CLOSURE: {
        "label": "Road Closure",
        "modifies_network": False,
        "help": "Close every lane of one edge (rerouter, network unchanged).",
        "params": [
            {"name": "edge_id", "kind": "edge", "required": True,
             "label": "Road (edge)"},
        ],
    },
    TRAFFIC_INCREASE: {
        "label": "Traffic Increase",
        "modifies_network": False,
        "help": "Raise demand across the network by a multiplier and re-simulate.",
        "params": [
            {"name": "demand_multiplier", "kind": "float", "required": True,
             "label": "Demand multiplier", "default": 1.2,
             "min": 1.05, "max": 3.0, "step": 0.05,
             "help": "1.2 = +20% vehicles"},
        ],
    },
}


def demand_for(scenario_type: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """The demand a scenario imposes, normalized. 1.0 = canonical (unchanged)
    demand; only a traffic increase raises it. Stored on the scenario so a
    definition records its own demand basis and stays reproducible without
    re-deriving from parameters."""
    multiplier = 1.0
    if scenario_type == TRAFFIC_INCREASE:
        try:
            multiplier = float((parameters or {}).get("demand_multiplier", 1.0))
        except (TypeError, ValueError):
            multiplier = 1.0
    return {"multiplier": multiplier, "source": "canonical_routes"}


@dataclass
class Scenario:
    """A reproducible what-if branch off the canonical twin."""

    scenario_id: str
    name: str
    type: str
    base_twin_id: str = "roadtwin-active"
    parameters: dict[str, Any] = field(default_factory=dict)
    demand: dict[str, Any] = field(default_factory=dict)
    seeds: list[int] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def __post_init__(self) -> None:
        # Derive demand once from type + parameters when not already given, so
        # every scenario (however constructed, and old files loaded without it)
        # carries a demand basis.
        if not self.demand:
            self.demand = demand_for(self.type, self.parameters)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Scenario":
        fields = cls.__dataclass_fields__  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in fields})
