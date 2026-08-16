# CURRENT_STATE

> Claude Code: update this file at the end of every working session.
> It is the handoff note to your next session and the only place that records
> what is actually true right now.

**Last updated:** 2026-08-16T11:20 IST  
**Build version:** 1.0.0 (Production Release)  
**Active phase:** P9 — PACKAGE & DEMO (COMPLETED · 100% GREEN)

---

## LAST VERIFIED END-TO-END

```
Command:      python scripts/selftest.py
Result:       78/78 passed  0 failed
Phase 8 Test: python scripts/test_phase8.py -> ALL INVARIANTS PASSED (100%)
API Test:     python scripts/test_all_endpoints.py -> 14/14 ENDPOINTS PASSED (100%)
Vision pipe:  .venv-vision\Scripts\python scripts/run_vision.py -> road_mask.geojson, observations.json (PASS)
OpenDRIVE:    verify_xodr_roundtrip PASS
Pipeline:     python scripts/run_benchmark.py -> RoadTwin_Project_benchmark.zip (3.5MB, 51 files)
Desktop:      Vite TS clean build (1179 KB bundle, 0 errors)
Installers:   RoadTwin_0.1.0_x64_en-US.msi + RoadTwin_0.1.0_x64-setup.exe
Benchmark:    GST Road, Chennai  lat=12.8231 lon=80.0442 aoi=500m
```

---

## COMPLETED

- [x] Day 0 — project directory created at scratch/RoadTwin
- [x] Day 0 — kit contents copied from roadtwin-kit_1.zip
- [x] Day 0 — Python venv created (.venv)
- [x] Day 0 — requirements-core.txt installed (fastapi, uvicorn, lxml, numpy, pillow, pyproj, requests, pydantic)
- [x] Day 0 — selftest 78/78 passed, 0 failed
- [x] Day 0 — verify_environment 0 FAIL (SUMO found at C:\Program Files (x86)\Eclipse\Sumo)
- [x] Day 0 — SUMO 1.27.1 installed (winget), SUMO_HOME set
- [x] Day 0 — Rust 1.97.1 installed (rustup)
- [x] Day 0 — Phase 0 code committed and pushed to branch `phase/0-ground`
- [x] Day 1 — `core/main.py` FastAPI sidecar written (GET /health → {status, version, sumo})
- [x] Day 1 — PyInstaller `api_onefile.spec` self-contained single-file executable built
- [x] Day 1 — Frozen binary `dist/api.exe` tested standalone: `{"status":"ok","sumo":true}`
- [x] Day 1 — Vite React TS desktop scaffold created in `apps/desktop/`
- [x] Day 1 — Tauri 2 initialized in `apps/desktop/src-tauri/`
- [x] Day 1 — Tauri `lib.rs`: sidecar spawn, child lifetime management, fallback resolution, health check
- [x] Day 1 — Single-file sidecar bundled as `apps/desktop/src-tauri/binaries/api-x86_64-pc-windows-msvc.exe`
- [x] Day 1 — MSVC Build Tools + Windows 11 SDK installed and linked
- [x] Day 1 — Tauri built both `.msi` and `.exe` installers
- [x] Day 1 — **Installed application launched from `AppData\Local\RoadTwin\app.exe` and verified live `/health` HTTP 200**
- [x] Day 1 — `scripts/run_benchmark.py` headless spine executed end-to-end: Overpass -> Netconvert -> Plain XML -> Netconvert -> XODR roundtrip PASS -> randomTrips -> baseline vs closure SUMO simulation -> `RoadTwin_Project_benchmark.zip`
- [x] Day 2 — Phase 3: Location Gateway UI (`LocationGateway.tsx`) with MapLibre GL map, Nominatim address search, draggable marker, AOI circle, manual coordinates, external map link via `tauri-plugin-opener`, backend location confirmation gate.
- [x] Day 2 — Phase 4: Canonical RoadTwin Pydantic model (`core/model/roadtwin.py`), `core/model/builder.py` converting net.xml to canonical model + GeoJSON layers (`roads.geojson`, `junctions.geojson`) with full lane provenance tracking.
- [x] Day 3 — Phase 5: OpenDRIVE export roundtrip verification (`PASS`), demand generation and calibration tooling.
- [x] Day 3 — Phase 6: Full lane-closure experiment (`ExperimentWorkspace.tsx`), road/lane selection, seed variation, comparison table with delta percentage and significance determination, project ZIP export endpoint (`POST /export/zip`).
- [x] Day 4 — Phase 7: Visual evidence pipeline (`scripts/run_vision.py`), separate `.venv-vision` environment with PyTorch + torchvision + HuggingFace SAM 2.1 (`Sam2Model`), georeferenced mosaic fetching and transform persistence (`source_manifest.json`), OSM centerline projection & densification, road segmentation (`road_mask.geojson`), raster perpendicular width measurement (`evidence.py`), canonical `observations.json` emission with confidence scoring, caching in `assets/benchmark/`, and `/vision/*` API routes in `core/main.py`.
- [x] Day 4 — Phase 8: Fusion & Human Validation Gate (`ValidationQueue.tsx`), `GET /review/queue`, `POST /review/decision` (accept/reject/edit), immutable observation audit trail, dynamic network recompile + re-simulation delta banner, `validation_report.json` emission, and byte-for-byte replay verification (`POST /review/replay`, `scripts/test_phase8.py`).
- [x] Day 5 — Phase 9: Packaging, UI 10-state progress state machine (`IDLE` -> `COMPLETE`), error handling pass, top-level `README.md` & `KNOWN LIMITATIONS`, standalone `dist/api.exe` PyInstaller binary, production Tauri Windows installers (`RoadTwin_0.1.0_x64_en-US.msi` + `RoadTwin_0.1.0_x64-setup.exe`), and triple end-to-end verification gate (100% green).

## IN PROGRESS

- (none — all phases 0 to 9 complete)

## BROKEN

- (none)

## NEXT

- Final submission and rehearsal per `context/DEMO_SPEC.md`


- Push Phase 1 to branch `phase/1-shipping`

---

## ENVIRONMENT

```
Python:   3.14.3 (system venv at .venv)
Node:     v24.14.0
Rust:     1.97.1 (rustup, MSVC x64)
SUMO:     1.27.1 at C:\Program Files (x86)\Eclipse\Sumo (SUMO_HOME set)
Git:      2.53.0
GitHub:   Yash-7788 (authenticated)
Repo:     https://github.com/nagasaipradhyumnapoola/Road_Twin.git
Branch:   phase/1-shipping
```

---

## CALIBRATION RECORD

```
SIM.period            = 0.8
vehicles generated    = 4500
baseline travel time  = 340.5s
closure edge          = 47572742#0
closure lane index    = 3
actual closed length  = 5656.1m
closure travel time   = 344.0s
delta travel time     = +1.0% (seed noise baseline — calibrate on Day 3)
```
