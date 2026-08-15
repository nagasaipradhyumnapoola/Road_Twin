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


# Public Overpass mirrors tried in order when the primary is rate-limited.
_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",   # CDN mirror — often succeeds when primary 504s
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]


def _try_mirrors(query: str, primary: str, user_agent: str, timeout_s: int) -> bytes:
    """POST to primary; on 4xx/timeout fall through mirrors in order."""
    candidates = [primary] + [m for m in _MIRRORS if m != primary]
    last_err: Exception | None = None
    for url in candidates:
        try:
            resp = requests.post(
                url,
                data={"data": query},
                headers={"User-Agent": user_agent},
                timeout=timeout_s + 30,
            )
            if resp.status_code == 200 and b"<osm" in resp.content[:2000]:
                print(f"[overpass] success via {url}")
                return resp.content
            print(f"[overpass] {url} => {resp.status_code}, trying next mirror")
            last_err = Exception(f"HTTP {resp.status_code}")
        except Exception as exc:
            print(f"[overpass] {url} error: {exc}, trying next mirror")
            last_err = exc
    raise RuntimeError(
        f"All Overpass mirrors failed. Last error: {last_err}\n"
        "Commit a cached .osm file or try again later."
    )


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
    content = _try_mirrors(query, endpoint, user_agent, timeout_s)

    out_path.write_bytes(content)
    if cached:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(content)
    print(f"[overpass] wrote {out_path} ({out_path.stat().st_size/1024:.0f} KB)")
    return out_path
