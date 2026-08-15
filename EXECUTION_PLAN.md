# RoadTwin — Execution Plan

Step-by-step, phase-wise, for one builder over five days.
Every step has a command or a check. Every day has a gate you do not pass
without.

**How to use this document.** Work top to bottom. When you reach a step marked
`▶ PROMPT`, open the named file in `prompts/` and give it to Claude Code
verbatim. Do not improvise the prompts — they encode the architectural
decisions in `context/DECISIONS.md`, and improvised prompts drift.

**The rule that matters most:** run `python scripts/run_benchmark.py` at the end
of every day. If it passes, you have a product. If it breaks, you broke it in
the last few hours and you know exactly where to look.

---

# DAY 0 — Prep (2–3 hours, the evening before)

Do not spend Day 1 morning on this. Every failure here costs minutes now and
hours later.

### 0.1 Install the toolchain

| Tool | Version | Note |
|---|---|---|
| Python | 3.11 or 3.12 | not 3.13 — wheel coverage is still patchy |
| Node.js | 20 LTS | for the Tauri frontend |
| Rust | stable | `rustup default stable` |
| MSVC Build Tools | 2022 | "Desktop development with C++" workload |
| WebView2 Runtime | current | usually already present on Win 11 |
| SUMO | 1.19+ | **set `SUMO_HOME`** |
| Git | any | — |

```powershell
setx SUMO_HOME "C:\Program Files (x86)\Eclipse\Sumo"
# open a NEW terminal, then:
netconvert --version
sumo --version
```

Full details in `SETUP.md`.

### 0.2 Create the environment

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-core.txt
```

### 0.3 Run the environment gate

```powershell
python scripts/verify_environment.py
python scripts/selftest.py
```

`verify_environment.py` must report zero FAIL. `selftest.py` must report
0 failed — it covers the georeferencing, evidence, metrics, edit and scenario
logic without needing SUMO or a network.

### 0.4 ★ Verify the benchmark location — the highest-leverage 45 minutes

This single check protects Days 2, 3, 4 and 5 simultaneously. Skip it and you
will discover on Day 4 that your headline demo moment is impossible.

Open your candidate location in an OSM tag inspector and confirm:

- [ ] the main road carries a `lanes` tag
- [ ] at least one real junction sits inside the AOI
- [ ] `maxspeed` present, or a sensible class default applies
- [ ] lane markings are clearly visible in satellite imagery at zoom 19

Then prove it mechanically:

```powershell
python scripts/run_benchmark.py --skip-sim
```

This fetches OSM, runs netconvert, emits the OpenDRIVE and verifies the
round-trip. Then **look at the network in netedit**:

```powershell
netedit projects\benchmark\sumo\network.net.xml
```

Are the junctions connected? Do the lane counts look plausible? A network that
looks wrong here will look wrong for five days.

> **If any of this fails, change the location, not the plan.**

### 0.5 Commit your demo insurance

```powershell
git add assets/benchmark/osm_*.osm
git commit -m "cache benchmark OSM extract"
```

Overpass rate-limits and venue wifi fails. This file is the difference between
a demo and an apology.

### 0.6 Record what you verified

Fill in the verification block in `context/DEMO_SPEC.md`.

### GATE 0

```
✓ verify_environment.py: 0 failures
✓ selftest.py: 0 failures
✓ run_benchmark.py --skip-sim produces network.net.xml + road_network.xodr
✓ network looks correct in netedit
✓ benchmark OSM extract committed
```

---

# DAY 1 — Walking skeleton + packaging proven

**Goal: an installed `.exe` that runs, and a headless script that produces real
SUMO numbers. No UI polish, no AI.**

The ordering here is deliberate and non-negotiable: **packaging first, while
you are fresh.** Packaging discovered broken on Day 5 ends the project.

### 1.1 Repository skeleton

```powershell
git init
mkdir apps\desktop
```

Copy this kit's `core/`, `vision/`, `scripts/`, `context/`, `config.py` into the
repo root.

### 1.2 ▶ PROMPT `prompts/day-01-skeleton.md`

Gives Claude Code: monorepo, Tauri 2 shell, React/TS frontend, FastAPI core
sidecar with `/health`, PyInstaller freeze, Tauri sidecar wiring, installer.

### 1.3 Freeze and wire the sidecar

```powershell
pyinstaller --onedir --name api --collect-all lxml core\main.py
# Tauri requires the target-triple suffix:
copy dist\api\api.exe apps\desktop\src-tauri\binaries\api-x86_64-pc-windows-msvc.exe
```

`src-tauri/tauri.conf.json`:

```json
{ "bundle": { "externalBin": ["binaries/api"] } }
```

### 1.4 Build and ACTUALLY INSTALL the installer

```powershell
cd apps\desktop
npm run tauri build
```

Then run the produced `.msi` / `.exe`, install it, launch the installed app,
and confirm `/health` responds. **Building is not the same as installing.**
Path resolution differs between `python main.py`, the frozen binary, and the
installed binary, and you want to find that out today.

### 1.5 The spine, headless

```powershell
python scripts/run_benchmark.py
```

This must complete and print real numbers. It already does everything the app
will do; the app is a UI on top of it.

### 1.6 Commit

```powershell
git add -A && git commit -m "day 1: walking skeleton, installer proven"
```

### GATE 1 — do not sleep until both are true

```
✓ The INSTALLED .exe launches and reaches the sidecar (/health -> ok)
✓ python scripts/run_benchmark.py prints real travel-time numbers
  and writes RoadTwin_Project_benchmark.zip
