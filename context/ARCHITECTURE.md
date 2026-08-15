# ARCHITECTURE

## The one idea that shapes everything

**netconvert plain XML is the single editable substrate.** OSM comes in,
plain XML is produced, edits land on plain XML, and everything downstream —
the SUMO network, the OpenDRIVE export, the map overlays — is regenerated from
it by one compiler invocation.

One source of truth, one compiler call, no divergence.

```
Overpass ──► benchmark.osm
                  │  netconvert --osm-files
                  ▼
      plain XML   .nod .edg .con .tll .typ      ◄── ALL EDITS LAND HERE
                  │                                 (human + accepted AI)
                  │  netconvert
        ┌─────────┴─────────┐
        ▼                   ▼
  network.net.xml    road_network.xodr
        │
        │  randomTrips ──► routes.rou.xml   (generated ONCE, shared)
        ▼
   ┌────────────┬──────────────────────┐
   │  sumo      │  sumo -a closure.add │
   │  baseline  │  closure             │
   └─────┬──────┴───────────┬──────────┘
         └──────┬───────────┘
                ▼
      tripinfo / queue / summary  ──►  metrics.json  ──►  RoadTwin_Project.zip
```

## Process layout

```
┌───────────────────────────────────────────────────────────┐
│  TAURI 2 DESKTOP        React + TypeScript + MapLibre      │
│  Location · Review Queue · 2D Map · Experiment · Export    │
└───────────────┬───────────────────────────┬───────────────┘
                │ localhost HTTP            │ localhost HTTP
                ▼                           ▼
   ┌─────────────────────────┐   ┌─────────────────────────────┐
   │ CORE SIDECAR            │   │ VISION SIDECAR   (OPTIONAL) │
   │ FastAPI                 │   │ FastAPI                     │
   │ requests lxml numpy     │   │ torch transformers          │
   │ pillow pydantic         │   │ SAM 2.1 · Grounding DINO    │
   │ frozen with PyInstaller │   │ own venv, NOT frozen        │
   │ ~300 MB                 │   │ downloads weights on demand │
   └───────────┬─────────────┘   └──────────────┬──────────────┘
               │ subprocess                     │
               ▼                                │ observations.json
   ┌─────────────────────────┐                  │
   │ SUMO (external)         │◄─────────────────┘
   │ netconvert · sumo       │
   │ randomTrips.py          │
   │ found via SUMO_HOME     │
   └─────────────────────────┘
```

**Why two sidecars.** Freezing PyTorch into the installer produces a 3–5 GB
binary and makes every packaging problem worse. Splitting them means the core
app is small and reliable, and if vision is missing the UI degrades to
`[ Continue with OSM ]` — which is behaviour we want anyway.

## Layer responsibilities

| Layer | Owns | Must never |
|---|---|---|
| Desktop UI | Presentation, confirmation gates, review interaction | Contain engineering logic |
| Core sidecar | Acquisition, compilation, simulation, export, provenance | Import torch |
| Vision sidecar | Segmentation, detection, evidence generation | Write to the canonical model |
| plain XML | The model itself | Be edited by two writers at once |

## Data flow contract

1. Nothing downstream runs until the location is **confirmed** by the user.
2. AI writes only to `observations.json`. It never touches plain XML.
3. Observations are **immutable**. A rejected observation stays, marked REJECTED.
4. Only `core.model.edits.apply_edits()` mutates plain XML.
5. Every `apply_edits` is followed by exactly one `plain_to_net`.
6. `baseline plain XML + validation_report.json` must reproduce the final model.

Rule 6 is tested by `edits.replay()` and covered in `scripts/selftest.py`.
If you break it, the "auditable" claim becomes a slogan.

## Coordinate systems

| Where | CRS | Note |
|---|---|---|
| OSM, GeoJSON, the map UI | EPSG:4326 | degrees, boundary format only |
| SUMO network | projected metres | netconvert applies UTM automatically |
| Tile mosaic | EPSG:3857 pixels | affine to 4326 via `vision/tiles.Mosaic` |

Lengths, widths and closure distances are **always** taken in metres, from the
SUMO network or the mosaic's ground resolution. Never subtract degrees.

## Failure behaviour

| Failure | Behaviour |
|---|---|
| Overpass down / rate-limited | Fall back to the cached extract in `assets/benchmark/` |
| Vision sidecar absent | Show `[ Continue with OSM ]`, proceed with baseline |
| Tile provider unreachable | Use the cached mosaic; skip Track A evidence |
| Geocoder fails | Manual lat/lon entry still works |
| SUMO not installed | Clear startup error naming SUMO_HOME |
| Selected lane cannot be closed | Explicit error; never a fabricated experiment |

Never fail silently. Never substitute a plausible number for a missing one.
