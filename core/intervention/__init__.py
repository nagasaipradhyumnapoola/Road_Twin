"""P13 — intervention engine.

Turns "this is what happens" (a scenario + its impact) into "what can we do
about it": generate a small deterministic set of candidate interventions,
validate them, evaluate each with REAL SUMO on a scenario branch (the canonical
twin is never touched), compare against the un-intervened scenario, and rank —
surfacing the *best tested option* (never an "optimal" one). Failed candidates
are kept with their reason, never silently dropped.
"""
