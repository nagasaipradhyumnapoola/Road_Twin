"""Filter tested options by an engineering goal (P14).

The search does NOT run SUMO. It reads the P13 intervention payload (candidates
tested with real SUMO + their results) and measures each against the goal. It
reports every tested option's improvement, the best option that SATISFIES the
target, and — when nothing does — the best result actually reached, so the
answer is an honest "not achieved" rather than a forced recommendation.
"""
from __future__ import annotations

from typing import Any

from config import DECISION
from core.decision.models import (
    Goal,
    OBJECTIVE_SPECS,
    improvement_pct,
    signed_change_pct,
)
from core.intervention.models import EVALUATED

# Each V1 candidate is a single lever, so its intervention count is 1.
_INTERVENTION_COUNT = 1

_NOTE = ("Goal measured against the tested options only — a small deterministic "
         "set of single-lever interventions, not an exhaustive search, so the "
         "winner is the best tested option, not necessarily optimal.")


def _option_row(result: dict[str, Any], objective: str,
                target_pct: float, max_interventions: int) -> dict[str, Any]:
    imp = improvement_pct(result, objective)
    within_budget = _INTERVENTION_COUNT <= max_interventions
    meets = (imp is not None and imp >= target_pct and within_budget)
    return {
        "intervention_id": result.get("intervention_id"),
        "name": result.get("name"),
        "type": result.get("type"),
        "improvement_pct": imp,
        "n_interventions": _INTERVENTION_COUNT,
        "within_budget": within_budget,
        "meets_goal": meets,
        "deltas": result.get("deltas"),
        # Signed change of each card metric (travel/queue negative = better,
        # completed positive = better) so the decision card renders directly.
        "metrics_pct": {
            "travel_time": signed_change_pct(result, "avg_travel_time_s"),
            "queue": signed_change_pct(result, "mean_queue_length_m"),
            "completed": signed_change_pct(result, "completed_vehicles"),
        },
    }


def search(payload: dict[str, Any], goal: Goal,
           cfg: dict = DECISION) -> dict[str, Any]:
    """Measure the tested candidates in `payload` against `goal`.

    Returns a JSON-native result: the per-option table, whether the target was
    achieved, the best qualifying option (or None), and the best result reached
    on the goal metric regardless of the target (for the no-solution message).
    """
    if goal.objective not in OBJECTIVE_SPECS:
        raise ValueError(f"Unknown objective '{goal.objective}'.")

    evaluated = [r for r in (payload.get("results") or [])
                 if r.get("status") == EVALUATED]
    rows = [_option_row(r, goal.objective, goal.target_pct, goal.max_interventions)
            for r in evaluated]
    measurable = [r for r in rows if r["improvement_pct"] is not None]

    # Best result reached on the metric, whether or not it clears the target —
    # this is what the honest "not achieved" line reports.
    best_reached = max((r["improvement_pct"] for r in measurable), default=None)

    qualifying = [r for r in rows if r["meets_goal"]]
    # Deterministic winner: largest improvement, then id as a stable tie-break.
    qualifying.sort(key=lambda r: (-r["improvement_pct"], r["intervention_id"] or ""))
    achieved = bool(qualifying)
    best = qualifying[0] if achieved else None

    over_budget = (goal.max_interventions > cfg["supported_max_interventions"])
    note = _NOTE
    if over_budget:
        note += (f" V1 tests single-lever options only; a budget of "
                 f"{goal.max_interventions} cannot be met by an untested "
                 f"combination, so options are still judged one at a time.")

    if achieved:
        message = f"Target achieved: {best['name']} ({best['improvement_pct']:+.1f}%)."
    elif best_reached is None:
        message = "No tested option produced a measurable result for this objective."
    else:
        message = (f"Target not achieved. Best tested result: "
                   f"{best_reached:+.1f}% (requested {goal.target_pct:+.1f}%).")

    return {
        "goal": goal.to_dict(),
        "objective_label": OBJECTIVE_SPECS[goal.objective]["label"],
        "achieved": achieved,
        "best_tested_option": best,
        "best_result_pct": best_reached,
        "options": rows,
        "note": note,
        "message": message,
    }
