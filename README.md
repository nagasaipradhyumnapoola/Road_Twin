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
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements-core.txt

python scripts/selftest.py            # 64 tests, ~2 seconds, no SUMO needed
python scripts/verify_environment.py  # checks SUMO, tools, network, cache
python scripts/run_benchmark.py       # full pipeline end to end
```

Then open **`EXECUTION_PLAN.md`** and start at Day 0.

---

## Prerequisites

| Tool | Version | Why |
|---|---|---|
| Python | 3.11 / 3.12 | core engine |
| **SUMO** | **1.19+** | **required — set `SUMO_HOME`** |
| Node.js | 20 LTS | Tauri frontend |
| Rust | stable | Tauri shell |
| MSVC Build Tools | 2022 | Tauri on Windows |

SUMO is an external prerequisite by design (ADR-008) — bundling it adds
hundreds of MB and a licence-notice obligation for no demo benefit.

See `SETUP.md` for the full install.

---

## The three architectural decisions that matter

**1. netconvert is the compiler backend (ADR-003).**
We do not hand-write OpenDRIVE. `netconvert` imports OSM *and* exports
OpenDRIVE. A homegrown `.xodr` emitter is 2–3 days of work whose failure mode
is a silently disconnected network in which no vehicle can route.

**2. Plain XML is the single editable substrate (ADR-004).**
`netconvert` emits `.nod/.edg/.con/.tll`. Edits land there; one recompile
regenerates the SUMO network, the OpenDRIVE and the map overlays. One source of
truth, no divergence.

**3. AI produces evidence, never changes (ADR-002).**
Model output goes to `observations.json` with a confidence and `status: REVIEW`.
It becomes a change only when a human accepts it, and the decision is recorded
so that `baseline + validation_report == final model` — an invariant that is
tested, not asserted.

---

## Running the tests

```bash
python scripts/selftest.py
```

64 tests covering the logic that is easy to get subtly and silently wrong:
tile georeferencing, lane-count evidence, SUMO output parsing, plain-XML edits,
closure scenario generation, export packaging. No SUMO and no network required,
so run them constantly.

The netconvert/sumo subprocess calls are covered by `run_benchmark.py` on a
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
