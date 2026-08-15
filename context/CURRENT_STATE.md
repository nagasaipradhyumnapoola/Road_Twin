# CURRENT_STATE

> Claude Code: update this file at the end of every working session.
> It is the handoff note to your next session and the only place that records
> what is actually true right now.

**Last updated:** (not started)
**Build version:** 0.1.0-dev

---

## LAST VERIFIED END-TO-END

```
Command:      (none yet)
Result:       (none yet)
Benchmark:    (see config.py BENCHMARK)
Artifacts:    (none yet)
```

Fill this in only after `python scripts/run_benchmark.py` has completed
successfully. "It should work" does not go in this section.

---

## COMPLETED

- [ ] Day 0 — environment verified (`scripts/verify_environment.py` passes)
- [ ] Day 0 — benchmark location verified (lanes tag, junction, imagery)
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

(nothing yet)

## BROKEN

(nothing yet)

## NEXT

Day 0. Run `python scripts/verify_environment.py`, then verify the benchmark
location per EXECUTION_PLAN.md.

---

## CALIBRATION RECORD

Fill this in on Day 3. Losing these numbers costs you an hour of re-tuning.

```
SIM.period            = (unset)
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

Keep this honest. It is a strength in front of judges, not a weakness.

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
