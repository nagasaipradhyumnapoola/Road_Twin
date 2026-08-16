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


# ── entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("ROADTWIN_PORT", "8765"))
    uvicorn.run(
        "core.main:app",
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
