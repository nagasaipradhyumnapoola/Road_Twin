"""Engineering goal vocabulary + the per-objective improvement measure (P14).

A Goal is what the engineer asks for; the improvement functions turn a tested
P13 candidate result into a single signed "improvement toward this goal" number,
always as a percentage of the un-intervened scenario baseline the candidate was
measured against. Every number here is derived from the candidate's own
real-SUMO baseline/intervention subsets — nothing is invented.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Objectives. Each maps to one measured metric and a direction of "better".
REDUCE_TRAVEL_TIME = "reduce_travel_time"
REDUCE_QUEUE = "reduce_queue"
INCREASE_COMPLETED = "increase_completed"
OBJECTIVES: tuple[str, ...] = (REDUCE_TRAVEL_TIME, REDUCE_QUEUE, INCREASE_COMPLETED)

# One source of truth for the goal form (GET /decision/objectives) and for the
# improvement math below. `metric` names the baseline/intervention subset key;
# `direction` says which way is an improvement.
OBJECTIVE_SPECS: dict[str, dict[str, Any]] = {
    REDUCE_TRAVEL_TIME: {
        "label": "Reduce travel time",
        "metric": "avg_travel_time_s",
        "direction": "reduce",
        "unit": "s",
        "help": "Lower average vehicle travel time across the network.",
    },
    REDUCE_QUEUE: {
        "label": "Reduce queue",
        "metric": "mean_queue_length_m",
        "direction": "reduce",
        "unit": "m",
        "help": "Lower the mean queue length across the network.",
    },
    INCREASE_COMPLETED: {
        "label": "Increase completed vehicles",
        "metric": "completed_vehicles",
        "direction": "increase",
        "unit": "veh",
        "help": "More vehicles complete their trips within the simulation window.",
    },
}


@dataclass
class Goal:
    """A measurable engineering goal against a scenario's tested options."""

    objective: str
    target_pct: float           # required improvement, as a positive percentage
    max_interventions: int = 1  # V1 tests single-lever options (see config.DECISION)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Goal":
        fields = cls.__dataclass_fields__  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in fields})


def improvement_pct(result: dict[str, Any], objective: str) -> float | None:
    """Signed improvement of a tested candidate toward `objective`, in percent.

    Positive means the goal moved in the right direction (travel time / queue
    fell, or completed vehicles rose). Measured against the candidate's own
    real-SUMO baseline. Returns None when the metric is missing on either arm,
    or the baseline is zero (percentage undefined) — never a fabricated number.
    """
    spec = OBJECTIVE_SPECS.get(objective)
    if spec is None:
        return None
    key = spec["metric"]
    base = (result.get("baseline") or {}).get(key)
    cand = (result.get("intervention") or {}).get(key)
    if base in (None, 0) or cand is None:
        return None
    if spec["direction"] == "reduce":
        return round((base - cand) / base * 100.0, 1)
    return round((cand - base) / base * 100.0, 1)


def signed_change_pct(result: dict[str, Any], metric_key: str) -> float | None:
    """Raw change (intervention − baseline) as a percentage of baseline.

    Sign is the physical change, not "improvement": travel-time/queue fall
    read negative, completed-vehicles rise reads positive — exactly how the
    decision card presents each metric. None when undefined.
    """
    base = (result.get("baseline") or {}).get(metric_key)
    cand = (result.get("intervention") or {}).get(metric_key)
    if base in (None, 0) or cand is None:
        return None
    return round((cand - base) / base * 100.0, 1)
