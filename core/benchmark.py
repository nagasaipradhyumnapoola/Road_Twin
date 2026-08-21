"""P10 — Acceleration Proof: the modeling benchmark record.

PS95 asks the system to *accelerate* road-network modeling. This module records,
from real measured values only, how much of that modeling is automated (stage
timings + network size) and how much human effort remains (confirmations,
evidence reviews, manual edits).

HARD RULE (from RoadTwin_Phases_10_14_FINAL.md §10):
  Never invent a manual baseline or an unsupported "X times faster" claim.
  This record therefore stores measured seconds and counts ONLY. It has no
  `manual_baseline`, `speedup`, or `faster` field, and callers must not add one.

One record per project, written to <project>/benchmark.json. Both the headless
spine (scripts/run_benchmark.py) and the interactive API endpoints populate it
through the helpers here, so there is a single schema and a single writer.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.sim.scenario import read_net_edges

BENCHMARK_ID = "accel-001"

# The automated MODELING stages that make up the headline TOTAL, in display
# order. Simulation is measured too but reported SEPARATELY (see load()):
# modeling is not simulation, and the doc's total excludes it.
MODELING_STAGES: tuple[str, ...] = (
    "acquisition_s",
    "model_generation_s",
    "compilation_s",
    "export_s",
)

# Keys that would express an unsupported comparative speed claim. Guarded against
# so the "no unsupported speed claim" rule cannot rot silently.
_FORBIDDEN_KEYS = ("manual_baseline", "speedup", "faster", "times_faster", "baseline_s")


def _benchmark_path(project_dir: str | Path) -> Path:
    return Path(project_dir) / "benchmark.json"


# ---------------------------------------------------------------------------
# measured inputs
# ---------------------------------------------------------------------------
def network_size_from_net(net_file: str | Path) -> dict[str, int]:
    """Roads, junctions and lanes from a compiled SUMO network.

    roads     = drivable (non-internal) edges
    lanes     = total lanes across those edges
    junctions = real intersections — same definition the canonical model and the
                map use (core/model/geometry.py:junctions_to_geojson): skip
                lane-internal (`:`-prefixed / type "internal") and dead-end nodes.
                Keeping this identical means the Acceleration panel's junction
                count matches the Pipeline tab's, rather than diverging.
    """
    edges = read_net_edges(net_file)
    roads = len(edges)
    lanes = sum(e["num_lanes"] for e in edges.values())

    junctions = 0
    from lxml import etree
    for _, el in etree.iterparse(str(net_file), tag="junction"):
        jid, jtype = el.get("id"), el.get("type")
        if jid and not jid.startswith(":") and jtype not in ("internal", "dead_end"):
            junctions += 1
        el.clear()

    return {"roads": roads, "junctions": junctions, "lanes": lanes}


def human_actions_from_project(project_dir: str | Path) -> dict[str, int]:
    """Human effort, computed live from project files — never fabricated.

    location_confirmation : 1 if a confirmed location.json exists, else 0
    evidence_reviews      : number of decisions recorded in validation_report.json
                            (each is a human ruling on one AI observation)
    manual_edits          : decisions whose user_action == "edit" (a hand-entered
                            value, distinct from accepting or rejecting the AI)
    """
    proj = Path(project_dir)

    location_confirmation = 0
    loc = proj / "location.json"
    if loc.exists():
        try:
            if json.loads(loc.read_text(encoding="utf-8")).get("confirmed"):
                location_confirmation = 1
        except Exception:
            pass

    evidence_reviews = 0
    manual_edits = 0
    report = proj / "validation_report.json"
    if report.exists():
        try:
            decisions = json.loads(report.read_text(encoding="utf-8")).get("decisions", [])
            evidence_reviews = len(decisions)
            manual_edits = sum(1 for d in decisions if d.get("user_action") == "edit")
        except Exception:
            pass

    return {
        "location_confirmation": location_confirmation,
        "evidence_reviews": evidence_reviews,
        "manual_edits": manual_edits,
    }


def _sumo_version() -> str | None:
    try:
        from core.build.netconvert import sumo_bin
        from core.provenance import tool_version
        # Resolve the absolute binary path first — a bare "netconvert" is not on
        # PATH when SUMO is only the pip-installed `eclipse-sumo` package.
        v = tool_version(sumo_bin("netconvert"))
        return v if v and v != "unknown" else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# storage (upsert into benchmark.json)
# ---------------------------------------------------------------------------
def _read_raw(project_dir: str | Path) -> dict[str, Any]:
    p = _benchmark_path(project_dir)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def _write_raw(project_dir: str | Path, data: dict[str, Any]) -> Path:
    # Guard: the stored record must never carry an unsupported speed claim.
    for k in _FORBIDDEN_KEYS:
        data.pop(k, None)
    if isinstance(data.get("timings"), dict):
        for k in _FORBIDDEN_KEYS:
            data["timings"].pop(k, None)
    p = _benchmark_path(project_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def update_stage(project_dir: str | Path, stage: str, seconds: float) -> Path:
    """Record one measured stage timing. Upserts benchmark.json.

    `stage` is a timings key such as "acquisition_s" or "simulation_s".
    """
    data = _read_raw(project_dir)
    data.setdefault("benchmark_id", BENCHMARK_ID)
    data.setdefault("created_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    data.setdefault("timings", {})
    data["timings"][stage] = round(float(seconds), 3)
    data["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sv = _sumo_version()
    if sv:
        data["sumo_version"] = sv
    return _write_raw(project_dir, data)


def set_network(project_dir: str | Path, net_file: str | Path) -> Path:
    """Record the network size from a compiled net. Upserts benchmark.json."""
    data = _read_raw(project_dir)
    data.setdefault("benchmark_id", BENCHMARK_ID)
    data.setdefault("created_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    data["network"] = network_size_from_net(net_file)
    data["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return _write_raw(project_dir, data)


def record_run(
    project_dir: str | Path,
    *,
    timings: dict[str, float],
    net_file: str | Path,
    seeds: int | None = None,
) -> Path:
    """Write a complete record in one shot — the headless-spine path.

    `timings` maps timings keys to measured seconds (e.g. acquisition_s,
    model_generation_s, compilation_s, export_s, simulation_s). total_s is
    derived at load time from the modeling stages, so it need not be passed.
    """
    data = _read_raw(project_dir)
    data["benchmark_id"] = BENCHMARK_ID
    data.setdefault("created_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    data["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["timings"] = {k: round(float(v), 3) for k, v in timings.items()}
    data["network"] = network_size_from_net(net_file)
    if seeds is not None:
        data["seeds"] = int(seeds)
    sv = _sumo_version()
    if sv:
        data["sumo_version"] = sv
    return _write_raw(project_dir, data)


# ---------------------------------------------------------------------------
# read (merge stored timings/network with live location + human effort)
# ---------------------------------------------------------------------------
def load(project_dir: str | Path) -> dict[str, Any] | None:
    """Return the full benchmark view, or None if nothing has been recorded.

    Location and human_actions are read LIVE from the project so they always
    reflect current truth; total_s is the sum of the recorded modeling stages.
    """
    data = _read_raw(project_dir)
    if not data or not data.get("timings"):
        return None

    proj = Path(project_dir)
    timings: dict[str, Any] = dict(data.get("timings", {}))
    total = sum(
        float(timings[k]) for k in MODELING_STAGES
        if isinstance(timings.get(k), (int, float))
    )
    timings["total_s"] = round(total, 3)

    location = None
    loc = proj / "location.json"
    if loc.exists():
        try:
            d = json.loads(loc.read_text(encoding="utf-8"))
            location = {
                "name": d.get("name"),
                "lat": d.get("lat"),
                "lon": d.get("lon"),
                "aoi_radius_m": d.get("aoi_radius_m"),
            }
        except Exception:
            location = None

    return {
        "benchmark_id": data.get("benchmark_id", BENCHMARK_ID),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
        "location": location,
        "network": data.get("network"),
        "timings": timings,
        "human_actions": human_actions_from_project(proj),
        "seeds": data.get("seeds"),
        "sumo_version": data.get("sumo_version") or _sumo_version(),
    }
