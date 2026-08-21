"""Intervention vocabulary + candidate shape (P13).

A Candidate is a structured, reproducible proposal to improve a scenario. It
carries only what is needed to reproduce a run (type + parameters + the scenario
it branches from); the measured outcome lives in a separate result dict, so the
definition stays immutable and the "reproducible from twin + scenario + candidate
+ seeds" claim stays honest.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

# V1 intervention types (only these two are mandatory / implemented).
LANE_CONFIG = "lane_configuration"
ALT_ROUTING = "alternative_routing"
INTERVENTION_TYPES: tuple[str, ...] = (LANE_CONFIG, ALT_ROUTING)

# Validation state of a candidate definition.
PENDING = "pending"
VALID = "valid"
INVALID = "invalid"

# Status of an evaluated candidate result.
EVALUATED = "evaluated"
FAILED = "failed"


@dataclass
class Candidate:
    """One structured, reproducible intervention proposal."""

    intervention_id: str
    scenario_id: str
    type: str
    name: str
    parameters: dict[str, Any] = field(default_factory=dict)
    validation_state: str = PENDING
    failure_reason: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Candidate":
        fields = cls.__dataclass_fields__  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in fields})