```

Gate 1 is the whole game. With it you have a project. Without it you have a repo.

---

# DAY 2 — Location gateway, acquisition, model, edit loop

### 2.1 ▶ PROMPT `prompts/day-02-location-osm.md`

### 2.2 Location gateway

- address input + lat/lon input
- geocoder behind a **swappable adapter** — real `User-Agent`, 1 req/s, cached
- MapLibre map — **verify tiles render before building anything on top**
- draggable marker with live coordinate readout
- "Open in Maps" via `tauri-plugin-opener` — **`shell.open` does not exist in
  Tauri 2**; this will cost you 20 confused minutes if you use v1 tutorials
- "Confirm Location" gate — nothing downstream runs unconfirmed
- persist `location.json`

### 2.3 Acquisition from the confirmed location

`core/acquire/overpass.py` is written and ready. Wire it to the confirmed
coordinates and the AOI radius. Cache by bbox.

### 2.4 The RoadTwin model

Build the Pydantic model per `context/DATA_CONTRACT.md`. The detail that
matters: **`lane_count_provenance`**. When OSM has no `lanes` tag, record
`inferred_default` with a low confidence rather than silently emitting a
number. This turns a data gap into your best demo beat (DEMO_SPEC beat 6).

### 2.5 The edit → recompile loop

Prove it end to end:

```powershell
python scripts/run_benchmark.py --edit-lanes 3
```

This applies a lane-count edit to the plain `.edg.xml`, recompiles, and
regenerates **both** `network.net.xml` and `road_network.xodr`. That single
funnel is why the twin never diverges.

### 2.6 Rebuild the installer

Every day. A packaging break found on Day 2 costs 30 minutes.

### GATE 2

```
✓ Address -> map -> confirm -> OSM downloaded -> model validates
✓ --edit-lanes 3 regenerates net.xml AND road_network.xodr
✓ run_benchmark.py still passes
✓ installer still builds
```

---

# DAY 3 — Simulation and experiment ★ THE CRITICAL DAY

By tonight every "never cut" item is done and everything after is upside.

### 3.1 ▶ PROMPT `prompts/day-03-simulation.md`

### 3.2 ★ Calibrate demand — the step people skip and regret

A lane closure on an empty road changes nothing. If you demo "42s vs 42s" the
project looks pointless, and that is a calibration failure, not a modelling one.

```powershell
# start here
python scripts/run_benchmark.py --seeds 1
```

Read the output. Then iterate on `SIM["period"]` in `config.py`:

| Symptom | Action |
|---|---|
| closure delta ≈ 0 | **lower** `period` (more traffic) |
| teleport warning appears | **raise** `period` — the network is gridlocked and the metrics are meaningless |
| baseline travel time barely above free-flow | lower `period` |
| delta 20–60% and no teleports | **stop, you are done** |

Two or three iterations is normal. **Write the final value into
`context/CURRENT_STATE.md` under CALIBRATION RECORD.** Losing it costs an hour.

### 3.3 Closure scenario

`core/sim/scenario.py` is written and tested. It generates a rerouter
additional-file — **the network is never modified** (ADR-006), so baseline and
closure share net, routes and seeds, and the delta is causal.

Note the honest limitation it enforces: SUMO closes a lane for the whole edge,
so `actual_closed_length_m` is the real edge length. Show that number, not a
made-up 150.

### 3.4 Run the experiment across seeds

```powershell
python scripts/run_benchmark.py
```

Five seeds, mean and standard deviation. `metrics.compare()` will tell you
whether the change exceeds seed noise. **If `significant` is false, you do not
have a result yet** — go back to 3.2.

### 3.5 Verify the OpenDRIVE

`run_benchmark.py` step 7 re-imports your own `.xodr` through netconvert. This
answers "is your OpenDRIVE actually valid?" with evidence rather than
assertion. Make sure it prints PASS.

### 3.6 Experiment UI

Road / lane / length selectors, RUN EXPERIMENT, comparison table with deltas
and the seed count. Explicit error when a lane cannot be closed — never a
fabricated experiment.

### 3.7 Export from the UI

### GATE 3 — GO / NO-GO. Be honest with yourself here.

```
✓ Baseline and closure both run from the UI
✓ Metrics differ MEANINGFULLY and reproducibly (significant == true)
✓ road_network.xodr re-imports cleanly
✓ Project ZIP exports from the UI
✓ CALIBRATION RECORD filled in
```

> **If Gate 3 fails tonight: stop all feature work. Spend Day 4 fixing it and
> Day 5 on polish and rehearsal. Ship with zero AI.**
>
> A twin that provably simulates beats one that detects traffic lights but
> cannot simulate. Losing the AI hurts; losing the simulation is fatal.

---

# DAY 4 — Visual evidence and human validation

### 4.1 ▶ PROMPT `prompts/day-04-vision-fusion.md`

### 4.2 Separate venv for vision (ADR-007)

```powershell
python -m venv .venv-vision
.venv-vision\Scripts\activate
pip install -r requirements-vision.txt
python -c "import torch; print(torch.cuda.is_available())"
```

Keep `torch` out of the frozen core binary. This is what keeps the installer at
~300 MB instead of 3–5 GB, and it makes "AI unavailable → continue with OSM"
structural rather than aspirational.

### 4.3 Georeferenced mosaic (audit item B2)

```powershell
$env:ROADTWIN_TILE_URL = "https://.../{z}/{x}/{y}.png"   # your chosen provider
```

`vision/tiles.py` is written and unit-tested — the pixel↔lon/lat round-trip is
accurate to 4e-09 px. **Persist the transform** into `source_manifest.json`.
Without it the mosaic is just a picture and none of the AI output can be
georeferenced.

Check the provider's terms and set a real `User-Agent`. Do not commit an API key.

### 4.4 SAM road mask — prompted with the OSM centerline

This is the trick that makes the vision phase work. Do not ask SAM to segment
everything and then guess which blob is the road: project the OSM centerline
into mosaic pixel coordinates with `Mosaic.lonlat_to_pixel` and feed those
points as positive prompts.

```python
from vision.segment import segment_road
mask = segment_road("mosaic.png", centerline_px)
```

Sanity checks are built in — the module warns if the mask covers >75% (SAM
segmented the whole scene) or <1% (the centerline is not landing on the road,
so your transform is wrong).

### 4.5 Lane-count evidence — your quantitative claim

```python
from vision.evidence import lane_count_evidence, make_observation
ev = lane_count_evidence(mask, centerline_px, mosaic.meters_per_pixel())
obs = make_observation("obs-001", ev, road_id="rt-road-007")
```

Measures mask width perpendicular to the centerline, converts pixels to metres,
divides by 3.5. Returns `None` rather than guessing when there is not enough
evidence — that refusal is a feature.

### 4.6 Street-level detection (optional, image-space only)

```python
from vision.detect import detect, to_observations
dets = detect("site_photo.jpg", VISION["dino_prompt_street"])
obs = to_observations(dets, road_id="rt-road-007", image_name="site_photo.jpg")
```

Every detection is tagged `geometry_kind: "image_space"`. No coordinate is
claimed. That one field pre-empts the sharpest question a technical judge can
ask.

### 4.7 Fusion and the review queue

Deterministic. `build_review_items()` compares evidence against baseline and
emits REVIEW (disagreement) or AGREEMENT (corroboration — show it, it is
evidence too). Observations are immutable; rejecting sets status, never deletes.

### 4.8 Accept → recompile → re-simulate

Accepting a review item creates an `Edit`, which flows through `apply_edits()`
→ `plain_to_net()` → new net, new `.xodr`, new simulation. Prove the whole
chain with the replay test:

```powershell
python scripts/selftest.py     # includes REPLAY: baseline + report == final model
```

### 4.9 Cache everything

Mask, detections, mosaic, into `assets/benchmark/`. Demo insurance.

### GATE 4

```
✓ A real discrepancy appears in the review queue
✓ Accepting it changes the model, net.xml, .xodr AND the simulation result
✓ Killing the vision sidecar degrades to [ Continue with OSM ] without crashing
✓ validation_report.json replays to the same final model
```

Gate 4's second line is the money shot: **the engineer accepts a piece of AI
evidence and the traffic numbers change.** Rehearse that transition
specifically.

---

# DAY 5 — Polish, package, rehearse

**No new features. None.**

### 5.1 ▶ PROMPT `prompts/day-05-package.md`

### 5.2 2D map polish

Lane overlays, review markers, confidence colouring. No 3D (ADR-012) — a
rushed three.js scene looks worse than a good 2D map and costs four times as
much.

### 5.3 Progress state machine

```
IDLE  LOCATING  ACQUIRING  BUILDING  ANALYZING  REVIEW_REQUIRED
VALIDATING  EXPORTING  SIMULATING  COMPLETE  FAILED
```

### 5.4 Error handling pass

Never fail silently. Never substitute a plausible number for a missing one.
Walk every failure row in `context/ARCHITECTURE.md` and confirm the behaviour.

### 5.5 Notebooks

```powershell
jupyter lab notebooks/
```

Two, both thin — they import `core/` and `vision/` rather than reimplementing
anything. `01_pipeline_walkthrough.ipynb` is the engineering story;
`02_final_demo.ipynb` reproduces the benchmark.

### 5.6 Documentation

- top-level `README.md` with SUMO stated as a prerequisite
- `KNOWN LIMITATIONS` written honestly (see CURRENT_STATE.md)
- `CURRENT_STATE.md` completed: exact command, coordinates, artifacts, version

### 5.7 Final installer on a clean machine

```powershell
cd apps\desktop && npm run tauri build
```

Install it somewhere that has never seen the source. Then whitelist it in
SmartScreen/antivirus on the demo machine — an unsigned PyInstaller binary
frequently trips heuristics, and you do not want to discover that at the venue.

### 5.8 ★ Record the backup demo video

Full run, stored locally, not in the cloud. This has saved more hackathon
projects than any technical decision.

### 5.9 ★ Rehearse three times, timed

Follow the beat table in `context/DEMO_SPEC.md`. Rehearse beats 9→12
specifically — accept evidence, watch the numbers move.

### GATE 5 — Definition of Done

```
✓ Installed .exe runs the full benchmark end to end
✓ Address -> confirm -> OSM -> model -> AI -> review -> accept
  -> .xodr -> SUMO -> closure -> metrics -> ZIP
✓ Backup video recorded
✓ Demo rehearsed three times
✓ CURRENT_STATE.md complete and honest
✓ A fresh machine can follow the README
```

---

# If you fall behind — cut in this order

```
1. Notebooks                          documentation, not product
2. Street-level object detection      keep SAM lane evidence: it is the
                                      quantitative claim
3. Map visual polish                  functional map is enough
4. Geocoding                          manual lat/lon still works
5. Multi-seed averaging               single fixed seed, disclosed

NEVER CUT, in priority order:
  1. Location confirmation
  2. OSM baseline acquisition
  3. RoadTwin canonical model
  4. OpenDRIVE export
  5. SUMO baseline
  6. Lane-closure experiment with real metrics
  7. Project export
```

3D is not on this list because it is never started.

---

# Daily rhythm

```
morning    read context/CURRENT_STATE.md
           run scripts/selftest.py
           ▶ give Claude Code the day's prompt

during     after each meaningful change:  python scripts/selftest.py

evening    python scripts/run_benchmark.py
           rebuild the installer
           update context/CURRENT_STATE.md
           git commit
           check the day's GATE before you sleep
```
