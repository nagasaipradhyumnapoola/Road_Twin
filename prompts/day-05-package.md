# DAY 5 — Integration, packaging, rehearsal

(Paste `prompts/master.md` first.)

---

**Add no new features. None.** Today is about making what exists reliable and
presentable.

## 1. 2D map polish

Lane overlays, review markers, confidence colouring, selected-road highlight.

**No 3D** (ADR-012). A rushed three.js scene looks worse than a good 2D map and
costs four times as much.

## 2. Progress state machine

Wire these to the UI so the user always knows what is happening:

```
IDLE  LOCATING  ACQUIRING  BUILDING  ANALYZING  REVIEW_REQUIRED
VALIDATING  EXPORTING  SIMULATING  COMPLETE  FAILED
```

## 3. Error handling pass

Walk every row of the failure table in `context/ARCHITECTURE.md` and confirm
the behaviour matches. Rules:

- never fail silently
- never substitute a plausible number for a missing one
- every error message says what happened **and** what the user can do

## 4. Export

Final `RoadTwin_Project.zip` per `context/DATA_CONTRACT.md`, including a
generated internal README built from the actual run — real coordinates, real
metrics, real file list. `core/export/package.py` already does this.

## 5. Notebooks

Two, both **thin** — they import `core/` and `vision/` and call them. They must
not reimplement pipeline logic; duplicated logic rots within a day.

- `notebooks/01_pipeline_walkthrough.ipynb` — the engineering story
- `notebooks/02_final_demo.ipynb` — reproduces the benchmark end to end

## 6. Documentation

- top-level `README.md`: prerequisites (**SUMO, with SUMO_HOME**), install, run,
  benchmark, limitations
- `KNOWN LIMITATIONS`, written honestly:
  - OpenDRIVE export carries geometry, lanes and junctions; **signal data is
    not represented in the .xodr** — it lives in `plain.tll.xml` and
    `roadtwin.json`
  - street-level detections are image-space only
  - SUMO closes a lane for a full edge; the reported length is the real one
  - demand is synthetic, not field-calibrated
  - one scenario type
  - unsigned binary — SmartScreen will warn
- `context/CURRENT_STATE.md`: exact successful command, benchmark coordinates,
  generated artifacts, known limitations, build version

Honesty here is a strength in front of judges, not a weakness. A team that
knows its own limitations reads as competent.

## 7. Final installer, verified on a clean machine

```
cd apps/desktop && npm run tauri build
```

Install it somewhere that has never seen the source tree. Then whitelist it in
SmartScreen and antivirus on the demo machine — an unsigned PyInstaller binary
frequently trips heuristics, and the venue is the wrong place to discover that.

## 8. Demo insurance

Work the checklist in `context/DEMO_SPEC.md`. In particular:

- record a **full backup demo video**, stored locally
- keep a pre-built `RoadTwin_Project.zip` on disk to open if live generation fails
- confirm the cached OSM, mosaic and vision outputs are committed

---

## Definition of Done

```
✓ Installed .exe runs the full benchmark end to end
✓ address -> confirm -> OSM -> model -> AI -> review -> accept
  -> .xodr -> SUMO -> closure -> metrics -> ZIP
✓ python scripts/selftest.py     0 failed
✓ python scripts/run_benchmark.py  significant: true
✓ backup video recorded
✓ demo rehearsed three times, timed
✓ a fresh machine can follow the README
```

**Do not claim completion until the full workflow has been executed from the
installed binary.** Record in `context/CURRENT_STATE.md`: the exact command,
the benchmark coordinates, the generated artifacts, the known limitations and
the build version.
