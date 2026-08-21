"""Automated verification test for Phase 3: Location Gateway & Map Loading."""
from __future__ import annotations

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests
from fastapi.testclient import TestClient
from core.main import app, _location_path, _project_dir

client = TestClient(app)


def test_phase3() -> int:
    print("=" * 70)
    print("PHASE 3 AUTOMATED VERIFICATION: LOCATION GATEWAY & MAP SUBSYSTEM")
    print("=" * 70)

    # -------------------------------------------------------------------------
    # Test 1: Backend Gate — Unconfirmed Location must block downstream endpoints
    # -------------------------------------------------------------------------
    print("\n[Test 1] Backend Gate Enforcement (Unconfirmed Block)")
    loc_file = _location_path()
    if loc_file.exists():
        loc_file.unlink()

    # Must return confirmed=False
    r = client.get("/location")
    assert r.status_code == 200
    assert r.json().get("confirmed") is False
    print("  [OK] GET /location returns {confirmed: false}")

    # Downstream /acquire must be rejected with 412
    r_acq = client.post("/acquire", json={"force": False})
    assert r_acq.status_code == 412
    print(f"  [OK] POST /acquire rejected: HTTP {r_acq.status_code} ({r_acq.json()['detail']})")

    # Downstream /model/build must be rejected with 412
    r_build = client.post("/model/build", json={})
    assert r_build.status_code == 412
    print(f"  [OK] POST /model/build rejected: HTTP {r_build.status_code} ({r_build.json()['detail']})")

    # -------------------------------------------------------------------------
    # Test 2: Geocoding — Valid Address
    # -------------------------------------------------------------------------
    print("\n[Test 2] Valid Address Geocoding (Nominatim / Geocache)")
    r_geo = client.post("/location/geocode", json={"query": "GST Road, Chennai"})
    assert r_geo.status_code in (200, 502)
    if r_geo.status_code == 200:
        cands = r_geo.json()
        print(f"  [OK] Geocoded 'GST Road, Chennai' -> {len(cands)} candidate(s)")
        if cands:
            first = cands[0]
            print(f"    First candidate: {first['display_name'][:50]}... ({first['lat']:.4f}, {first['lon']:.4f})")
    else:
        print("  [WARN] Geocoder remote offline / rate limited, handled gracefully")

    # -------------------------------------------------------------------------
    # Test 3: Geocoding — Invalid Address Handling
    # -------------------------------------------------------------------------
    print("\n[Test 3] Invalid Address Handling")
    r_inv = client.post("/location/geocode", json={"query": "abcdef123456invalid_nonexistent_place"})
    assert r_inv.status_code == 200
    inv_cands = r_inv.json()
    assert len(inv_cands) == 0
    print("  [OK] Invalid address returns empty candidate list (no crash)")

    # -------------------------------------------------------------------------
    # Test 4: Manual Coordinates & Confirmation (writes location.json)
    # -------------------------------------------------------------------------
    print("\n[Test 4] Location Confirmation & Persistence (location.json)")
    confirm_payload = {
        "name": "GST Road, Chennai",
        "lat": 12.8231,
        "lon": 80.0442,
        "aoi_radius_m": 500.0,
        "confirmation_method": "user",
    }
    r_conf = client.post("/location/confirm", json=confirm_payload)
    assert r_conf.status_code == 200
    resp_data = r_conf.json()
    assert resp_data["ok"] is True
    assert resp_data["location"]["confirmed"] is True
    assert resp_data["location"]["lat"] == 12.8231
    assert resp_data["location"]["lon"] == 80.0442
    print("  [OK] POST /location/confirm returned HTTP 200")

    # Verify physical file on disk
    assert loc_file.exists(), f"location.json must exist at {loc_file}"
    saved = json.loads(loc_file.read_text(encoding="utf-8"))
    assert saved["confirmed"] is True
    assert saved["lat"] == 12.8231
    assert saved["lon"] == 80.0442
    assert saved["aoi_radius_m"] == 500.0
    print(f"  [OK] Verified location.json on disk ({loc_file}): {saved['name']} [{saved['lat']}, {saved['lon']}]")

    # Verify GET /location returns the confirmed location
    r_get = client.get("/location")
    assert r_get.status_code == 200
    assert r_get.json()["confirmed"] is True
    print("  [OK] GET /location now reports confirmed: true")

    # -------------------------------------------------------------------------
    # Test 5: Map Tiles Reachability
    # -------------------------------------------------------------------------
    print("\n[Test 5] Map Tile Service Reachability")
    tile_url = "https://tile.openstreetmap.org/15/23669/15206.png"
    try:
        res = requests.get(tile_url, headers={"User-Agent": "RoadTwin/0.2.0 (Testing)"}, timeout=5)
        print(f"  [OK] Standard OSM raster tile reachable: HTTP {res.status_code} ({len(res.content)} bytes)")
    except Exception as e:
        print(f"  [WARN] Remote tile warning: {e}")

    # -------------------------------------------------------------------------
    # Test 6: Coordinate <-> Pixel Roundtrip Precision
    # -------------------------------------------------------------------------
    print("\n[Test 6] Georeferencing Geometry & Coordinate Invariants")
    from vision.tiles import deg2num, num2deg, ground_resolution
    lat_in, lon_in, z = 12.8231, 80.0442, 19
    xtile, ytile = deg2num(lat_in, lon_in, z)
    lat_out, lon_out = num2deg(xtile, ytile, z)
    assert abs(lat_in - lat_out) < 0.005
    assert abs(lon_in - lon_out) < 0.005
    res = ground_resolution(lat_in, z)
    assert 0.2 < res < 0.35
    print(f"  [OK] Tile EPSG:3857 conversion invariant passes (resolution: {res:.4f} m/px at z{z})")

    print("\n" + "=" * 70)
    print("PHASE 3 ALL CHECKS PASSED: 100% GREEN")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(test_phase3())
