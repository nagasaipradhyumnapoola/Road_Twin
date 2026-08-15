"""One-shot Overpass fetch — run from repo root."""
import requests
import time
from pathlib import Path

QUERY = """[out:xml][timeout:90];
(
  way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|unclassified|residential|service)$"]
     (12.81861,80.03959,12.82759,80.04881);
  >;
);
out body;
"""

UA = "RoadTwin/0.1 (SIH2025; roadtwin.sih@gmail.com)"
OUT = Path("assets/benchmark/benchmark.osm")
OUT.parent.mkdir(parents=True, exist_ok=True)

ENDPOINTS = [
    ("POST", "https://overpass-api.de/api/interpreter"),
    ("GET",  "https://overpass-api.de/api/interpreter"),
    ("POST", "https://overpass.kumi.systems/api/interpreter"),
    ("POST", "https://overpass.openstreetmap.ru/api/interpreter"),
    ("GET",  "https://lz4.overpass-api.de/api/interpreter"),
]

for method, url in ENDPOINTS:
    print(f"Trying {method} {url} ...")
    try:
        if method == "POST":
            r = requests.post(url, data={"data": QUERY}, headers={"User-Agent": UA}, timeout=100)
        else:
            r = requests.get(url, params={"data": QUERY}, headers={"User-Agent": UA}, timeout=100)
        print(f"  => {r.status_code}  {len(r.content)} bytes")
        if r.status_code == 200 and b"<osm" in r.content[:500]:
            OUT.write_bytes(r.content)
            print(f"  SAVED to {OUT}  ({OUT.stat().st_size/1024:.0f} KB)")
            break
    except Exception as e:
        print(f"  ERROR: {e}")
    time.sleep(3)
else:
    print("ALL ENDPOINTS FAILED — Overpass is down. Try again in 10 minutes.")
    raise SystemExit(1)
