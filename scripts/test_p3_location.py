#!/usr/bin/env python3
"""P3 Location Gateway backend regression tests.

    python scripts/test_p3_location.py

Covers the repaired backend behaviour: coordinate validation at the request
boundary, strict-JSON persistence, the confirmed-location gate (including
/network/geojson), confirmation_method provenance, and clean geocode error
handling. Upstream geocoding is MOCKED, so ordinary runs need no network. The
one real-Nominatim check is gated behind ROADTWIN_LIVE_GEOCODE=1 and clearly
labelled -- it is manual/integration, not part of the default suite.

Runs against an isolated ROADTWIN_DATA_DIR so it never touches the repo's
projects/ or a developer's real state.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Isolate persistent state BEFORE importing the app.
_TMP = tempfile.mkdtemp(prefix="rt_p3_")
os.environ["ROADTWIN_DATA_DIR"] = _TMP

warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402

import core.main as M  # noqa: E402

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL {name}  {detail}")


def section(t: str) -> None:
    print(f"\n{t}\n" + "-" * len(t))


client = TestClient(M.app)
VALID = {"name": "GST Road", "lat": 12.8261, "lon": 80.0413, "aoi_radius_m": 500}


def _clear_location() -> None:
    M._location_path().unlink(missing_ok=True)


def _raw_confirm(body: dict):
    """POST with json.dumps so NaN/Infinity reach the server as literal tokens
    (Python's json emits them; httpx's json= would refuse)."""
    return client.post("/location/confirm", content=json.dumps(body),
                       headers={"Content-Type": "application/json"})


# ===========================================================================
def test_validation():
    section("coordinate validation at the request boundary")
    _clear_location()

    r = client.post("/location/confirm", json=VALID)
    check("valid coordinates accepted (200)", r.status_code == 200,
          str(r.status_code))
    check("valid confirm writes confirmed=true",
          r.json()["location"]["confirmed"] is True)

    bad = [
        ("latitude 999 rejected", {**VALID, "lat": 999}),
        ("latitude -91 rejected", {**VALID, "lat": -91}),
        ("longitude 181 rejected", {**VALID, "lon": 181}),
        ("longitude -181 rejected", {**VALID, "lon": -181}),
        ("AOI radius 0 rejected", {**VALID, "aoi_radius_m": 0}),
        ("AOI radius -500 rejected", {**VALID, "aoi_radius_m": -500}),
    ]
    for name, body in bad:
        check(name, client.post("/location/confirm", json=body).status_code == 422)

    nonfinite = [
        ("NaN latitude rejected", {**VALID, "lat": float("nan")}),
        ("Infinity latitude rejected", {**VALID, "lat": float("inf")}),
        ("-Infinity longitude rejected", {**VALID, "lon": float("-inf")}),
    ]
    for name, body in nonfinite:
        r = _raw_confirm(body)
        # Must be a clean 422, not a 500 from echoing the non-serialisable input.
        check(name, r.status_code == 422, str(r.status_code))
        try:
            r.json()
            parseable = True
        except Exception:
            parseable = False
        check(f"  -> {name.split()[0]} error response is valid JSON", parseable)


def test_no_invalid_write():
    section("invalid coordinates never reach location.json")
    _clear_location()
    _raw_confirm({**VALID, "lat": float("nan")})
    check("rejected NaN did not create location.json",
          not M._location_path().exists())

    # A valid confirm writes strict JSON: no bare NaN/Infinity tokens on disk.
    client.post("/location/confirm", json=VALID)
    raw = M._location_path().read_text()
    check("location.json exists after valid confirm", bool(raw))
    check("location.json contains no NaN/Infinity token",
          "NaN" not in raw and "Infinity" not in raw)
    strict_ok = True
    try:
        json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    except ValueError:
        strict_ok = False
    check("location.json parses under STRICT json (JS JSON.parse-equivalent)",
          strict_ok)
    check("location.json holds the submitted coordinates",
          json.loads(raw)["lat"] == 12.8261 and json.loads(raw)["lon"] == 80.0413)


def test_confirmation_method():
    section("confirmation_method provenance is server-assigned")
    _clear_location()
    r = client.post("/location/confirm",
                    json={**VALID, "confirmation_method": "benchmark_config"})
    check("client-supplied confirmation_method is ignored",
          r.json()["location"]["confirmation_method"] == "user",
          r.json()["location"]["confirmation_method"])
    for spoof in ("system", "verified", "trusted"):
        r = client.post("/location/confirm",
                        json={**VALID, "confirmation_method": spoof})
        check(f"'{spoof}' cannot be spoofed",
              r.json()["location"]["confirmation_method"] == "user")


def test_backend_gate():
    section("confirmed-location gate (server-side, bypasses the UI)")
    gated = [("GET", "/network/edges"), ("POST", "/acquire"),
             ("GET", "/network/geojson"), ("POST", "/export/zip")]

    _clear_location()
    for method, ep in gated:
        r = client.request(method, ep, json={} if method == "POST" else None)
        check(f"no location: {method} {ep} -> 412", r.status_code == 412,
              str(r.status_code))

    M._location_path().parent.mkdir(parents=True, exist_ok=True)
    M._location_path().write_text(json.dumps(
        {"name": "u", "lat": 12.9, "lon": 80.1, "confirmed": False}))
    for method, ep in gated:
        r = client.request(method, ep, json={} if method == "POST" else None)
        check(f"unconfirmed: {method} {ep} -> 412", r.status_code == 412,
              str(r.status_code))

    client.post("/location/confirm", json=VALID)

    # After confirming, the LOCATION gate opens. Endpoints then hit their own
    # preconditions -- and "network not built" is ALSO a 412, so a status code
    # alone cannot tell the two apart. Distinguish by the detail message: the
    # location gate says "not confirmed"; anything else means the gate opened.
    def _location_blocked(resp) -> bool:
        if resp.status_code != 412:
            return False
        detail = resp.json().get("detail", "")
        return isinstance(detail, str) and "not confirmed" in detail.lower()

    for ep in ("/network/geojson", "/network/edges", "/export/zip"):
        method = "GET" if ep.startswith("/network") else "POST"
        r = client.request(method, ep, json={} if method == "POST" else None)
        check(f"confirmed: {ep} passes the location gate",
              not _location_blocked(r),
              f"{r.status_code} {r.json().get('detail','')[:40] if isinstance(r.json().get('detail'),str) else ''}")


def test_geocode_errors():
    section("geocode error handling (upstream mocked)")
    import core.acquire.geocoder as G
    orig = G.geocode

    # 1. empty / whitespace input -> clean [] (no crash, no upstream call)
    check("empty query returns [] cleanly",
          client.post("/location/geocode", json={"query": ""}).json() == [])
    check("whitespace query returns [] cleanly",
          client.post("/location/geocode", json={"query": "   "}).json() == [])

    # 2. reachable geocoder, no match -> [] (address-not-found, NOT an error)
    G.geocode = lambda *a, **k: []
    r = client.post("/location/geocode", json={"query": "no such place xyz"})
    check("address-not-found returns 200 with []",
          r.status_code == 200 and r.json() == [], str(r.status_code))

    # 3. upstream failure -> clean 503, no URL / traceback leak
    import requests

    def _boom(*a, **k):
        raise requests.HTTPError(
            "403 Client Error: Forbidden for url: "
            "https://nominatim.openstreetmap.org/search?q=secret")
    G.geocode = _boom
    r = client.post("/location/geocode", json={"query": "anything"})
    check("upstream failure returns 503", r.status_code == 503, str(r.status_code))
    body = json.dumps(r.json())
    check("503 message is user-facing, not raw upstream text",
          "unavailable" in body.lower())
    check("503 does not leak the upstream URL",
          "nominatim.openstreetmap.org" not in body and "http" not in body.lower())

    G.geocode = orig


def test_live_geocode():
    section("LIVE Nominatim (integration -- set ROADTWIN_LIVE_GEOCODE=1)")
    if os.environ.get("ROADTWIN_LIVE_GEOCODE") != "1":
        print("  ..   skipped (network integration test; not part of the suite)")
        return
    r = client.post("/location/geocode", json={"query": "GST Road, Chennai"})
    check("live: GST Road, Chennai resolves", r.status_code == 200 and r.json(),
          str(r.status_code))
    if r.status_code == 200 and r.json():
        c0 = r.json()[0]
        check("live: candidate has plausible Chennai coordinates",
              12.5 < c0["lat"] < 13.5 and 79.5 < c0["lon"] < 80.5,
              f"{c0['lat']:.4f},{c0['lon']:.4f}")


def main() -> int:
    print("=" * 72)
    print("P3 Location Gateway backend regression tests")
    print(f"(isolated data dir: {_TMP})")
    print("=" * 72)
    test_validation()
    test_no_invalid_write()
    test_confirmation_method()
    test_backend_gate()
    test_geocode_errors()
    test_live_geocode()
    print("\n" + "=" * 72)
    print(f"{PASS} passed, {FAIL} failed")
    print("=" * 72)

    import shutil
    shutil.rmtree(_TMP, ignore_errors=True)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
