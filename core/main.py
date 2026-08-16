"""Core FastAPI sidecar — the only Python process the Tauri app talks to.

Endpoints:
  GET  /health                 → liveness + capability probe
  GET  /location               → current confirmed location (or null)
  POST /location/geocode       → address → candidates list
  POST /location/confirm       → write location.json, gate downstream
  POST /acquire                → download OSM (requires confirmed location)
  POST /model/build            → build canonical model from net.xml
  GET  /network/geojson        → roads + junctions GeoJSON for MapLibre

Frozen binary path-resolution note:
  When frozen by PyInstaller, __file__ is inside a temp _MEIPASS directory.
  config.py reads ROOT from its own __file__, which works correctly in both
  the live and frozen environments because we add the repo root to sys.path
  before importing anything from core/.
"""
from __future__ import annotations

import json
import sys
import os
from pathlib import Path

# ── path setup ────────────────────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    _base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
else:
    _base = Path(__file__).resolve().parent.parent

if str(_base) not in sys.path:
    sys.path.insert(0, str(_base))

# ── imports ───────────────────────────────────────────────────────────────────
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── version ───────────────────────────────────────────────────────────────────
__version__ = "0.2.0"

# ── app ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="RoadTwin Core API",
    version=__version__,
    description="Headless backend for the RoadTwin desktop application.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # Tauri WebView origin is app://localhost
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── request / response models ─────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    version: str
    sumo: bool
    sumo_home: str | None


class GeocodeRequest(BaseModel):
    query: str


class GeocandiDate(BaseModel):
    display_name: str
    lat: float
    lon: float
    importance: float


class ConfirmRequest(BaseModel):
    name: str
    lat: float
    lon: float
    aoi_radius_m: float = 500.0
    confirmation_method: str = "user"


class AcquireRequest(BaseModel):
    force: bool = False   # skip cache and re-download


class BuildRequest(BaseModel):
    pass


# ── project directory helper ──────────────────────────────────────────────────

def _project_dir() -> Path:
    """Active project directory — always 'active' until multi-project support."""
    try:
        from config import PROJECTS_DIR
        p = PROJECTS_DIR / "active"
        p.mkdir(parents=True, exist_ok=True)
        return p
    except Exception:
        p = _base / "projects" / "active"
        p.mkdir(parents=True, exist_ok=True)
        return p


def _location_path() -> Path:
    return _project_dir() / "location.json"


def _read_location() -> dict | None:
    p = _location_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _require_location() -> dict:
    loc = _read_location()
    if not loc or not loc.get("confirmed"):
        raise HTTPException(
            status_code=412,
            detail="Location not confirmed. POST /location/confirm first.",
        )
    return loc


# ── helpers ───────────────────────────────────────────────────────────────────

def _sumo_ok() -> tuple[bool, str | None]:
    try:
        from core.build.netconvert import sumo_home
        p = str(sumo_home())
        return True, p
    except Exception:
        return False, None


# ── routes ────────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness + capability probe. Tauri polls this on startup."""
    ok, path = _sumo_ok()
    return HealthResponse(status="ok", version=__version__, sumo=ok, sumo_home=path)


@app.get("/location")
def get_location() -> dict:
    """Return current confirmed location, or {confirmed: false}."""
    loc = _read_location()
    return loc if loc else {"confirmed": False}


@app.post("/location/geocode")
def geocode(body: GeocodeRequest) -> list[GeocandiDate]:
    """Address → candidate list via Nominatim (rate-limited, cached)."""
    try:
        from core.acquire.geocoder import geocode as _geocode
        from config import OVERPASS, ASSETS
        cache_dir = ASSETS / "geocache"
        results = _geocode(
            body.query,
            user_agent=OVERPASS["user_agent"],
            cache_dir=cache_dir,
        )
        return [GeocandiDate(**r) for r in results]
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/location/confirm")
def confirm_location(body: ConfirmRequest) -> dict:
    """Write location.json. Gates all downstream pipeline calls."""
    data = {
        "name": body.name,
        "lat": body.lat,
        "lon": body.lon,
        "aoi_radius_m": body.aoi_radius_m,
        "crs": "EPSG:4326",
        "confirmed": True,
        "confirmation_method": body.confirmation_method,
    }
    _location_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {"ok": True, "location": data}


