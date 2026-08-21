"""Nominatim geocoder adapter.

One public endpoint, real User-Agent, 1 req/s rate-limit, file cache.
Mirrors the pattern from overpass.py: thin requests wrapper, no heavy deps.
"""
from __future__ import annotations

import json
import time
import hashlib
from pathlib import Path
from typing import Any

import requests

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_LAST_CALL: float = 0.0          # module-level rate-limit state


def _rate_limit() -> None:
    """Enforce 1 request/second per Nominatim usage policy."""
    global _LAST_CALL
    elapsed = time.monotonic() - _LAST_CALL
    if elapsed < 1.05:
        time.sleep(1.05 - elapsed)
    _LAST_CALL = time.monotonic()


def _cache_key(query: str) -> str:
    return hashlib.sha256(query.lower().strip().encode()).hexdigest()[:16]


def geocode(
    query: str,
    *,
    user_agent: str,
    cache_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Search Nominatim for `query`.

    Returns a list of candidate dicts, each with keys:
        display_name, lat (float), lon (float), importance (float)

    At most 5 results. Empty list if not found.
    Cache hit skips the network call.
    """
    if cache_dir:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        hit = cache_dir / f"geo_{_cache_key(query)}.json"
        if hit.exists():
            return json.loads(hit.read_text())

    try:
        resp = requests.get(
            _NOMINATIM_URL,
            params={
                "q": query,
                "format": "jsonv2",
                "limit": 5,
                "addressdetails": 0,
                "accept-language": "en",
            },
            headers={"User-Agent": user_agent, "Accept-Language": "en, en-US;q=0.9"},
            timeout=8,
        )
        resp.raise_for_status()
        raw: list[dict] = resp.json()
    except Exception as exc:
        # Graceful fallback: return empty list on network/timeout/rate-limit error
        print(f"[geocoder] Nominatim lookup failed for '{query}': {exc}")
        return []

    results = [
        {
            "display_name": r.get("display_name", ""),
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
            "importance": float(r.get("importance", 0.0)),
        }
        for r in raw
    ]

    if cache_dir and results:
        hit.write_text(json.dumps(results, indent=2))

    return results


_NOMINATIM_REV_URL = "https://nominatim.openstreetmap.org/reverse"


def reverse_geocode(
    lat: float,
    lon: float,
    *,
    user_agent: str,
    cache_dir: Path | None = None,
) -> dict[str, Any] | None:
    """Reverse geocode lat/lon into human readable display name."""
    if cache_dir:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        key = f"rev_{lat:.5f}_{lon:.5f}"
        hit = cache_dir / f"geo_{_cache_key(key)}.json"
        if hit.exists():
            try:
                data = json.loads(hit.read_text())
                if data.get("display_name"):
                    return data
            except Exception:
                pass

    _rate_limit()
    try:
        resp = requests.get(
            _NOMINATIM_REV_URL,
            params={
                "lat": lat,
                "lon": lon,
                "format": "jsonv2",
                "zoom": 18,
                "addressdetails": 1,
                "accept-language": "en",
            },
            headers={"User-Agent": user_agent, "Accept-Language": "en, en-US;q=0.9"},
            timeout=8,
        )
        resp.raise_for_status()
        raw: dict = resp.json()
        addr = raw.get("address", {})
        road = (
            addr.get("road")
            or addr.get("pedestrian")
            or addr.get("footway")
            or addr.get("street")
            or addr.get("highway")
            or raw.get("name")
        )
        locality = (
            addr.get("suburb")
            or addr.get("neighbourhood")
            or addr.get("residential")
            or addr.get("village")
            or addr.get("town")
            or addr.get("city_district")
            or addr.get("city")
            or addr.get("county")
        )

        if road and locality and road.lower() != locality.lower():
            short_name = f"{road}, {locality}"
        elif road:
            short_name = road
        elif raw.get("display_name"):
            parts = [p.strip() for p in raw["display_name"].split(",") if p.strip()]
            short_name = ", ".join(parts[:2]) if len(parts) >= 2 else raw["display_name"]
        else:
            short_name = None

        if not short_name:
            return None

        res = {"display_name": short_name, "full_name": raw.get("display_name", short_name), "lat": lat, "lon": lon}
        if cache_dir and short_name:
            hit.write_text(json.dumps(res, indent=2))
        return res
    except Exception as exc:
        print(f"[geocoder] Reverse geocode failed for {lat},{lon}: {exc}")
        return None
