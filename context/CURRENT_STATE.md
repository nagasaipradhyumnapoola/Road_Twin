# CURRENT_STATE

> Claude Code: update this file at the end of every working session.
> It is the handoff note to your next session and the only place that records
> what is actually true right now.

**Last updated:** 2026-08-16T01:20 IST  
**Build version:** 0.1.0  
**Active phase:** P1 — SHIPPING PATH (COMPLETED)

---

## LAST VERIFIED END-TO-END

```
Command:      python scripts/selftest.py
Result:       78/78 passed  0 failed
Verify Env:   10 ok, 2 warn (python 3.14 + optional torch), 0 fail
Installer:    RoadTwin_0.1.0_x64-setup.exe + RoadTwin_0.1.0_x64_en-US.msi
Installed:    C:\Users\yashk\AppData\Local\RoadTwin\app.exe launches & /health responds
Headless:     python scripts/run_benchmark.py -> RoadTwin_Project_benchmark.zip (2.5MB)
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
- [x] Day 1 — `scripts/run_benchmark.py` headless spine executed end-to-end: Overpass -> Netconvert -> Plain XML -> Netconvert -> XODR roundtrip PASS -> randomTrips -> 5 seeds baseline vs closure SUMO simulation -> `RoadTwin_Project_benchmark.zip` (2.5 MB)

## IN PROGRESS

- Ready for Phase 2 / Phase 3

## BROKEN

- (none)

## NEXT

- Phase 2: Location Gateway UI (MapLibre + marker drag + confirm AOI)
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
