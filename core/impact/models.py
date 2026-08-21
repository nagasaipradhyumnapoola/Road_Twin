"""Impact vocabulary + result shapes (P12).

Kept deliberately small: the analysis emits plain JSON-native dicts (so the
result serializes straight into the scenario result file), and these dataclasses
document and construct those dicts without adding a second storage architecture.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Impact classes — deterministic severity of worsening on an edge.
UNCHANGED = "UNCHANGED"
LOW = "LOW"
MODERATE = "MODERATE"
HIGH = "HIGH"
SEVERE = "SEVERE"
CLASSES = (UNCHANGED, LOW, MODERATE, HIGH, SEVERE)
# Index order for band lookups (UNCHANGED handled separately).
SEVERITY_ORDER = (LOW, MODERATE, HIGH, SEVERE)

# Attribution — how the edge relates to the scenario change.
DIRECTLY_AFFECTED = "DIRECTLY_AFFECTED"
SECONDARILY_AFFECTED = "SECONDARILY_AFFECTED"
ATTR_UNCHANGED = "UNCHANGED"


@dataclass
class EdgeImpact:
    edge_id: str
    attribution: str
    impact_class: str
    # Deltas (scenario − baseline). None when a metric is absent in an arm.
    travel_time_delta_s: float | None = None
    travel_time_delta_pct: float | None = None
    queue_delta_m: float | None = None
    speed_delta_mps: float | None = None
    waiting_time_delta_s: float | None = None
    entered_delta: float | None = None
    # Raw arms, so a reader can trace the delta back to measured values.
    baseline: dict[str, Any] | None = None
    scenario: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JunctionImpact:
    junction_id: str
    impact_score: float
    total_queue_increase_m: float
    total_waiting_increase_s: float
    n_incident_affected: int
    worst_edge: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ImpactResult:
    scenario_id: str
    edges: list[dict[str, Any]] = field(default_factory=list)
    critical_junctions: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
