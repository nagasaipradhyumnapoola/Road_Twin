"""Final export: RoadTwin_Project.zip

The zip is the deliverable a judge can take away, so it must be
self-describing. A README generated from the actual run -- real coordinates,
real metrics, real file list -- is worth more than any slide.
"""
from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

README_TEMPLATE = """# RoadTwin Project Export

Generated: {generated}
Build: {version}

## Location
{location_name}
lat {lat:.6f}, lon {lon:.6f}   (confirmed by: {confirmation})
AOI radius: {radius} m

## Contents

| File | What it is |
|---|---|
| roadtwin.json | Canonical road model: roads, lanes, junctions, objects, provenance |
| road_network.xodr | OpenDRIVE export (written by netconvert) |
| observations.json | Raw AI evidence, immutable, with confidence and status |
| validation_report.json | Every human decision, replayable against the baseline |
| source_manifest.json | Data sources, queries, timestamps, hashes |
| plain/ | netconvert plain XML - the editable substrate |
| sumo/ | Network, routes, scenario and raw simulation results |

## Experiment result

{results}

## How to reproduce

    python scripts/run_benchmark.py

Requires SUMO on PATH (SUMO_HOME set). See the top-level README.

## Known limitations

- The OpenDRIVE export carries geometry, lanes and junctions. Signal data is
  not represented in the .xodr; it lives in sumo/plain.tll.xml and roadtwin.json.
- Street-level AI detections are image-space only (geometry_kind =
  "image_space") and are attached to a road id rather than a coordinate.
  Only overhead-imagery evidence carries real-world geometry.
- SUMO closes a lane for the full length of an edge; the reported closure
  length is the actual edge length, not an arbitrary requested distance.
- One scenario type (lane closure) is implemented.
- The Windows binary is unsigned; SmartScreen will warn on first run.
"""


def write_source_manifest(project_dir: str | Path, entries: list[dict[str, Any]]) -> Path:
    p = Path(project_dir) / "source_manifest.json"
    p.write_text(json.dumps(
        {"schema_version": "0.1",
         "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "artifacts": entries},
        indent=2))
    return p


def write_readme(project_dir: str | Path, *, location: dict, results_table: str,
                 version: str = "0.1.0") -> Path:
    p = Path(project_dir) / "README.md"
    p.write_text(README_TEMPLATE.format(
        generated=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        version=version,
        location_name=location.get("name", "unnamed"),
        lat=location["lat"], lon=location["lon"],
        confirmation=location.get("confirmation_method", "user"),
        radius=location.get("aoi_radius_m", "?"),
        results=results_table or "(no simulation results in this export)",
    ))
    return p


def export_project(project_dir: str | Path, zip_path: str | Path) -> Path:
    """Zip the project folder. Skips scratch and per-seed raw output."""
    project_dir = Path(project_dir)
    zip_path = Path(zip_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    skip_parts = {"__pycache__", ".ipynb_checkpoints", "tmp"}
    n = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(project_dir.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(project_dir)
            # NB: test against the RELATIVE parts. Testing f.parts matches
            # directories in the absolute path (e.g. /tmp/...) and silently
            # produces an empty archive.
            if skip_parts & set(rel.parts):
                continue
            # keep aggregate results, drop the bulky per-seed queue dumps
            if f.name == "queue.xml" and "seed_" in str(rel):
                continue
            z.write(f, rel)
            n += 1
    size_mb = zip_path.stat().st_size / 1e6
    print(f"[export] {n} files -> {zip_path.name} ({size_mb:.1f} MB)")
    return zip_path
