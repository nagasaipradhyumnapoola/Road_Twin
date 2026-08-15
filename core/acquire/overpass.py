"""OSM acquisition via Overpass.

Why not OSMnx: OSMnx drags in GeoPandas + NetworkX, which are the two worst
libraries to freeze with PyInstaller, and it hands back a graph object when
what netconvert actually wants is raw .osm XML. Thirty lines of `requests`
gives us exactly the right artifact with none of the packaging pain.

Keep OSMnx in the notebook environment if you want it for exploration.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

import requests

QUERY_TEMPLATE = """
[out:xml][timeout:{timeout}];
(
  way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|unclassified|residential|service)$"]
     ({south},{west},{north},{east});
  >;
);
out body;
"""


def bbox_from_point(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    """Return (south, west, north, east) for a square AOI around a point.

    Good enough at city scale; we are defining a query window, not doing geodesy.
    """
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * max(math.cos(math.radians(lat)), 1e-6))
    return (lat - dlat, lon - dlon, lat + dlat, lon + dlon)


def _cache_key(bbox: tuple[float, float, float, float]) -> str:
    return hashlib.sha256(("%.6f,%.6f,%.6f,%.6f" % bbox).encode()).hexdigest()[:16]


def fetch_osm(
    bbox: tuple[float, float, float, float],
    out_path: str | Path,
    *,
    endpoint: str,
    user_agent: str,
    timeout_s: int = 90,
    cache_dir: str | Path | None = None,
    allow_network: bool = True,
) -> Path:
    """Download the OSM extract for `bbox` and write it to `out_path`.

    Caching is not an optimisation here, it is DEMO INSURANCE. Overpass
    rate-limits, and venue wifi fails. Commit the cached file to the repo.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cached = None
    if cache_dir:
        cached = Path(cache_dir) / f"osm_{_cache_key(bbox)}.osm"
        if cached.exists() and cached.stat().st_size > 0:
            out_path.write_bytes(cached.read_bytes())
            print(f"[overpass] cache hit -> {cached.name}")
            return out_path

    if not allow_network:
        raise RuntimeError(
            "No cached OSM for this bbox and network is disabled. "
            "Run once with network access to populate assets/benchmark/."
        )

    south, west, north, east = bbox
    query = QUERY_TEMPLATE.format(
        timeout=timeout_s, south=south, west=west, north=north, east=east
    )
    print(f"[overpass] querying bbox=({south:.5f},{west:.5f},{north:.5f},{east:.5f})")
    resp = requests.post(
        endpoint,
        data={"data": query},
        headers={"User-Agent": user_agent},
        timeout=timeout_s + 30,
    )
    resp.raise_for_status()
    if b"<osm" not in resp.content[:2000]:
        raise RuntimeError(f"Overpass did not return OSM XML: {resp.text[:300]}")

    out_path.write_bytes(resp.content)
    if cached:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(resp.content)
    print(f"[overpass] wrote {out_path} ({out_path.stat().st_size/1024:.0f} KB)")
    return out_path
