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

    _rate_limit()
    resp = requests.get(
        _NOMINATIM_URL,
        params={
            "q": query,
            "format": "jsonv2",
            "limit": 5,
            "addressdetails": 0,
        },
        headers={"User-Agent": user_agent},
        timeout=15,
    )
    resp.raise_for_status()
    raw: list[dict] = resp.json()

    results = [
        {
            "display_name": r.get("display_name", ""),
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
            "importance": float(r.get("importance", 0.0)),
        }
        for r in raw
    ]

    if cache_dir:
        hit.write_text(json.dumps(results))

    return results
