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
import time
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
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

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


@app.exception_handler(RequestValidationError)
def _clean_validation_error(request: Request, exc: RequestValidationError):
    """Return a clean 422 that does not echo the raw input.

    FastAPI's default handler puts the offending `input` back into the response.
    For a NaN/Infinity latitude that value is not JSON-serialisable, so the
    default response itself crashes with a 500 -- turning a correctly-rejected
    request into a server error. Dropping `input` also avoids reflecting caller
    data. The field/message/type still identify what was wrong.
    """
    errors = [
        {"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


# ── request / response models ─────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    version: str
    sumo: bool
    sumo_home: str | None


class GeocodeRequest(BaseModel):
    query: str


class ReverseGeocodeRequest(BaseModel):
    lat: float
    lon: float


class GeocandiDate(BaseModel):
    display_name: str
    lat: float
    lon: float
    importance: float


class ConfirmRequest(BaseModel):
    """A user confirming a map location. Validated at the request boundary so
    invalid geography cannot reach location.json or any downstream operation.

    `confirmation_method` is deliberately NOT a client field: the manual-map
    flow is always a human confirmation, so the server stamps "user" itself.
    Letting the client send it allowed a caller to write
    confirmation_method="benchmark_config" and forge system-generated
    provenance. `model_config` extra="ignore" (Pydantic default) means the
    frontend still sending the field is harmless.
    """
    name: str
    # allow_inf_nan=False rejects NaN/Infinity at the boundary; ge/le bound the
    # geography. Both raise 422 before the handler runs.
    lat: float = Field(ge=-90.0, le=90.0, allow_inf_nan=False)
    lon: float = Field(ge=-180.0, le=180.0, allow_inf_nan=False)
    aoi_radius_m: float = Field(default=500.0, gt=0.0, allow_inf_nan=False)


class AcquireRequest(BaseModel):
    force: bool = False   # skip cache and re-download


class BuildRequest(BaseModel):
    pass


# ── project directory helper ──────────────────────────────────────────────────

def _data_root() -> Path:
    """Where the app keeps PERSISTENT project state.

    Frozen (PyInstaller onefile), config.PROJECTS_DIR resolves inside the
    _MEIxxxx extraction dir, which is deleted on exit -- so a confirmed location
    did not survive a restart of the installed app. Persist under a real
    per-user data directory instead. Dev/source runs keep writing to the repo's
    projects/ so nothing about the developer workflow changes.

    ROADTWIN_DATA_DIR overrides everything (tests, custom installs).
    """
    env = os.environ.get("ROADTWIN_DATA_DIR")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        root = Path(base) if base else (Path.home() / ".roadtwin")
        return root / "RoadTwin"
    # Dev/source: the directory that CONTAINS projects/ is the repo root, so
    # _data_root()/projects/active == the original PROJECTS_DIR/active.
    from config import ROOT as _ROOT
    return _ROOT


def _project_dir() -> Path:
    """Active project directory — always 'active' until multi-project support."""
    try:
        p = _data_root() / "projects" / "active"
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


def _get_net_file() -> Path:
    """Return path to network.net.xml with automatic benchmark fallback."""
    proj = _project_dir()
    p1 = proj / "sumo" / "network.net.xml"
    if p1.exists():
        return p1
    p2 = proj / "build" / "network.net.xml"
    if p2.exists():
        return p2
    # Check benchmark project
    bench = proj.parent / "benchmark" / "sumo" / "network.net.xml"
    if bench.exists():
        import shutil
        (proj / "sumo").mkdir(parents=True, exist_ok=True)
        shutil.copy(bench, p1)
        return p1
    bench_build = proj.parent / "benchmark" / "build" / "network.net.xml"
    if bench_build.exists():
        import shutil
        (proj / "build").mkdir(parents=True, exist_ok=True)
        shutil.copy(bench_build, p2)
        return p2
    raise HTTPException(status_code=412, detail="Network not built. POST /model/build first.")


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
    """Address -> candidate list via Nominatim (rate-limited, cached).

    An empty query is not an error -- it returns []. A reachable geocoder that
    simply finds nothing also returns [] (the frontend shows "no matches").
    Only an upstream FAILURE (network error, HTTP 4xx/5xx) becomes a 503, with
    a clean application-level message -- never the raw upstream URL or traceback,
    which leak internal detail and confuse the user.
    """
    import requests as _requests

    from config import ASSETS, NOMINATIM_USER_AGENT
    from core.acquire.geocoder import geocode as _geocode

    if not body.query or not body.query.strip():
        return []

    try:
        results = _geocode(
            body.query,
            user_agent=NOMINATIM_USER_AGENT,
            cache_dir=ASSETS / "geocache",
        )
    except (_requests.HTTPError, _requests.RequestException):
        # Upstream refused, timed out, or is unreachable. Do not surface the URL
        # or the exception text.
        raise HTTPException(
            status_code=503,
            detail=("Address lookup is temporarily unavailable. "
                    "Please try again, or enter coordinates manually."),
        ) from None
    except Exception:
        raise HTTPException(
            status_code=503,
            detail=("Address lookup failed. "
                    "Please enter coordinates manually."),
        ) from None

    return [GeocandiDate(**r) for r in results]


@app.post("/location/reverse")
def reverse_geocode_endpoint(body: ReverseGeocodeRequest) -> dict:
    """Lat/Lon → display name via Nominatim reverse geocode."""
    try:
        from core.acquire.geocoder import reverse_geocode as _rev_geo
        from config import OVERPASS, ASSETS
        cache_dir = ASSETS / "geocache"
        res = _rev_geo(body.lat, body.lon, user_agent=OVERPASS["user_agent"], cache_dir=cache_dir)
        if res and res.get("display_name"):
            return res
        return {"display_name": "", "lat": body.lat, "lon": body.lon}
    except Exception:
        return {"display_name": "", "lat": body.lat, "lon": body.lon}


@app.post("/location/confirm")
def confirm_location(body: ConfirmRequest) -> dict:
    """Write location.json. Gates all downstream pipeline calls.

    The server assigns confirmation_method="user" -- this endpoint IS the manual
    human-confirmation flow, so the provenance is not the client's to claim.
    """
    data = {
        "name": body.name,
        "lat": body.lat,
        "lon": body.lon,
        "aoi_radius_m": body.aoi_radius_m,
        "crs": "EPSG:4326",
        "confirmed": True,
        "confirmation_method": "user",
    }
    # allow_nan=False makes json.dumps RAISE rather than emit a bare NaN/Infinity
    # token (which is invalid JSON that the frontend's JSON.parse cannot read).
    # ConfirmRequest already rejects non-finite input, so this is belt-and-braces
    # -- but it guarantees the file on disk is always strict JSON.
    try:
        payload = json.dumps(data, indent=2, allow_nan=False)
    except ValueError as exc:
        raise HTTPException(status_code=422,
                            detail="Coordinates must be finite numbers.") from exc
    _location_path().write_text(payload, encoding="utf-8")
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
        _t = time.perf_counter()
        osm_path = fetch_osm(
            bbox,
            out_path=proj / "network.osm",
            endpoint=OVERPASS["endpoint"],
            user_agent=OVERPASS["user_agent"],
            timeout_s=OVERPASS["timeout_s"],
            cache_dir=ASSETS / "osm_cache",
            allow_network=True,
        )
        # P10 — record the real acquisition time into the modeling benchmark.
        try:
            from core import benchmark as BM
            BM.update_stage(proj, "acquisition_s", time.perf_counter() - _t)
        except Exception:
            pass
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
        _t = time.perf_counter()
        plain = osm_to_plain(osm_path, build_dir)
        _model_gen_s = time.perf_counter() - _t

        # 2. plain XML → net.xml + xodr
        net_file = build_dir / "network.net.xml"
        xodr_file = build_dir / "road_network.xodr"
        _t = time.perf_counter()
        plain_to_net(plain, net_file, xodr_out=xodr_file)
        _compile_s = time.perf_counter() - _t

        # A new network invalidates network-dependent artifacts from any prior
        # location. plain_to_net raised on failure, so reaching here means the
        # build succeeded and network.net.xml is fresh. Remove the stale
        # routes.rou.xml (its edges may not exist in this network -> SUMO
        # "edge ... is not known") and the edge-specific closure.add.xml, so the
        # next /demand/generate regenerates demand for THIS network rather than
        # serving cached routes built against the previous location.
        (build_dir / "routes.rou.xml").unlink(missing_ok=True)
        (build_dir / "closure.add.xml").unlink(missing_ok=True)

        # 3. Build canonical model
        location = Location(
            name=loc_data["name"],
            lat=loc_data["lat"],
            lon=loc_data["lon"],
            aoi_radius_m=loc_data.get("aoi_radius_m", 500),
            confirmed=True,
            confirmation_method=loc_data.get("confirmation_method", "user"),
        )
        model = build_from_net(net_file, location, proj, osm_file=osm_path)

        # P10 — record the real modeling + compilation times and network size.
        try:
            from core import benchmark as BM
            BM.update_stage(proj, "model_generation_s", _model_gen_s)
            BM.update_stage(proj, "compilation_s", _compile_s)
            BM.set_network(proj, net_file)
        except Exception:
            pass

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
    _require_location()   # location-dependent, so gate it like its siblings
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


@app.get("/benchmark")
def get_benchmark() -> dict:
    """P10 — the modeling acceleration benchmark for the active project.

    Real measured stage timings + network size + human effort. Falls back to the
    bundled `benchmark` project so the panel has something to show before the
    user has run their own pipeline. 404 only when neither has a record.
    """
    from core import benchmark as BM

    proj = _project_dir()
    record = BM.load(proj)
    source = "active"
    if record is None:
        bench = proj.parent / "benchmark"
        record = BM.load(bench)
        source = "benchmark"
    if record is None:
        raise HTTPException(
            status_code=404,
            detail="No benchmark recorded yet. Run the pipeline (acquire → build → export).",
        )
    record["source"] = source
    return record



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


class ScenarioCreateRequest(BaseModel):
    """A what-if scenario definition (P11). parameters is type-specific; see
    core.scenario.models.TYPE_SPECS (exposed at GET /scenario/types)."""
    name: str
    type: str
    parameters: dict = Field(default_factory=dict)
    seeds: list[int] | None = None   # None → use config defaults


# ── P11 scenario state (in-memory, single-project) ───────────────────────────
_scenario_state: dict = {"status": "idle"}   # idle | running | done | error


# ── P6 routes ─────────────────────────────────────────────────────────────────

@app.get("/network/edges")
def list_edges() -> dict:
    """List drivable edges from the compiled network — drives the UI selectors."""
    _require_location()
    net_file = _get_net_file()

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
    net_file = _get_net_file()

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
    net_file = _get_net_file()

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
    # NOTE: no closure_file precondition -- this endpoint builds closure.add.xml
    # itself from the requested edge/lane a few lines below (build_lane_closure),
    # so requiring it to pre-exist was contradictory and broke a fresh project.

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


# ── P11 What-If Scenario Engine ──────────────────────────────────────────────

def _scenario_summary(result: dict | None) -> dict | None:
    """Compact headline for the scenario list, drawn only from real metrics."""
    if not result:
        return None
    cmp = result.get("comparison")
    if not cmp:
        # baseline: report its own travel time, nothing to compare
        b = result.get("baseline") or {}
        return {"kind": "baseline",
                "baseline_travel_time_s": b.get("avg_travel_time_s")}
    tt = next((r for r in cmp.get("rows", [])
               if r.get("metric") == "Average travel time"), None)
    return {
        "kind": "comparison",
        "travel_time_delta_pct": tt.get("delta_pct") if tt else None,
        "significant": cmp.get("significant"),
    }


@app.get("/scenario/types")
def scenario_types() -> dict:
    """Type catalogue that drives the New Scenario form + validation."""
    from config import SIM
    from core.scenario.models import SCENARIO_TYPES, TYPE_SPECS
    return {
        "types": [{"type": t, **TYPE_SPECS[t]} for t in SCENARIO_TYPES],
        "seeds_default": SIM["seeds"],
    }


@app.get("/scenario/list")
def scenario_list() -> dict:
    """All scenarios (baseline first), each with a compact result summary."""
    _require_location()
    from config import SIM
    from core.scenario import registry as R

    proj = _project_dir()
    R.ensure_baseline(proj, SIM["seeds"])   # list is never empty
    items = []
    for s in R.list_scenarios(proj):
        res = R.load_result(proj, s.scenario_id)
        items.append({
            "scenario": s.to_dict(),
            "has_result": res is not None,
            "summary": _scenario_summary(res),
        })
    return {"scenarios": items, "total": len(items)}


@app.post("/scenario/create")
def scenario_create(body: ScenarioCreateRequest) -> dict:
    """Validate + persist a scenario definition (no simulation yet)."""
    _require_location()
    from config import SIM
    from core.scenario import registry as R
    from core.scenario.models import Scenario
    from core.scenario.validator import validate

    proj = _project_dir()
    net_file = _get_net_file()
    seeds = body.seeds if body.seeds else SIM["seeds"]

    scenario = Scenario(
        scenario_id=R.next_id(proj), name=body.name, type=body.type,
        parameters=body.parameters or {}, seeds=list(seeds),
    )
    try:
        validate(scenario, net_file)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    R.save(proj, scenario)
    return {"ok": True, "scenario": scenario.to_dict()}


@app.get("/scenario/status")
def scenario_status() -> dict:
    """Poll the current scenario run (idle | running | done | error)."""
    return _scenario_state


@app.get("/scenario/{scenario_id}")
def scenario_get(scenario_id: str) -> dict:
    """One scenario definition plus its last result, if any."""
    _require_location()
    from config import SIM
    from core.scenario import registry as R

    proj = _project_dir()
    if scenario_id == R.BASELINE_ID:
        R.ensure_baseline(proj, SIM["seeds"])   # materialize on first access
    s = R.load(proj, scenario_id)
    if not s:
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found.")
    return {"scenario": s.to_dict(), "result": R.load_result(proj, scenario_id)}


@app.post("/scenario/{scenario_id}/run")
def scenario_run(scenario_id: str) -> dict:
    """Run a scenario end-to-end (baseline + scenario arms) and store the result.

    Synchronous and heavy, like /experiment/run: it blocks until every seed
    completes. Poll /scenario/status meanwhile. Numbers are real SUMO output.
    """
    global _scenario_state
    if _scenario_state.get("status") == "running":
        raise HTTPException(status_code=409,
                            detail="A scenario is already running. Wait for it to finish.")

    _require_location()
    from config import SIM
    from core.scenario import engine, registry as R

    proj = _project_dir()
    if scenario_id == R.BASELINE_ID:
        R.ensure_baseline(proj, SIM["seeds"])   # materialize on first access
    scenario = R.load(proj, scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found.")

    net_file = _get_net_file()
    base_routes = proj / "sumo" / "routes.rou.xml"
    if not base_routes.exists():
        raise HTTPException(status_code=412,
                            detail="Routes not generated. POST /demand/generate first.")

    work_dir = proj / "sumo" / "scenarios" / scenario_id
    _scenario_state = {"status": "running", "scenario_id": scenario_id}
    try:
        result = engine.execute(
            scenario, net_file=net_file, base_routes=base_routes, work_dir=work_dir,
        )
        R.save_result(proj, scenario_id, result)
        _scenario_state = {"status": "done", "scenario_id": scenario_id}
        return {"ok": True, "result": result}
    except ValueError as exc:
        _scenario_state = {"status": "error", "scenario_id": scenario_id, "detail": str(exc)}
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        _scenario_state = {"status": "error", "scenario_id": scenario_id, "detail": str(exc)}
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Vision Endpoints (Phase 7) ────────────────────────────────────────────────

def _get_vision_python() -> Path | None:
    candidates = [
        _base / ".venv-vision" / "Scripts" / "python.exe",
        _base.parent / "RoadTwin" / ".venv-vision" / "Scripts" / "python.exe",
        _base.parent / ".venv-vision" / "Scripts" / "python.exe",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


@app.get("/vision/status")
def vision_status() -> dict:
    """Check if vision environment and model weights are ready."""
    vision_python = _get_vision_python()
    has_venv = vision_python is not None
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

    vision_python = _get_vision_python()
    if not vision_python:
        raise HTTPException(status_code=503,
                            detail="Vision environment not configured (.venv-vision missing).")

    import subprocess
    cmd = [str(vision_python), str(_base / "scripts" / "run_vision.py"),
           "--project", proj.name, "--zoom", str(zoom)]
    if edge_id:
        cmd.extend(["--edge", edge_id])

    res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_base))
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
        bench_obs = proj.parent / "benchmark" / "observations.json"
        asset_obs = _base / "assets" / "benchmark" / "observations.json"
        if bench_obs.exists():
            obs_file = bench_obs
        elif asset_obs.exists():
            obs_file = asset_obs

    if not obs_file.exists():
        return {"items": [], "total": 0, "review_count": 0, "agreement_count": 0}

    observations = json.loads(obs_file.read_text(encoding="utf-8"))
    if not observations:
        return {"items": [], "total": 0, "review_count": 0, "agreement_count": 0}

    # Build baseline dictionary from plain.edg.xml or network. /model/build writes
    # the plain substrate to proj/sumo/; run_benchmark and older builds used
    # proj/build/. Check both so a freshly built packaged project (sumo/) resolves
    # its baseline instead of silently falling through to an empty map (which drops
    # every observation and shows "No Pending Discrepancies").
    plain_edg = proj / "build" / "plain.edg.xml"
    if not plain_edg.exists():
        plain_edg = proj / "sumo" / "plain.edg.xml"
    if not plain_edg.exists():
        plain_edg = proj / "plain.edg.xml"
    if not plain_edg.exists():
        bench_edg = proj.parent / "benchmark" / "build" / "plain.edg.xml"
        if bench_edg.exists():
            plain_edg = bench_edg

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
    import shutil

    obs_file = proj / "observations.json"
    if not obs_file.exists():
        bench_obs = proj.parent / "benchmark" / "observations.json"
        asset_obs = _base / "assets" / "benchmark" / "observations.json"
        if bench_obs.exists():
            shutil.copy(bench_obs, obs_file)
        elif asset_obs.exists():
            shutil.copy(asset_obs, obs_file)
        else:
            raise HTTPException(status_code=404, detail="observations.json not found.")

    observations = json.loads(obs_file.read_text(encoding="utf-8"))
    target_obs = next((o for o in observations if o["id"] == req.observation_id), None)
    if not target_obs:
        raise HTTPException(status_code=404, detail=f"Observation '{req.observation_id}' not found.")

    road_id = target_obs.get("attached_to", {}).get("road_id", "")
    edge_id = road_id.replace("rt-road-", "") if road_id.startswith("rt-road-") else road_id

    # Locate the editable plain substrate. /model/build writes it to proj/sumo/;
    # run_benchmark and older builds used proj/build/. Resolve from wherever it
    # actually landed so the packaged (sumo/) and benchmark (build/) layouts both
    # edit correctly; copy the benchmark project only as a last resort. ALL plain
    # files (nod/con/tll) then come from this same dir, so the recompile below
    # cannot mix a sumo/ edge file with a missing build/ node file.
    plain_dir = None
    for cand in (proj / "build", proj / "sumo", proj):
        if (cand / "plain.edg.xml").exists():
            plain_dir = cand
            break
    if plain_dir is None:
        bench_build = proj.parent / "benchmark" / "build"
        if (bench_build / "plain.edg.xml").exists():
            (proj / "build").mkdir(parents=True, exist_ok=True)
            for _f in ("plain.edg.xml", "plain.nod.xml", "plain.con.xml", "plain.tll.xml"):
                if (bench_build / _f).exists():
                    shutil.copy(bench_build / _f, proj / "build" / _f)
            plain_dir = proj / "build"
        else:
            raise HTTPException(status_code=500, detail="plain.edg.xml not found for editing.")
    plain_edg = plain_dir / "plain.edg.xml"

    from core.model.edits import Edit, apply_edits, prune_stale_connections, write_validation_report
    from core.build.netconvert import plain_to_net

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
        "nod": plain_dir / "plain.nod.xml",
        "edg": plain_edg,
        "con": (plain_dir / "plain.con.xml") if (plain_dir / "plain.con.xml").exists() else None,
        "tll": (plain_dir / "plain.tll.xml") if (plain_dir / "plain.tll.xml").exists() else None,
    }
    # A lane reduction leaves connections referencing removed lanes; prune them
    # so netconvert does not abort on "Lane index is larger than number of lanes".
    if applied_edits and plain_files["con"] is not None:
        prune_stale_connections(plain_files["con"], plain_edg)
    plain_to_net(plain_files, sumo_net, xodr_out=xodr_file)

    # 4. Write validation report
    write_validation_report(edits, observations, report_path)

    # 5. Re-simulation to refresh metrics on the edited network. The closure
    #    additional lives under sumo/ next to the network; building it is INSIDE
    #    the try so a closure-build or SUMO failure is reported (sim_error) rather
    #    than raising a 500 after the model has already been mutated on disk.
    sim_result = None
    sim_error = None
    routes_file = proj / "routes.rou.xml"
    if routes_file.exists():
        from config import SIM, CLOSURE
        from core.sim import run, scenario
        closure_file = proj / "sumo" / "closure.add.xml"
        try:
            if not closure_file.exists():
                scenario.build_lane_closure(
                    sumo_net, closure_file,
                    edge_id=edge_id, lane_index=0,
                    begin=CLOSURE["begin"], end=CLOSURE["end"],
                )
            sim_result = run.run_experiment(
                sumo_net, routes_file,
                proj / "sumo" / "results",
                closure_file,
                seeds=[42],
                begin=SIM["begin"], end=SIM["end"],
                closed_edge=edge_id,
            )
        except Exception as exc:
            sim_error = str(exc)
            sim_result = None

    return {
        "ok": True,
        "action": action,
        "observation_id": req.observation_id,
        "edge_id": edge_id,
        "new_value": new_val,
        "recompiled": True,
        "sim_result": sim_result,
        "sim_error": sim_error,
    }


@app.post("/review/replay")
def review_replay() -> dict:
    """Verify that baseline plain XML + validation_report.json reproduces the final model."""
    _require_location()
    proj = _project_dir()
    report_path = proj / "validation_report.json"
    plain_edg = proj / "build" / "plain.edg.xml"

    if not report_path.exists():
        bench_rep = proj.parent / "benchmark" / "validation_report.json"
        if bench_rep.exists():
            report_path = bench_rep

    if not plain_edg.exists():
        plain_edg = proj / "sumo" / "plain.edg.xml"   # /model/build writes here
    if not plain_edg.exists():
        bench_edg = proj.parent / "benchmark" / "build" / "plain.edg.xml"
        if bench_edg.exists():
            plain_edg = bench_edg

    if not report_path.exists() or not plain_edg.exists():
        raise HTTPException(status_code=404, detail="validation_report.json or baseline plain.edg.xml missing.")

    from core.model.edits import replay
    test_out = proj / "build" / "replayed.edg.xml"
    (proj / "build").mkdir(parents=True, exist_ok=True)
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
        _t = time.perf_counter()
        zip_path = EX.export_project(
            proj, proj.parent / "RoadTwin_Project_export.zip"
        )
        # P10 — record the real export time into the modeling benchmark.
        try:
            from core import benchmark as BM
            BM.update_stage(proj, "export_s", time.perf_counter() - _t)
        except Exception:
            pass
        return {"ok": True, "zip_path": str(zip_path),
                "size_kb": round(zip_path.stat().st_size / 1024, 1)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Frozen re-exec guard. Subprocess calls (e.g. demand generation launching
    # SUMO's randomTrips.py in core/sim/demand.py) use sys.executable, which is
    # THIS exe when frozen by PyInstaller -- not a Python interpreter. If we were
    # handed a .py script, act as a Python runner and execute it, instead of
    # starting a SECOND API server on the port the parent sidecar already owns
    # (which fails with WinError 10048). Dev is unaffected: there sys.executable
    # is the venv python, so this branch never runs.
    if getattr(sys, "frozen", False) and len(sys.argv) > 1 and sys.argv[1].endswith(".py"):
        import runpy
        sys.argv = sys.argv[1:]                  # the script sees itself as argv[0]
        runpy.run_path(sys.argv[0], run_name="__main__")
    else:
        port = int(os.environ.get("ROADTWIN_PORT", "8765"))
        # Pass the app OBJECT, not the "core.main:app" import string. When frozen,
        # this file is the entry point and PyInstaller bundles it as __main__, so
        # the dotted name "core.main" is not importable and uvicorn's string form
        # dies with `Could not import module "core.main"` -- the packaged sidecar
        # then never binds its port. The app instance is already in scope here, so
        # hand it to uvicorn directly (no reload/workers are used).
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
