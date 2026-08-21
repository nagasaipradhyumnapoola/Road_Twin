"""Rank tested candidates deterministically (P13).

Only evaluated candidates with real metrics rank. Primary key is travel-time
improvement (most negative delta first), then queue improvement, then the id as
a stable tie-break — so the same results always produce the same order and the
same winner. The winner is the "best tested option": the search is a small
deterministic set, not exhaustive, so it is never called "optimal".
"""
from __future__ import annotations

from typing import Any

from core.intervention.models import EVALUATED

_NOTE = ("Best tested option among the tested candidates — a small deterministic "
         "set, not an exhaustive search, so not necessarily optimal.")


def rank(results: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = [
        r for r in results
        if r.get("status") == EVALUATED
        and (r.get("deltas") or {}).get("travel_time_s") is not None
    ]
    evaluated.sort(key=lambda r: (
        r["deltas"]["travel_time_s"],
        r["deltas"].get("queue_m") if r["deltas"].get("queue_m") is not None else 0.0,
        r["intervention_id"],
    ))

    if not evaluated:
        return {"ranked": [], "best_tested_option": None, "improves": False,
                "note": _NOTE,
                "message": "No candidate produced real metrics to rank."}

    best = evaluated[0]
    improves = best["deltas"]["travel_time_s"] < 0
    return {
        "ranked": [r["intervention_id"] for r in evaluated],
        "best_tested_option": {
            "intervention_id": best["intervention_id"],
            "name": best["name"],
            "type": best["type"],
            "deltas": best["deltas"],
        },
        "improves": improves,
        "note": _NOTE,
        "message": (
            f"Best tested option: {best['name']}" if improves
            else "No tested intervention improved on the scenario."
        ),
    }
