# RoadTwin — SIH #95

Turn a real Indian road into an editable, simulation-ready digital road model,
without rebuilding the network by hand.

```
address ─► confirm location ─► OSM baseline ─► visual AI evidence
        ─► engineer validates ─► RoadTwin ─► OpenDRIVE ─► SUMO
        ─► lane-closure experiment ─► project export
```

---

## What this kit is

This is the **execution kit**, not the finished app: the plan, the context
files, the day-by-day Claude Code prompts, the working core modules and the
documentation notebooks. You build the Tauri desktop shell around it.

```
roadtwin-kit/
├── EXECUTION_PLAN.md        ★ start here — step-by-step, Day 0 to Day 5
├── SETUP.md                 environment install, exact commands
├── config.py                every tunable in one place
│
├── context/                 read by Claude Code before any change
│   ├── PROJECT_CONTEXT.md   problem, solution, boundary, non-goals
│   ├── ARCHITECTURE.md      how the pieces fit, failure behaviour
│   ├── DATA_CONTRACT.md     every schema
│   ├── DECISIONS.md         13 binding ADRs
│   ├── CURRENT_STATE.md     living handoff note — update it daily
│   └── DEMO_SPEC.md         benchmark, demo script, insurance checklist
│
├── prompts/                 paste into Claude Code, verbatim
│   ├── master.md            binding constraints — paste every session
│   └── day-00 … day-05.md
│
├── core/                    ★ working, unit-tested
│   ├── acquire/overpass.py     OSM download + cache
│   ├── build/netconvert.py     OSM → plain XML → net.xml + .xodr
│   ├── model/edits.py          the edit → recompile funnel + replay
│   ├── sim/demand.py           randomTrips + calibration helper
│   ├── sim/scenario.py         rerouter lane closure
│   ├── sim/run.py              baseline vs closure across seeds
│   ├── sim/metrics.py          SUMO output → metrics + significance
│   ├── export/package.py       RoadTwin_Project.zip
│   └── provenance.py           sha256 artifact chain
│
├── vision/                  ★ working
│   ├── tiles.py                georeferenced mosaic (pixel ↔ lon/lat)
│   ├── segment.py              SAM 2.1, centerline-prompted
│   ├── detect.py               Grounding DINO
│   └── evidence.py             mask width → lane-count claim
│
├── scripts/
│   ├── verify_environment.py   ★ Day 0 gate
│   ├── selftest.py             ★ 64 tests, no SUMO or network needed
│   └── run_benchmark.py        ★ headless end-to-end — THE regression test
│
└── notebooks/
    ├── 01_pipeline_walkthrough.ipynb
    └── 02_final_demo.ipynb
```

---

## Quick start

```bash
# 1. Setup core venv & dependencies
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements-core.txt

# 2. Run test suites
python scripts/selftest.py            # 78 unit tests, ~2s, no SUMO needed
python scripts/test_all_endpoints.py  # 14 FastAPI endpoints tested live
python scripts/verify_environment.py  # checks SUMO, tools, network, cache
python scripts/run_benchmark.py       # full pipeline end-to-end benchmark

# 3. Vision Environment (Optional AI upside)
python -m venv .venv-vision && .venv-vision\Scripts\activate
pip install -r requirements-vision.txt
python scripts/run_vision.py          # georeferenced mosaic -> SAM 2.1 mask -> observations.json

# 4. Launch Desktop App (Tauri + React + FastAPI Sidecar)
cd apps/desktop
npm install
npm run tauri dev
```

---

## Running the tests

```bash
python scripts/selftest.py
```

78 tests covering the logic that is easy to get subtly and silently wrong:
tile georeferencing, lane-count evidence, SUMO output parsing, plain-XML edits,
closure scenario generation, export packaging. No SUMO and no network required.

The netconvert/sumo subprocess calls are covered by `test_all_endpoints.py` and `run_benchmark.py` on a
machine with SUMO installed.

---

## Known limitations

Stated up front, because a team that knows its own limits reads as competent.

- The OpenDRIVE export carries geometry, lanes and junctions. **Signal data is
  not represented in the `.xodr`** (a documented SUMO exporter limitation); it
  lives in `plain.tll.xml` and `roadtwin.json`.
- Street-level AI detections are `geometry_kind: "image_space"` — attached to a
  road id, with no real-world coordinate claimed. Only overhead-imagery
  evidence carries geometry.
- SUMO closes a lane for the full length of an edge; the reported closure
  length is the actual edge length, not an arbitrary requested distance.
- Demand is synthetic (`randomTrips`), not calibrated against field counts. The
  experiment is a controlled comparison, not a forecast.
- One scenario type: lane closure.
- The Windows binary is unsigned; SmartScreen warns on first run.
- No pothole detection — open-vocabulary models cannot do it reliably (ADR-013).

---

## Licences to note

SUMO is EPL-2.0. SAM 2.1 and Grounding DINO checkpoints are Apache-2.0. Check
your tile and geocoding providers' terms before shipping, set a real
`User-Agent`, and do not commit API keys.
