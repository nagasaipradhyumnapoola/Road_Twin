# CURRENT_STATE

> Claude Code: update this file at the end of every working session.
> It is the handoff note to your next session and the only place that records
> what is actually true right now.

**Last updated:** 2026-08-18  
**Build version:** 1.0.0  
**Active phase:** P0 — GROUND (RE-OPENED after audit; repairs landed, runtime verification blocked)

---

## CURRENT VERIFIED STATE — this machine, 2026-08-18

Only what has actually been re-run and observed here. Nothing below is inherited.

```
python scripts/selftest.py            83 passed, 0 failed        VERIFIED
python scripts/verify_environment.py  4 ok, 3 warn, 5 FAIL       VERIFIED FAILING
python scripts/run_benchmark.py --skip-sim
                                      exit 2 at step 3           VERIFIED FAILING
Benchmark:  GST Road, Chennai  lat=12.8261 lon=80.0413 aoi=500m  (relocated 2026-08-18)
```

All 5 environment failures have one cause: **SUMO is not installed on this
machine** (no netconvert, no sumo, no netedit, SUMO_HOME unset). Rust/cargo is
also absent. These are MACHINE SETUP items, not repository defects.

**NOT verified here:** network.net.xml, road_network.xodr, OpenDRIVE round-trip,
the AOI clip, the full pipeline, the vision pipeline, the desktop build, the
installers. All of them require SUMO and/or the Rust toolchain.

---

## HISTORICAL — recorded 2026-08-16 on a DIFFERENT machine, NOT reproduced here

Kept for provenance only. Treat as unverified until re-run on this machine.

```
Command:      python scripts/selftest.py
Result:       78/78 passed  0 failed        (suite has since grown to 83)
Phase 8 Test: python scripts/test_phase8.py -> ALL INVARIANTS PASSED (100%)
API Test:     python scripts/test_all_endpoints.py -> 14/14 ENDPOINTS PASSED (100%)
Vision pipe:  .venv-vision\Scripts\python scripts/run_vision.py -> road_mask.geojson, observations.json (PASS)
OpenDRIVE:    verify_xodr_roundtrip PASS
Pipeline:     python scripts/run_benchmark.py -> RoadTwin_Project_benchmark.zip (3.5MB, 51 files)
Desktop:      Vite TS clean build (1179 KB bundle, 0 errors)
Installers:   RoadTwin_0.1.0_x64_en-US.msi + RoadTwin_0.1.0_x64-setup.exe
Benchmark:    GST Road, Chennai  lat=12.8231 lon=80.0442 aoi=500m  (superseded)
```

That pipeline run was made BEFORE the AOI was enforced, so its network extended
far beyond the 500 m AOI. See the calibration record at the bottom of this file.

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

- P0 re-verification. Code repairs landed 2026-08-18; runtime proof still blocked.

## BROKEN

- **SUMO not installed on this machine** — blocks netconvert, sumo, netedit,
  `verify_environment.py` (5 FAIL), and `run_benchmark.py` (exit 2 at step 3).
- **Rust/cargo not installed on this machine** — blocks the Tauri build (P1+).
- Python here is 3.14.3; project documents 3.11/3.12 and `verify_environment.py`
  accepts only `>=3.10, <3.14`, so it reports WARN. Selftest passes regardless.

## KNOWN FUTURE ISSUES (do not fix in P0)

- `core/sim/metrics.py` `compare()`: `significant = tt_sd == 0 or ...`. With a
  single seed `aggregate()` sets sd to 0.0, so ANY delta — even 0.0% — is
  reported significant. `SETUP.md` recommends `--seeds 1`. Belongs to P5/P6.

## NEXT

- Install SUMO + set SUMO_HOME, then re-run `verify_environment.py` and
  `run_benchmark.py --skip-sim` to prove the AOI clip and the .xodr round-trip.
- Fill the verification block in `context/DEMO_SPEC.md` from that run.
- Only then consider P1.

---

## ENVIRONMENT

Measured on this machine 2026-08-18. Do not copy figures in from another box.

```
Python:   3.14.3 (.venv, from C:\Python314)   WARN: outside documented 3.11/3.12
Node:     v24.14.0        npm 11.9.0
Rust:     NOT INSTALLED   (no cargo on PATH, no ~/.cargo, no winget entry)
SUMO:     NOT INSTALLED   (SUMO_HOME unset; no netconvert/sumo/netedit anywhere)
MSVC:     Visual Studio Build Tools 2026 v18.4.0   (docs say 2022)
WebView2: Runtime 151.0.4129.86
Git:      2.50.1.windows.1
Repo:     https://github.com/nagasaipradhyumnapoola/Road_Twin.git
Branch:   phase/0-ground
```

---

## CALIBRATION RECORD — STALE, superseded 2026-08-18

Recorded before the AOI was enforced and before the benchmark was relocated.
`actual closed length = 5656.1m` inside a "500 m AOI" is the symptom that
exposed the missing clip: Overpass returned whole ways, nothing clipped the
build, so the closure landed on a 5.7 km edge. Also note the delta is +1.0% —
within seed noise, i.e. this was never a demo-ready result.

Re-calibrate from scratch once SUMO is installed. Do not reuse these numbers.

```
SIM.period            = 0.8
vehicles generated    = 4500
baseline travel time  = 340.5s
closure edge          = 47572742#0
closure lane index    = 3
actual closed length  = 5656.1m          <- 11x the AOI diameter; invalid
closure travel time   = 344.0s
delta travel time     = +1.0% (within seed noise — NOT a result)
```
