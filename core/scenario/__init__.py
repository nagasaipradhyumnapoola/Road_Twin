"""P11 — What-If Scenario Engine.

The canonical RoadTwin stays fixed; every "what if" is a SCENARIO branch off it,
simulated against the same baseline and stored with its result. This package is
the high-level engine:

    models.py     Scenario dataclass + the type catalogue (drives UI + validation)
    validator.py  reject an impossible scenario before any SUMO run
    builder.py    turn a scenario into a concrete SUMO execution (routes/additional)
    engine.py     run baseline + scenario arms, compare, return real metrics
    registry.py   persist scenarios and their results per project

NOT to be confused with core.sim.scenario, which is the LOW-LEVEL writer of a
single closure additional-file. This package orchestrates; that module emits XML.
builder.py delegates to it for the actual closure files.
"""
from core.scenario.models import (  # noqa: F401
    SCENARIO_TYPES,
    TYPE_SPECS,
    Scenario,
)
