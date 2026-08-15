# CURRENT_STATE

> Claude Code: update this file at the end of every working session.
> It is the handoff note to your next session and the only place that records
> what is actually true right now.

**Last updated:** 2026-08-15T23:59 IST
**Build version:** 0.1.0-dev
**Active phase:** P0 — GROUND

---

## LAST VERIFIED END-TO-END

```
Command:      python scripts/selftest.py
Result:       (run after deps install)
Benchmark:    GST Road, Chennai  lat=12.8231 lon=80.0442 aoi=500m
Artifacts:    (none yet)
```

---

## COMPLETED

- [x] Day 0 — project directory created at scratch/RoadTwin
- [x] Day 0 — kit contents copied from roadtwin-kit_1.zip
- [x] Day 0 — Python venv created (.venv)
- [x] Day 0 — requirements-core.txt installation started
- [ ] Day 0 — environment verified (selftest 64/64, verify_environment 0 FAIL)
- [ ] Day 0 — benchmark location verified (lanes tag, junction, imagery)
- [ ] Day 0 — Rust installed (needed for Tauri — Phase 1)
- [ ] Day 1 — Tauri shell launches
- [ ] Day 1 — core sidecar frozen and wired
- [ ] Day 1 — **installer built and installed, /health responds**
- [ ] Day 1 — `run_benchmark.py` produces real metrics and a zip
- [ ] Day 2 — location gateway with working map tiles
- [ ] Day 2 — Overpass acquisition with cache
- [ ] Day 2 — RoadTwin model + lane_count_provenance
- [ ] Day 2 — edit → recompile regenerates net.xml and .xodr
- [ ] Day 3 — demand calibrated (record the period value below)
- [ ] Day 3 — baseline vs closure, N seeds, significant delta
- [ ] Day 3 — OpenDRIVE round-trip verified
- [ ] Day 3 — export from the UI
- [ ] Day 4 — georeferenced mosaic + transform persisted
- [ ] Day 4 — SAM road mask from centerline prompts
- [ ] Day 4 — lane-count evidence + review queue
- [ ] Day 4 — accept → model → simulation changes
- [ ] Day 5 — map polish, progress states, error handling
- [ ] Day 5 — installer verified on a clean machine
- [ ] Day 5 — backup demo video recorded

## IN PROGRESS

- P0 — pip install requirements-core.txt
- P0 — selftest verification pending

## BROKEN

- Rust/Cargo NOT installed → Tauri build blocked (Phase 1 prerequisite)
- SUMO NOT installed → simulation phases blocked (Phases 2–6)
  → need: https://sumo.dlr.de/docs/Downloads.php

## NEXT

Run `python scripts/selftest.py` after pip install completes.
Then install SUMO + Rust for Phase 1 readiness.

---

## ENVIRONMENT

```
Python:   3.14.3 (system) — kit recommends 3.11/3.12, monitor for compat issues
Node:     v24.14.0
Rust:     NOT INSTALLED — install from https://rustup.rs
SUMO:     NOT INSTALLED — install from https://sumo.dlr.de/docs/Downloads.php
Git:      2.53.0
GitHub:   Yash-7788 (authenticated)
Repo:     https://github.com/nagasaipradhyumnapoola/Road_Twin.git
Branch:   phase/0-ground (to be created)
```

---

## CALIBRATION RECORD

Fill this in on Day 3.

```
SIM.period            = 0.8 (default — tune on Day 3)
vehicles generated    = (unset)
vehicles completed    = (unset)
baseline travel time  = (unset)
closure edge          = (unset)
closure lane index    = (unset)
actual closed length  = (unset)
delta travel time     = (unset)
significant?          = (unset)
```

---

## KNOWN LIMITATIONS

- OpenDRIVE export carries geometry, lanes and junctions; **signal data is not
  represented in the .xodr** (SUMO's exporter limitation). Signals live in
  `plain.tll.xml` and `roadtwin.json`.
- Street-level detections are `geometry_kind: "image_space"` — attached to a
  road id, no real-world coordinate claimed.
- SUMO closes a lane for a full edge; the reported closure length is the actual
  edge length.
- Demand is synthetic (randomTrips), not counted or calibrated against field
  data. The experiment is a controlled comparison, not a forecast.
- One scenario type: lane closure.
- Windows binary is unsigned; SmartScreen warns on first run.
- No pothole detection (ADR-013).
