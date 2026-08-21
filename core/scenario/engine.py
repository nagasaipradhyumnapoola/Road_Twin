"""Run a scenario: baseline arm + scenario arm, compared, with real metrics.

Every closure/traffic scenario runs its OWN baseline arm on the same seeds, so
each result is self-contained and reproducible from (twin + scenario + config +
seed). The canonical twin is never touched — both arms load the identical net;
only the additional-file (or the demand) differs, so the delta is causal.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from config import SIM
from core.impact import analysis as impact_analysis
from core.scenario.builder import build_execution
from core.scenario.models import BASELINE, Scenario
from core.scenario.validator import validate
from core.sim import metrics as M
from core.sim import run as sim_run


def execute(
    scenario: Scenario,
    *,
    net_file: str | Path,
    base_routes: str | Path,
    work_dir: str | Path,
) -> dict[str, Any]:
    """Validate, build, simulate, and compare. Returns the stored result shape."""
    validate(scenario, net_file)
    spec = build_execution(
        scenario, net_file=net_file, base_routes=base_routes, work_dir=work_dir,
    )
    work_dir = Path(work_dir)
    seeds = scenario.seeds

    baseline = sim_run.run_scenario(
        net_file, spec["baseline_routes"], work_dir,
        seeds=seeds, begin=SIM["begin"], end=SIM["end"],
        additional=None, label="baseline", edge_filter=spec["edge_filter"],
    )

    result: dict[str, Any] = {
        "scenario_id": scenario.scenario_id,
        "name": scenario.name,
        "type": scenario.type,
        "seeds": seeds,
        "change": spec["change"],
        "baseline": baseline,
    }

    if scenario.type == BASELINE:
        # The reference has nothing to compare against — its own metrics ARE the
        # result. Do not fabricate a comparison.
        result.update(scenario=None, comparison=None, table=None)
        return result

    scen = sim_run.run_scenario(
        net_file, spec["scenario_routes"], work_dir,
        seeds=seeds, begin=SIM["begin"], end=SIM["end"],
        additional=spec["scenario_additional"], label="scenario",
        edge_filter=spec["edge_filter"],
    )
    cmp = M.compare(baseline, scen)

    # P12 — attribute the aggregate change to specific edges and junctions,
    # from the real per-edge metrics both arms just produced.
    impact = impact_analysis.analyze(
        baseline_edges=baseline.get("edges") or {},
        scenario_edges=scen.get("edges") or {},
        net_file=net_file,
        closed_edges=spec.get("closed_edges") or [],
        comparison=cmp,
        scenario_id=scenario.scenario_id,
        seeds=seeds,
    )

    result.update(scenario=scen, comparison=cmp, table=M.format_table(cmp),
                  impact=impact)
    return result
