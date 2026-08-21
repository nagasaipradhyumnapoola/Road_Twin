"""Evaluate a candidate with REAL SUMO on a scenario branch (P13).

No second simulation engine: reuses core.sim.run + core.sim.metrics, plus the
existing lane-edit funnel (core.model.edits + core.build.netconvert) for lane
configuration and the rerouter additionals (core.sim.scenario) for diversion.

Every candidate is measured against the UN-INTERVENED scenario (the closure on
the canonical net) on identical seeds. The canonical network is never edited: a
lane-configuration candidate recompiles a BRANCH net inside the workspace; a
routing candidate only adds additional-files. Failures return a result with a
reason and NO metrics — never a fabricated number.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from lxml import etree

from config import CLOSURE, SIM
from core.build.netconvert import plain_to_net
from core.intervention.models import (
    ALT_ROUTING,
    EVALUATED,
    FAILED,
    INVALID,
    LANE_CONFIG,
    Candidate,
)
from core.model.edits import Edit, apply_edits
from core.scenario.builder import build_execution
from core.scenario.models import Scenario
from core.sim import metrics as M
from core.sim import run as sim_run
from core.sim import scenario as SC


# ---------------------------------------------------------------------------
# workspace helpers
# ---------------------------------------------------------------------------
def _find_plain(project_dir: str | Path) -> dict[str, Path] | None:
    """Locate the editable plain-XML substrate for lane reconfiguration."""
    for sub in ("build", "sumo", "."):
        base = Path(project_dir) / sub
        edg = base / "plain.edg.xml"
        nod = base / "plain.nod.xml"
        if edg.exists() and nod.exists():
            plain = {"nod": nod, "edg": edg}
            for k in ("con", "tll", "typ"):
                p = base / f"plain.{k}.xml"
                if p.exists():
                    plain[k] = p
            return plain
    return None


def _merge_additionals(paths: list[Path], out: Path) -> Path:
    """Combine several additional-files into one <additional> root."""
    root = etree.Element("additional")
    for p in paths:
        tree = etree.parse(str(p))
        for child in tree.getroot():
            root.append(child)
    out.parent.mkdir(parents=True, exist_ok=True)
    etree.ElementTree(root).write(str(out), pretty_print=True,
                                  xml_declaration=True, encoding="UTF-8")
    return out


def _subset(agg: dict[str, Any]) -> dict[str, Any]:
    return {
        "avg_travel_time_s": agg.get("avg_travel_time_s"),
        "avg_travel_time_s_sd": agg.get("avg_travel_time_s_sd"),
        "mean_queue_length_m": agg.get("mean_queue_length_m"),
        "completed_vehicles": agg.get("completed_vehicles"),
        "n_seeds": agg.get("n_seeds"),
    }


def _deltas(ref: dict[str, Any], cand: dict[str, Any]) -> dict[str, Any]:
    def d(k):
        a, b = ref.get(k), cand.get(k)
        return round(b - a, 2) if a is not None and b is not None else None
    tt_a, tt_b = ref.get("avg_travel_time_s"), cand.get("avg_travel_time_s")
    return {
        "travel_time_s": d("avg_travel_time_s"),
        "travel_time_pct": (round((tt_b - tt_a) / tt_a * 100, 1)
                            if tt_a not in (None, 0) and tt_b is not None else None),
        "queue_m": d("mean_queue_length_m"),
        "completed_vehicles": d("completed_vehicles"),
    }


# ---------------------------------------------------------------------------
# reference (un-intervened scenario) + candidate evaluation
# ---------------------------------------------------------------------------
def prepare_reference(scenario: Scenario, *, net_file: str | Path,
                      base_routes: str | Path, work_dir: str | Path,
                      seeds: list[int]) -> dict[str, Any]:
    """Run the scenario's own closure on the canonical net — the baseline every
    candidate is judged against. Returns {agg, closure_additional, closed_edge}."""
    work_dir = Path(work_dir)
    spec = build_execution(scenario, net_file=net_file, base_routes=base_routes,
                           work_dir=work_dir / "_scenario")
    closed = (spec.get("closed_edges") or [None])[0]
    agg = sim_run.run_scenario(
        net_file, spec["baseline_routes"], work_dir / "reference",
        seeds=seeds, begin=SIM["begin"], end=SIM["end"],
        additional=spec["scenario_additional"], label="reference",
        edge_filter=closed, collect_edges=False,
    )
    return {"agg": agg, "closure_additional": spec["scenario_additional"],
            "closed_edge": closed, "base_routes": spec["baseline_routes"]}


def evaluate(candidate: Candidate, *, net_file: str | Path, base_routes: str | Path,
             closure_additional: str | Path, closed_edge: str | None,
             reference: dict[str, Any], work_dir: str | Path,
             seeds: list[int], project_dir: str | Path) -> dict[str, Any]:
    """Evaluate one candidate. Returns the persisted result dict (never raises)."""
    work_dir = Path(work_dir)
    base = {
        "intervention_id": candidate.intervention_id,
        "scenario_id": candidate.scenario_id,
        "type": candidate.type,
        "name": candidate.name,
        "parameters": candidate.parameters,
        "seeds": list(seeds),
    }

    if candidate.validation_state == INVALID:
        return {**base, "status": FAILED,
                "failure_reason": candidate.failure_reason or "Candidate is invalid."}

    try:
        if candidate.type == LANE_CONFIG:
            cand_agg = _run_lane_config(candidate, net_file=net_file,
                                        base_routes=base_routes,
                                        closure_additional=closure_additional,
                                        closed_edge=closed_edge, work_dir=work_dir,
                                        seeds=seeds, project_dir=project_dir)
        elif candidate.type == ALT_ROUTING:
            cand_agg = _run_alt_routing(candidate, net_file=net_file,
                                        base_routes=base_routes,
                                        closure_additional=closure_additional,
                                        closed_edge=closed_edge, work_dir=work_dir,
                                        seeds=seeds)
        else:  # unreachable — validator blocks it
            raise ValueError(f"Unsupported type '{candidate.type}'.")

        cmp = M.compare(reference["agg"], cand_agg)
        return {
            **base, "status": EVALUATED,
            "baseline": _subset(reference["agg"]),
            "intervention": _subset(cand_agg),
            "deltas": _deltas(reference["agg"], cand_agg),
            "significant": cmp.get("significant"),
            "comparison": {"rows": cmp.get("rows"), "verdict": cmp.get("verdict")},
        }
    except Exception as exc:  # real failure — keep it, no fake metrics
        return {**base, "status": FAILED, "failure_reason": str(exc)}


def _run_lane_config(candidate, *, net_file, base_routes, closure_additional,
                     closed_edge, work_dir, seeds, project_dir) -> dict[str, Any]:
    plain = _find_plain(project_dir)
    if plain is None:
        raise RuntimeError(
            "Plain network files (plain.edg.xml/plain.nod.xml) are not available, "
            "so lanes cannot be reconfigured. Rebuild the model (POST /model/build)."
        )
    p = candidate.parameters
    branch_edg = work_dir / "branch.edg.xml"
    apply_edits(
        plain["edg"],
        [Edit(edge_id=p["edge_id"], attribute="numLanes",
              old_value=None, new_value=str(int(p["to_lanes"])),
              source="intervention")],
        branch_edg,
    )
    branch_plain = {**plain, "edg": branch_edg}
    branch_net = work_dir / "branch.net.xml"
    plain_to_net(branch_plain, branch_net)   # recompile — into the workspace only
    return sim_run.run_scenario(
        branch_net, base_routes, work_dir / "candidate",
        seeds=seeds, begin=SIM["begin"], end=SIM["end"],
        additional=closure_additional, label="candidate",
        edge_filter=closed_edge, collect_edges=False,
    )


def _run_alt_routing(candidate, *, net_file, base_routes, closure_additional,
                     closed_edge, work_dir, seeds) -> dict[str, Any]:
    p = candidate.parameters
    div = SC.build_diversion(
        net_file, work_dir / "diversion.add.xml",
        avoid_edge=p["avoid_edge"], trigger_edges=p["trigger_edges"],
        begin=CLOSURE["begin"], end=CLOSURE["end"],
    )
    combined = _merge_additionals(
        [Path(closure_additional), Path(div["additional_file"])],
        work_dir / "combined.add.xml",
    )
    return sim_run.run_scenario(
        net_file, base_routes, work_dir / "candidate",
        seeds=seeds, begin=SIM["begin"], end=SIM["end"],
        additional=combined, label="candidate",
        edge_filter=closed_edge, collect_edges=False,
    )