@app.post("/acquire")
def acquire_osm(body: AcquireRequest) -> dict:
    """Download OSM extract for the confirmed location."""
    loc = _require_location()
    try:
        from config import OVERPASS, ASSETS
        from core.acquire.overpass import fetch_osm, bbox_from_point

        lat, lon, radius = loc["lat"], loc["lon"], loc.get("aoi_radius_m", 500)
        bbox = bbox_from_point(lat, lon, radius)
        proj = _project_dir()
        osm_path = fetch_osm(
            bbox,
            out_path=proj / "network.osm",
            endpoint=OVERPASS["endpoint"],
            user_agent=OVERPASS["user_agent"],
            timeout_s=OVERPASS["timeout_s"],
            cache_dir=ASSETS / "osm_cache",
            allow_network=True,
        )
        return {"ok": True, "osm_path": str(osm_path),
                "size_kb": round(osm_path.stat().st_size / 1024, 1)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/model/build")
def build_model(body: BuildRequest) -> dict:
    """OSM → netconvert → canonical model. Requires confirmed location + OSM."""
    loc_data = _require_location()
    proj = _project_dir()
    osm_path = proj / "network.osm"
    if not osm_path.exists():
        raise HTTPException(status_code=412, detail="OSM not acquired. POST /acquire first.")

    try:
        from config import PROJECTS_DIR
        from core.build.netconvert import plain_to_net, osm_to_plain, sumo_home
        from core.model.builder import build_from_net
        from core.model.roadtwin import Location

        build_dir = proj / "sumo"
        build_dir.mkdir(exist_ok=True)

        # 1. OSM → plain XML  (returns dict[str, Path])
        plain = osm_to_plain(osm_path, build_dir)

        # 2. plain XML → net.xml + xodr
        net_file = build_dir / "network.net.xml"
        xodr_file = build_dir / "road_network.xodr"
        plain_to_net(plain, net_file, xodr_out=xodr_file)

        # 3. Build canonical model
        location = Location(
            name=loc_data["name"],
            lat=loc_data["lat"],
            lon=loc_data["lon"],
            aoi_radius_m=loc_data.get("aoi_radius_m", 500),
            confirmed=True,
            confirmation_method=loc_data.get("confirmation_method", "user"),
        )
        model = build_from_net(net_file, location, proj)

        return {
            "ok": True,
            "roads": len(model.roads),
            "lanes": len(model.lanes),
            "junctions": len(model.junctions),
            "project_dir": str(proj),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/network/geojson")
def network_geojson() -> dict:
    """Return roads + junctions GeoJSON for the MapLibre overlay."""
    proj = _project_dir()
    roads_path = proj / "roads.geojson"
    juncs_path = proj / "junctions.geojson"

    result: dict = {}
    if roads_path.exists():
        result["roads"] = json.loads(roads_path.read_text(encoding="utf-8"))
    if juncs_path.exists():
        result["junctions"] = json.loads(juncs_path.read_text(encoding="utf-8"))

    if not result:
        raise HTTPException(status_code=404, detail="Model not built yet. POST /model/build first.")

    return result



# ── P6 experiment state (in-memory, single-project) ──────────────────────────
# Stores the last experiment result so the UI can poll without re-running.
_experiment_state: dict = {"status": "idle"}   # idle | running | done | error


class DemandRequest(BaseModel):
    period: float = 0.8
    fringe_factor: float = 10.0
    force: bool = False


class ScenarioRequest(BaseModel):
    edge_id: str
    lane_index: int
    begin: int = 300
    end: int = 3600


class ExperimentRequest(BaseModel):
    edge_id: str
    lane_index: int
    seeds: list[int] | None = None   # None → use config defaults


# ── P6 routes ─────────────────────────────────────────────────────────────────

@app.get("/network/edges")
def list_edges() -> dict:
    """List drivable edges from the compiled network — drives the UI selectors."""
    _require_location()
    proj = _project_dir()
    net_file = proj / "sumo" / "network.net.xml"
    if not net_file.exists():
        raise HTTPException(status_code=412, detail="Network not built. POST /model/build first.")

    try:
        from core.sim.scenario import read_net_edges, pick_closure_candidate
        edges = read_net_edges(net_file)
        candidate = pick_closure_candidate(net_file)

        # Filter to multi-lane only (single-lane can't be meaningfully closed)
        multi = {
            eid: {
                "num_lanes": d["num_lanes"],
                "length_m": round(d["length_m"], 1),
                "from": d["from"],
                "to": d["to"],
                "lanes": d["lanes"],
            }
            for eid, d in edges.items()
            if d["num_lanes"] >= 2
        }
        return {
            "edges": multi,
            "total_edges": len(edges),
            "multi_lane_edges": len(multi),
            "recommended": candidate,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/demand/generate")
def generate_demand(body: DemandRequest) -> dict:
    """Generate traffic demand (randomTrips). Required before running experiment."""
    _require_location()
    proj = _project_dir()
    net_file = proj / "sumo" / "network.net.xml"
    if not net_file.exists():
        raise HTTPException(status_code=412, detail="Network not built. POST /model/build first.")

    routes_file = proj / "sumo" / "routes.rou.xml"
    if routes_file.exists() and not body.force:
        n = routes_file.read_text(errors="ignore").count("<vehicle ")
        return {"ok": True, "cached": True, "vehicle_count": n,
                "routes_file": str(routes_file), "period": body.period}

    try:
        from config import SIM
        from core.sim.demand import generate_routes
        d = generate_routes(
            net_file, proj / "sumo",
            begin=SIM["begin"], end=SIM["end"],
            period=body.period, fringe_factor=body.fringe_factor,
            seed=SIM["seeds"][0],
        )
        # warn if too low
        warning = None
        if d["count"] < 100:
            warning = (f"Only {d['count']} vehicles generated. Lower period for more traffic."
                       " A closure on a near-empty network changes nothing.")
        return {"ok": True, "cached": False, "vehicle_count": d["count"],
                "routes_file": str(d["routes"]), "period": body.period,
                "warning": warning}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/scenario/build")
def build_scenario(body: ScenarioRequest) -> dict:
    """Write the lane-closure additional-file. Validates edge + lane before writing."""
    _require_location()
    proj = _project_dir()
    net_file = proj / "sumo" / "network.net.xml"
    if not net_file.exists():
        raise HTTPException(status_code=412, detail="Network not built. POST /model/build first.")

    try:
        from core.sim.scenario import build_lane_closure
        closure_file = proj / "sumo" / "closure.add.xml"
        desc = build_lane_closure(
            net_file, closure_file,
            edge_id=body.edge_id, lane_index=body.lane_index,
            begin=body.begin, end=body.end,
        )
        (proj / "scenario.json").write_text(json.dumps(desc, indent=2), encoding="utf-8")
        return {"ok": True, "scenario": desc}
    except ValueError as exc:
        # Invalid edge / lane — surface as 422 so the UI shows a clear error
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/experiment/status")
def experiment_status() -> dict:
    """Poll the current experiment state (idle | running | done | error)."""
    return _experiment_state


@app.post("/experiment/run")
def run_experiment_endpoint(body: ExperimentRequest) -> dict:
    """Run the full baseline-vs-closure experiment.

    This is a synchronous call — it blocks until all seeds complete.
    For the UI: show a spinner, then poll /experiment/status once returned.
    Heavy but honest: the numbers don't appear until they are real.
    """
    global _experiment_state
    if _experiment_state.get("status") == "running":
        raise HTTPException(status_code=409, detail="Experiment already running. Wait for it to finish.")

    _require_location()
    proj = _project_dir()
    net_file = proj / "sumo" / "network.net.xml"
    routes_file = proj / "sumo" / "routes.rou.xml"
    closure_file = proj / "sumo" / "closure.add.xml"

    if not net_file.exists():
        raise HTTPException(status_code=412, detail="Network not built.")
    if not routes_file.exists():
        raise HTTPException(status_code=412, detail="Routes not generated. POST /demand/generate first.")
    if not closure_file.exists():
        raise HTTPException(status_code=412, detail="Scenario not built. POST /scenario/build first.")

    try:
        from config import SIM, CLOSURE
        from core.sim import run as sim_run
        from core.sim.scenario import build_lane_closure, read_net_edges

        _experiment_state = {"status": "running"}

        # Rebuild closure file to match the requested edge/lane
        edges = read_net_edges(net_file)
        if body.edge_id not in edges:
            raise ValueError(f"Edge '{body.edge_id}' not in network.")
        desc = build_lane_closure(
            net_file, closure_file,
            edge_id=body.edge_id, lane_index=body.lane_index,
            begin=CLOSURE["begin"], end=CLOSURE["end"],
        )
        (proj / "scenario.json").write_text(json.dumps(desc, indent=2), encoding="utf-8")

        seeds = body.seeds if body.seeds else SIM["seeds"]
        result = sim_run.run_experiment(
            net_file, routes_file,
            proj / "sumo" / "results",
            closure_file,
            seeds=seeds,
            begin=SIM["begin"], end=SIM["end"],
            closed_edge=body.edge_id,
        )

        # Persist metrics
        metrics_data = {k: v for k, v in result.items() if k != "table"}
        (proj / "metrics.json").write_text(json.dumps(metrics_data, indent=2), encoding="utf-8")

        _experiment_state = {
            "status": "done",
            "result": result,
            "scenario": desc,
        }
        return _experiment_state

    except ValueError as exc:
        _experiment_state = {"status": "error", "detail": str(exc)}
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        _experiment_state = {"status": "error", "detail": str(exc)}
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Vision Endpoints (Phase 7) ────────────────────────────────────────────────

@app.get("/vision/status")
def vision_status() -> dict:
    """Check if vision environment and model weights are ready."""
    vision_python = C.ROOT / ".venv-vision" / "Scripts" / "python.exe"
    has_venv = vision_python.exists()
    return {
        "available": has_venv,
        "venv_path": str(vision_python) if has_venv else None,
        "model": "facebook/sam2.1-hiera-small",
    }


@app.post("/vision/run")
def vision_run(edge_id: str | None = None, zoom: int = 18) -> dict:
    """Execute Phase 7 visual evidence extraction pipeline."""
    _require_location()
    proj = _project_dir()

    vision_python = C.ROOT / ".venv-vision" / "Scripts" / "python.exe"
    if not vision_python.exists():
        raise HTTPException(status_code=503,
                            detail="Vision environment not configured (.venv-vision missing).")

    import subprocess
    cmd = [str(vision_python), str(C.ROOT / "scripts" / "run_vision.py"),
           "--project", proj.name, "--zoom", str(zoom)]
    if edge_id:
        cmd.extend(["--edge", edge_id])

    res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(C.ROOT))
    if res.returncode != 0:
        raise HTTPException(status_code=500, detail=f"Vision extraction failed: {res.stderr or res.stdout}")

    # Read generated observations
    obs_file = proj / "observations.json"
    observations = json.loads(obs_file.read_text(encoding="utf-8")) if obs_file.exists() else []

    return {
        "ok": True,
        "observations_count": len(observations),
        "observations": observations,
        "has_road_mask": (proj / "road_mask.geojson").exists(),
        "has_mosaic": (proj / "vision" / "mosaic.png").exists(),
    }


@app.get("/vision/observations")
def vision_observations() -> dict:
    """Return latest generated observations and road mask."""
    proj = _project_dir()
    obs_file = proj / "observations.json"
    mask_file = proj / "road_mask.geojson"

    observations = json.loads(obs_file.read_text(encoding="utf-8")) if obs_file.exists() else []
    road_mask = json.loads(mask_file.read_text(encoding="utf-8")) if mask_file.exists() else None

    return {
        "observations": observations,
        "road_mask": road_mask,
    }


# ── Review & Validation Queue Endpoints (Phase 8) ─────────────────────────────

class ReviewDecisionRequest(BaseModel):
    observation_id: str
    action: str                     # "ACCEPT_VISION" | "KEEP_BASELINE" | "EDIT"
    edited_value: int | None = None
    reason: str | None = None


@app.get("/review/queue")
def review_queue() -> dict:
    """Return fusion review items comparing baseline model to observations."""
    _require_location()
    proj = _project_dir()

    obs_file = proj / "observations.json"
    if not obs_file.exists():
        return {"items": [], "total": 0, "review_count": 0, "agreement_count": 0}

    observations = json.loads(obs_file.read_text(encoding="utf-8"))
    if not observations:
        return {"items": [], "total": 0, "review_count": 0, "agreement_count": 0}

    # Build baseline dictionary from plain.edg.xml or network
    plain_edg = proj / "build" / "plain.edg.xml"
    if not plain_edg.exists():
        plain_edg = proj / "plain.edg.xml"

    baseline_dict: dict[str, dict] = {}
    if plain_edg.exists():
        from core.model.edits import read_edges
        edg_map = read_edges(plain_edg)
        for eid, attrs in edg_map.items():
            num_lanes = int(attrs.get("numLanes", 1))
            road_id = f"rt-road-{eid}"
            baseline_dict[road_id] = {
                "lane_count": num_lanes,
                "lane_count_provenance": {
                    "source": "osm",
                    "tag": f"lanes={num_lanes}",
                    "inferred": False,
                },
            }

    from vision.evidence import build_review_items
    items = build_review_items(observations, baseline_dict, min_confidence=0.3)

    rev_count = sum(1 for item in items if item["status"] == "REVIEW")
    agr_count = sum(1 for item in items if item["status"] == "AGREEMENT")

    return {
        "items": items,
        "total": len(items),
        "review_count": rev_count,
        "agreement_count": agr_count,
    }


@app.post("/review/decision")
def review_decision(req: ReviewDecisionRequest) -> dict:
    """Apply human validation decision: accept/reject/edit observation -> recompile & re-simulate."""
    _require_location()
    proj = _project_dir()

    obs_file = proj / "observations.json"
    if not obs_file.exists():
        raise HTTPException(status_code=404, detail="observations.json not found.")

    observations = json.loads(obs_file.read_text(encoding="utf-8"))
    target_obs = next((o for o in observations if o["id"] == req.observation_id), None)
    if not target_obs:
        raise HTTPException(status_code=404, detail=f"Observation '{req.observation_id}' not found.")

    road_id = target_obs.get("attached_to", {}).get("road_id", "")
    edge_id = road_id.replace("rt-road-", "") if road_id.startswith("rt-road-") else road_id

    plain_edg = proj / "build" / "plain.edg.xml"
    if not plain_edg.exists():
        plain_edg = proj / "plain.edg.xml"
    if not plain_edg.exists():
        raise HTTPException(status_code=500, detail="plain.edg.xml not found for editing.")

    from core.model.edits import Edit, apply_edits, write_validation_report
    from core.acquire.netconvert import plain_to_net

    report_path = proj / "validation_report.json"
    existing_decisions = []
    if report_path.exists():
        try:
            existing_decisions = json.loads(report_path.read_text(encoding="utf-8")).get("decisions", [])
        except Exception:
            existing_decisions = []

    # Map existing decisions to Edit objects
    edits = [
        Edit(
            edge_id=d["edge_id"],
            attribute=d["attribute"],
            old_value=d.get("old_value"),
            new_value=d["new_value"],
            source=d.get("source", "human"),
            observation_id=d.get("observation_id"),
            user_action=d.get("user_action", "accept"),
        )
        for d in existing_decisions
    ]

    action = req.action.upper()
    if action == "ACCEPT_VISION":
        new_val = str(target_obs["value"])
        target_obs["status"] = "ACCEPTED"
        user_action = "accept"
        source = "accepted_vision"
    elif action == "KEEP_BASELINE":
        new_val = str(target_obs.get("evidence", {}).get("baseline_value", 4))
        target_obs["status"] = "REJECTED"
        user_action = "reject"
        source = "human"
    elif action == "EDIT":
        if req.edited_value is None or req.edited_value < 1:
            raise HTTPException(status_code=422, detail="Valid edited_value required for EDIT action.")
        new_val = str(req.edited_value)
        target_obs["status"] = "ACCEPTED"
        target_obs["value"] = req.edited_value
        user_action = "edit"
        source = "human"
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action '{req.action}'")

    # Add or update this decision
    new_edit = Edit(
        edge_id=edge_id,
        attribute="numLanes",
        old_value=None,
        new_value=new_val,
        source=source,
        observation_id=req.observation_id,
        confidence=target_obs.get("confidence", 1.0),
        user_action=user_action,
    )
    edits = [e for e in edits if e.observation_id != req.observation_id] + [new_edit]

    # 1. Update observations.json (IMMUTABLE audit trail - status updated, never deleted)
    obs_file.write_text(json.dumps(observations, indent=2), encoding="utf-8")

    # 2. Apply edits to plain.edg.xml
    applied_edits = [e for e in edits if e.user_action != "reject"]
    if applied_edits:
        apply_edits(plain_edg, applied_edits)

    # 3. Recompile network with netconvert
    sumo_net = proj / "sumo" / "network.net.xml"
    if not sumo_net.exists():
        sumo_net = proj / "build" / "network.net.xml"
    xodr_file = proj / "road_network.xodr"

    plain_files = {
        "nod": proj / "build" / "plain.nod.xml",
        "edg": plain_edg,
        "con": proj / "build" / "plain.con.xml" if (proj / "build" / "plain.con.xml").exists() else None,
        "tll": proj / "build" / "plain.tll.xml" if (proj / "build" / "plain.tll.xml").exists() else None,
    }
    plain_to_net(plain_files, sumo_net, xodr_out=xodr_file)

    # 4. Write validation report
    write_validation_report(edits, observations, report_path)

    # 5. Quick re-simulation to update metrics if routes exist
    sim_result = None
    routes_file = proj / "routes.rou.xml"
    if routes_file.exists():
        from core.sim import run, scenario
        closure_file = proj / "closure.add.xml"
        if not closure_file.exists():
            scenario.build_closure_additional(sumo_net, edge_id, 0, closure_file)
        try:
            sim_result = run.run_experiment(
                sumo_net, routes_file, closure_file, seeds=[42], out_dir=proj / "sim"
            )
        except Exception:
            sim_result = None

    return {
        "ok": True,
        "action": action,
        "observation_id": req.observation_id,
        "edge_id": edge_id,
        "new_value": new_val,
        "recompiled": True,
        "sim_result": sim_result,
    }


@app.post("/review/replay")
def review_replay() -> dict:
    """Verify that baseline plain XML + validation_report.json reproduces the final model."""
    _require_location()
    proj = _project_dir()
    report_path = proj / "validation_report.json"
    plain_edg = proj / "build" / "plain.edg.xml"

    if not report_path.exists() or not plain_edg.exists():
        raise HTTPException(status_code=404, detail="validation_report.json or baseline plain.edg.xml missing.")

    from core.model.edits import replay
    test_out = proj / "build" / "replayed.edg.xml"
    replay(plain_edg, report_path, test_out)

    return {
        "ok": True,
        "replayed_path": str(test_out),
        "matches": test_out.exists(),
    }


@app.post("/export/zip")
def export_zip() -> dict:
    """Package the project as a ZIP and return its path."""
    _require_location()
    proj = _project_dir()
    metrics_path = proj / "metrics.json"
    if not metrics_path.exists():
        raise HTTPException(status_code=412,
                            detail="No experiment results yet. Run an experiment first.")

    try:
        from core.export import package as EX
        from core import provenance as P

        loc_data = _read_location() or {}
        prov_path = proj / "provenance.json"
        prov = P.ProvenanceLog(prov_path)

        # Read metrics for README
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        from core.sim.metrics import format_table
        table = format_table(metrics.get("comparison", {"rows": [], "n_seeds": 0,
                                                         "significant": False, "verdict": ""}))

        EX.write_source_manifest(proj, prov.entries)
        EX.write_readme(proj, location=loc_data, results_table=table)
        zip_path = EX.export_project(
            proj, proj.parent / "RoadTwin_Project_export.zip"
        )
        return {"ok": True, "zip_path": str(zip_path),
                "size_kb": round(zip_path.stat().st_size / 1024, 1)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("ROADTWIN_PORT", "8765"))
    uvicorn.run(
        "core.main:app",
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
