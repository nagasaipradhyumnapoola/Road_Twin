# RoadTwin — FINAL EXECUTION PLAN

**Phase-wise, end-to-end, feasibility-first.**
One builder · 5 days · Windows `.exe` required · NVIDIA GPU available · greenfield.

> This document supersedes `EXECUTION_PLAN.md`. It is the single thing you work
> from. Everything else in the repo is reference material this points at.

---

# 0. THE FEASIBILITY CONTRACT

Read this once, agree with yourself, then stop renegotiating it at 2am on Day 4.

## What ships

| In | Why it survives |
|---|---|
| Location confirmation gateway | The credibility beat; cheap |
| OSM acquisition + cache | Foundation of everything |
| RoadTwin canonical model + provenance | The engineering story |
| Edit → recompile loop | Proves the twin is editable, not a picture |
| OpenDRIVE export (via netconvert) | Interoperability claim, ~free |
| SUMO baseline + lane closure + real metrics | **The proof. Non-negotiable.** |
| SAM 2.1 lane-count evidence | The differentiator, and it's measurable |
| Human review + accept/reject + audit trail | The design commitment |
| Project ZIP export | The takeaway artifact |
| Windows installer | You made this a hard requirement |

## What does not ship, by decision

| Out | Reason |
|---|---|
| Hand-written OpenDRIVE compiler | 2–3 days, silent failure mode. netconvert does it. |
| 3D view | Rushed 3D looks worse than good 2D at 4× the cost |
| Pothole detection | Open-vocab models can't do it; demoing it invites embarrassment |
| Six notebooks | Two, thin. The rest is duplicated logic that rots. |
| GDAL / Rasterio / GeoPandas / NetworkX / OSMnx in runtime | Never load-bearing; worst libraries to freeze |
| SQLite / PostGIS | Folders and JSON. Inspectable in front of a judge. |
| Video, temporal fusion, LLM control, multi-scenario | Not the first vertical slice |
| Bundling SUMO | Hundreds of MB and a licence notice for zero demo benefit |

## The three rules that make this fit in 5 days

1. **netconvert is the compiler.** You never write OpenDRIVE. (ADR-003)
2. **Vertical before horizontal.** The whole spine runs headless on Day 1;
   every later phase replaces a stub, never adds an unproven layer.
3. **Ship the installer on Day 1 and rebuild it nightly.** Packaging found
   broken on Day 5 ends the project.

## Hour budget

Assumes ~12 working hours/day, solo, with Claude Code.

| Phase | Hours | Cumulative | Day |
|---|---:|---:|---|
| P0 Ground | 3 | 3 | Day 0 (evening) |
| P1 Shipping path | 5 | 8 | Day 1 AM |
| P2 Spine | 6 | 14 | Day 1 PM |
| P3 Location gateway | 5 | 19 | Day 2 AM |
| P4 Baseline model | 6 | 25 | Day 2 PM |
| P5 Compile & calibrate | 5 | 30 | Day 3 AM |
| P6 The experiment | 6 | 36 | Day 3 PM ★ |
| P7 Visual evidence | 6 | 42 | Day 4 AM |
| P8 Fusion & validation | 5 | 47 | Day 4 PM |
| P9 Package & demo | 10 | 57 | Day 5 |
| **Slack** | **3** | **60** | — |

Three hours of slack across five days. That is why the cut rules in each phase
are not decorative.

---

# 1. PHASE MAP

```
P0 GROUND ─────────────────── env + benchmark verified
     │
P1 SHIPPING PATH ──────────── .exe installs and runs        ┐
     │                                                       │ Day 1
P2 SPINE ──────────────────── headless E2E produces metrics ┘
     │
P3 LOCATION ───────────────── confirm gate + map            ┐ Day 2
     │                                                       │
P4 BASELINE MODEL ─────────── OSM → RoadTwin → edit loop    ┘
     │
P5 COMPILE & CALIBRATE ────── net.xml + .xodr + demand      ┐ Day 3
     │                                                       │
P6 THE EXPERIMENT ─────────── closure vs baseline, metrics  ┘ ★ CORE DONE
     │
     ├──── everything below is UPSIDE. If P6 slips, cut here.
     │
P7 VISUAL EVIDENCE ────────── georef mosaic → SAM → lanes   ┐ Day 4
     │                                                       │
P8 FUSION & VALIDATION ────── review → accept → re-simulate ┘
     │
P9 PACKAGE & DEMO ─────────── installer, docs, rehearsal      Day 5
```

**The single most important line in this document:**
if P6 is not green by the end of Day 3, you stop building features and ship
without AI. A twin that provably simulates beats one that detects traffic
lights but cannot simulate.

---

# PHASE 0 — GROUND

**3 h · Day 0 evening · Blocks everything**

## Objective
Prove the toolchain works and the benchmark location can support the demo,
before a single line of product code exists.

## Steps

**0.1 Install** (see `SETUP.md` for detail)

```
Python 3.11/3.12 · Node 20 · Rust stable · MSVC Build Tools 2022
WebView2 · SUMO 1.19+ · Git
```

```powershell
setx SUMO_HOME "C:\Program Files (x86)\Eclipse\Sumo"
# OPEN A NEW TERMINAL -- setx does not affect the current one
netconvert --version
sumo --version
```

**0.2 Environment**

```powershell
cd Road_Twin
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-core.txt
python scripts/selftest.py               # expect 83 passed, 0 failed
python scripts/verify_environment.py     # expect 0 FAIL
```

`selftest.py` needs neither SUMO nor network. If it fails, your checkout is
broken — fix that before anything else.

**0.3 ★ Verify the benchmark — the highest-leverage 45 minutes in the project**

Set candidate coordinates in `config.py` → `BENCHMARK`, then:

```powershell
python scripts/run_benchmark.py --skip-sim
netedit projects\benchmark\sumo\network.net.xml
```

Confirm, by looking:

- [ ] main road carries an OSM `lanes` tag
- [ ] at least one real junction inside the AOI
- [ ] **junctions are connected in netedit** (look, don't assume)
- [ ] at least one multi-lane edge ≥ 100 m for the closure
- [ ] lane markings visible in satellite imagery at zoom 19

**0.4 Commit demo insurance**

```powershell
git add assets/benchmark/osm_*.osm
git commit -m "cache benchmark OSM extract"
git push
```

**0.5** Fill the verification block in `context/DEMO_SPEC.md`.

## DONE WHEN
```
✓ selftest 83/83          ✓ verify_environment 0 FAIL
✓ --skip-sim produces network.net.xml + road_network.xodr
✓ junctions connected in netedit
✓ benchmark OSM committed
```

## IF IT FAILS
**Change the location, not the plan.** Ten minutes relocating beats two days
fighting bad source data. Candidate evaluation prompt is in
`prompts/day-00-setup.md` §3.

---

# PHASE 1 — SHIPPING PATH

**5 h · Day 1 AM · Do this first, while fresh**

## Objective
An installed `.exe` that launches and talks to the Python sidecar. No features.

Packaging first is deliberate. Tauri + PyInstaller pain is all in the *first*
successful build: hidden imports, data files, path resolution differing between
`python main.py`, the frozen binary, and the installed binary. Find that today,
when it costs 30 minutes.

## Steps

**1.1** ▶ `prompts/day-01-skeleton.md`

**1.2** Scaffold `apps/desktop` — Tauri 2 + React + TS + Vite. Window opens.

**1.3** `core/main.py` — FastAPI, `GET /health` → `{"status":"ok","sumo":<bool>}`

Dependencies are **exactly** the seven in `requirements-core.txt`. Adding an
eighth is how a 300 MB installer becomes a 3 GB one that fails to build.

**1.4** Freeze

```powershell
pyinstaller --onedir --name api --collect-all lxml core\main.py
copy dist\api\api.exe apps\desktop\src-tauri\binaries\api-x86_64-pc-windows-msvc.exe
```

`tauri.conf.json` → `"bundle": { "externalBin": ["binaries/api"] }`

The target-triple suffix is mandatory; Tauri will not find the sidecar without it.

**1.5** Build **and install**

```powershell
cd apps\desktop
npm run tauri build
```

Then run the produced installer, install it, launch the installed app, confirm
`/health` responds. **Building ≠ installing.**

## DONE WHEN
```
✓ The INSTALLED .exe launches and reaches the sidecar
```

## CUT IF LATE
Nothing. This phase has no fat. If it overruns past 6 h, the problem is a
specific PyInstaller error — take it to Claude Code with the full traceback
rather than trying variations.

---

# PHASE 2 — SPINE

**6 h · Day 1 PM · The phase that decides whether you have a project**

## Objective
`scripts/run_benchmark.py` runs the entire pipeline headless and prints real
SUMO numbers. Hardcoded location, no UI, no AI.

This script already exists and is written. This phase is about making it *run
on your machine* and understanding it, because from here on it is your
regression test, your demo backup, and your evidence to judges that the
pipeline is real.

## The spine

```
location (hardcoded) → Overpass → benchmark.osm
  → netconvert → plain XML → netconvert → net.xml + road_network.xodr
  → randomTrips → routes.rou.xml
  → sumo baseline → sumo closure → tripinfo/queue/summary
  → metrics.json → RoadTwin_Project.zip
```

## Steps

```powershell
python scripts/run_benchmark.py
```

Work every error to root cause. Expected first-run issues, in likelihood order:

| Error | Cause | Fix |
|---|---|---|
| `SUMO_HOME is not set` | new terminal not opened | open a new terminal |
| empty network | AOI has no drivable roads | widen `aoi_radius_m`, or move benchmark |
| `no multi-lane edge` | location can't support a closure | move benchmark (P0 should have caught this) |
| randomTrips fails | wrong python, or tools path | it uses `sys.executable`; check `$SUMO_HOME\tools` |
| 0 vehicles completed | demand too low or routes invalid | lower `SIM["period"]`; check `--ignore-route-errors` output |

Then read the output. You should see edges, lanes, a closure candidate, a
metrics table, and a zip path.

## DONE WHEN
```
✓ run_benchmark.py completes
✓ prints real travel-time numbers (not None, not zeros)
✓ writes RoadTwin_Project_benchmark.zip
✓ OpenDRIVE round-trip prints PASS
```

## GATE 1 — do not sleep until P1 and P2 are both green
With them you have a project. Without them you have a repo.

## CUT IF LATE
If the closure delta is zero, ignore it for now — calibration is P5. You need
the pipeline to *run*, not to be interesting, tonight.

---

# PHASE 3 — LOCATION GATEWAY

**5 h · Day 2 AM**

## Objective
Address or lat/lon → map → drag → confirm. Nothing downstream runs unconfirmed.

## Steps

**3.1** ▶ `prompts/day-02-location-osm.md` (location half)

**3.2 Verify map tiles render FIRST.** MapLibre ships no map data. Get a grey
rectangle out of the way before building marker logic on top of it.

**3.3** Build:

- address input + lat/lon input
- geocoder **behind an adapter** — real `User-Agent`, 1 req/s, cached
- draggable marker, live coordinate readout
- **"Open in Maps" via `tauri-plugin-opener`** — Tauri 2 has no `shell.open`;
  every v1 tutorial online will waste 20 minutes of your life here
- explicit "Confirm Location"
- persist `location.json`

**3.4** Enforce the gate **in the backend**, not just the UI. A confirmed
location is a precondition, not a UI convention.

## DONE WHEN
```
✓ address → map → drag marker → confirm → location.json written
✓ invalid address handled; manual lat/lon still works
✓ backend rejects downstream calls without confirmation
```

## CUT IF LATE
Geocoding. Manual lat/lon entry alone still gives you the whole demo beat —
the engineer confirming the site is the point, not the address lookup.

---

# PHASE 4 — BASELINE MODEL

**6 h · Day 2 PM**

## Objective
Confirmed location → OSM → canonical RoadTwin model → working edit loop.

## Steps

**4.1** Wire `core/acquire/overpass.py` to the confirmed coordinates + AOI
radius. Cache by bbox.

**4.2** Build the Pydantic model per `context/DATA_CONTRACT.md`:
Road / Lane / Junction / Object / Observation, stable ids, provenance.

**4.3 ★ `lane_count_provenance` — do not skip this**

Indian OSM roads frequently have no `lanes` tag. When absent, apply a
road-class default and record:

```json
{"source": "inferred_default", "rule": "highway=trunk -> 2 lanes", "confidence": 0.4}
```

Never emit a lane count as though OSM supplied it. This converts a data gap
into your strongest demo beat: *"OSM has no lane data here. We inferred 2, and
we say so. Vision measured 3."* That is the real problem Indian road engineers
have, and showing it is better than pretending it doesn't exist.

**4.4** Emit `roads.geojson` + `junctions.geojson` for the map — one call each,
`core/model/geometry.py` handles the projection:

```python
from core.model.geometry import edges_to_geojson, junctions_to_geojson
roads = edges_to_geojson(net_file, properties=per_edge_props)
juncs = junctions_to_geojson(net_file)
```

A SUMO network stores **projected metres offset by `netOffset`**, so it cannot
be fed to MapLibre directly. `NetGeo` is the single conversion point — do not
re-implement it anywhere else (ADR-014). Check `_georeferencing` in the output:
`"exact (pyproj)"` is what you want; `"boundary interpolation"` means pyproj
isn't installed.

**4.5** Prove the edit loop:

```powershell
python scripts/run_benchmark.py --edit-lanes 3
```

`apply_edits()` rewrites `plain.edg.xml` → one `plain_to_net()` call →
**both** `network.net.xml` and `road_network.xodr` regenerate. That single
funnel is why the twin never diverges.

**4.6** Rebuild the installer. Every day.

## DONE WHEN
```
✓ roadtwin.json validates, every entity has a stable id
✓ every lane_count carries lane_count_provenance
✓ --edit-lanes 3 regenerates net.xml AND road_network.xodr
✓ run_benchmark.py still passes
```

## CUT IF LATE
Junction connection detail and the `objects` array. Roads + lanes + provenance
carry the demo.
---

# PHASE 5 — COMPILE & CALIBRATE

**5 h · Day 3 AM**

## Objective
A network worth simulating, and demand that makes the closure matter.

## Steps

**5.1** ▶ `prompts/day-03-simulation.md`

**5.2 ★ Calibrate demand — the step people skip and regret on stage**

A lane closure on an empty road changes nothing. "42 s baseline, 42 s closure"
makes the whole project look pointless — and that is a *calibration* failure,
not a modelling failure.

```powershell
python scripts/run_benchmark.py --seeds 1     # fast iteration
```

Tune `SIM["period"]` in `config.py`. Lower period = more traffic.

| Symptom | Action |
|---|---|
| closure delta ≈ 0 | **lower** period |
| teleport warning in metrics | **raise** period — network is gridlocked, numbers meaningless |
| baseline barely above free-flow | lower period |
| delta 20–60%, no teleports | **stop. calibrated.** |

Target ~75–85% of corridor capacity. Two or three iterations is normal.

**Write the final value into `context/CURRENT_STATE.md` → CALIBRATION RECORD**,
with vehicle counts and baseline travel time. Losing it costs an hour.

**5.3** Confirm the OpenDRIVE round-trip prints PASS. This turns "is your
OpenDRIVE valid?" from an assertion into evidence.

## DONE WHEN
```
✓ period recorded; delta 20-60%; zero teleport warnings
✓ OpenDRIVE round-trip PASS
```

## CUT IF LATE
Drop to 3 seeds instead of 5. Do **not** drop to 1 — a single seed makes your
headline number an anecdote, and a judge asking "did you re-run the baseline?"
will expose it.

---

# PHASE 6 — THE EXPERIMENT ★ CORE COMPLETE

**6 h · Day 3 PM · This is the phase the project is judged on**

## Objective
Baseline vs lane closure, from the UI, with real metrics and honest framing.

## Why it's built this way

The closure is a **rerouter additional-file**, not a network edit. Both runs
load the identical network, identical routes and identical seeds — the only
variable is the closure, so the delta is **causal**. Rebuilding the network to
remove a lane would change edge ids and destroy the comparison.

```xml
<rerouter id="rr_closure" edges="UPSTREAM CLOSED">
  <interval begin="300" end="3600">
    <closingLaneReroute id="CLOSED_2" allow="authority"/>
  </interval>
</rerouter>
```

`--device.rerouting.probability 1` is already set in `core/sim/run.py`. Without
it vehicles cannot respond to the closure at all.

## Honest limitation, surfaced not hidden

SUMO closes a lane for a **whole edge**. There is no partial-length closure.
So the UI reports `actual_closed_length_m` — the real edge length. Claiming
"150 m" when you closed a 340 m edge is the kind of detail that unravels under
questioning.

## Steps

**6.1** Experiment UI: road selector, lane selector, length display (read-only,
from the network), RUN EXPERIMENT.

**6.2** Comparison table with deltas and the seed count visible.

**6.3** Explicit error when a lane cannot be closed — single-lane edge,
out-of-range index, unknown edge. `core/sim/scenario.py` already raises on all
three. **Never a fabricated experiment.**

**6.4** Respect `comparison.significant`. When false, the UI says so. Do not
present seed noise as a finding.

**6.5** Export `RoadTwin_Project.zip` from the UI.

## Expected shape

```
                        BASELINE      CLOSURE      DELTA
Average travel time        42.1s        56.4s      +34.0%
Queue length               18.2m        47.6m     +161.5%
Completed vehicles           102           97       -4.9%
mean of 5 seeds | Closure produced a change larger than seed-to-seed variation.
```

## GATE 2 — GO / NO-GO. Be honest with yourself.
```
✓ baseline and closure both run FROM THE UI
✓ significant == true, reproducibly
✓ closing a single-lane edge shows a clear error
✓ ZIP exports from the UI
✓ CALIBRATION RECORD filled in
```

## ★ IF GATE 2 FAILS TONIGHT

Stop all feature work. Spend Day 4 fixing it and Day 5 on polish and rehearsal.
**Ship with zero AI.** See §MINIMUM SHIPPABLE at the end of this document.

---

# PHASE 7 — VISUAL EVIDENCE

**6 h · Day 4 AM · Upside only. Only start if Gate 2 is green.**

## Objective
Georeferenced imagery → SAM road mask → a measurable lane-count claim.

## Steps

**7.1** ▶ `prompts/day-04-vision-fusion.md`

**7.2 Separate venv** (ADR-007) — keeps `torch` out of the frozen core binary.

```powershell
python -m venv .venv-vision
.venv-vision\Scripts\activate
pip install -r requirements-vision.txt
python -c "import torch; print(torch.cuda.is_available())"
```

**7.3 ★ Georeferenced mosaic — the step everything else depends on**

SAM returns pixels. Grounding DINO returns pixels. GeoJSON needs degrees. That
conversion exists **only** because you build the image yourself from XYZ tiles
and keep the transform.

```powershell
$env:ROADTWIN_TILE_URL = "https://.../{z}/{x}/{y}.png"
```

`vision/tiles.py` is written and unit-tested — pixel↔lon/lat round-trips to
4e-09 px. Persist `mosaic.to_dict()` into `source_manifest.json`. Without it
the mosaic is just a picture again.

Check your provider's terms, set a real `User-Agent`, never commit a key.

**7.4 ★ Prompt SAM with the OSM centerline**

Do not ask SAM to segment everything and then guess which blob is the road.
You already know where the road is. Project the centerline into pixel space
with `Mosaic.lonlat_to_pixel()` and feed those points as positive prompts.

This one change is the difference between a usable mask and an afternoon of
disappointment.

```python
from core.model.geometry import NetGeo, edge_centerline_lonlat, densify_lonlat
from vision.segment import segment_road

geo    = NetGeo(net_file)
line   = edge_centerline_lonlat(net_file, edge_id, geo=geo)
line   = densify_lonlat(line, every_m=10.0)     # see below -- do not skip
px     = [mosaic.lonlat_to_pixel(lon, lat) for lon, lat in line]
mask   = segment_road("mosaic.png", px)
```

**Why `densify_lonlat` matters:** netconvert's `--geometry.remove` collapses a
straight road to two shape points. Feeding SAM two prompts for a 300 m road
gives you a poor mask. Densifying to a point every 10 m gives it coverage —
in the test fixture this turns 2 points into 127.

Built-in sanity warnings fire if the mask covers >75% (SAM segmented the whole
scene) or <1% (your transform is wrong).

**7.5 Lane-count evidence — the quantitative claim**

```python
from vision.evidence import lane_count_evidence, make_observation
ev  = lane_count_evidence(mask, centerline_px, mosaic.meters_per_pixel())
obs = make_observation("obs-001", ev, road_id="rt-road-007")
```

Measures mask width perpendicular to the centerline → metres → ÷ 3.5.
Returns `None` when evidence is insufficient. **Preserve that refusal** — a
confident lane count from three noisy samples is how a demo gets taken apart.

**7.6 Street-level detection (optional)**

`transformers` Grounding DINO, lowercase period-separated prompt, every
detection tagged `geometry_kind: "image_space"` with no coordinate claimed.
No pothole class.

**7.7** Cache mosaic, mask and detections into `assets/benchmark/`.

## DONE WHEN
```
✓ mosaic transform persisted
✓ SAM mask covers the road, not the scene
✓ lane_count_evidence returns a plausible value with a sane confidence
```

## CUT IF LATE
Drop 7.6 entirely. **Keep 7.5** — the SAM lane measurement is the quantitative
claim; the street-level object boxes are decoration by comparison.

---

# PHASE 8 — FUSION & VALIDATION

**5 h · Day 4 PM**

## Objective
Evidence becomes a question. The engineer answers it. The answer is recorded
and replayable.

## The design commitment

> AI produces evidence. The engineer decides. Every decision is recorded.

An AI road builder that is wrong 15% of the time is unusable. An AI evidence
generator that is right 85% of the time, behind a human gate, is valuable.

## Steps

**8.1** Deterministic fusion via `build_review_items()`:
disagreement → REVIEW, agreement → AGREEMENT (show it; corroboration is
evidence), low confidence → filtered.

**8.2** Observations are **immutable**. Rejecting sets `status`, never deletes.

**8.3** Review UI:

```
ROAD FEATURE — lane count

OSM:      no data   (inferred: 2, confidence 40%)
VISION:   3 lanes   (mask width 10.8 m / 3.5 m, confidence 82%)

[ ACCEPT VISION ]   [ KEEP BASELINE ]   [ EDIT ]
```

**8.4 ★ Accept → recompile → re-simulate**

Accept creates an `Edit` → `apply_edits()` → `plain_to_net()` → new net, new
`.xodr`, new simulation result.

**This is the money shot of the entire demo:** the engineer accepts a piece of
AI evidence and the traffic numbers change. Rehearse this transition
specifically — it is what makes the twin feel real rather than decorative.

**8.5** Write `validation_report.json`. The invariant
`baseline plain XML + decisions == final model` is tested by `edits.replay()`
and covered in `selftest.py`. Do not break it.

**8.6** Graceful degradation: kill the vision sidecar mid-session and confirm
the UI shows `[ Continue with OSM ]` and proceeds.

## DONE WHEN
```
✓ a real discrepancy appears in the review queue
✓ accepting it changes the model, net.xml, .xodr AND the metrics
✓ rejecting preserves the observation with status REJECTED
✓ validation_report replays to the same final model
✓ killing the vision sidecar degrades without crashing
```

## CUT IF LATE
The EDIT action. ACCEPT and KEEP BASELINE carry the story; free-text editing
does not.

---

# PHASE 9 — PACKAGE & DEMO

**10 h · Day 5 · No new features. None.**

## Steps

**9.1** ▶ `prompts/day-05-package.md`

**9.2** 2D map polish: lane overlays, review markers, confidence colouring.
No 3D.

**9.3** Progress state machine wired to the UI:

```
IDLE  LOCATING  ACQUIRING  BUILDING  ANALYZING  REVIEW_REQUIRED
VALIDATING  EXPORTING  SIMULATING  COMPLETE  FAILED
```

**9.4** Error-handling pass. Walk every row of the failure table in
`context/ARCHITECTURE.md`. Never fail silently; never substitute a plausible
number for a missing one.

**9.5** Two thin notebooks — they import `core/` and `vision/`, never
reimplement.

**9.6** Docs: README with SUMO as a stated prerequisite; KNOWN LIMITATIONS
written honestly; `CURRENT_STATE.md` completed with the exact working command,
coordinates, artifacts and build version.

**9.7** Final installer, verified on a machine that has never seen the source.
Whitelist it in SmartScreen/antivirus on the demo machine — unsigned
PyInstaller binaries trip heuristics, and the venue is the wrong place to learn
that.

**9.8 ★ Record the full backup demo video.** Locally, not in the cloud. This
has saved more hackathon projects than any technical decision.

**9.9 ★ Rehearse three times, timed.** Follow the beat table in
`context/DEMO_SPEC.md`. Rehearse beats 9→12 specifically.

## DEFINITION OF DONE
```
✓ installed .exe runs the full benchmark end to end
✓ address → confirm → OSM → model → AI → review → accept
  → .xodr → SUMO → closure → metrics → ZIP
✓ selftest 83/83 · run_benchmark significant == true
✓ backup video recorded
✓ rehearsed three times
✓ a fresh machine can follow the README
```

---

# 2. RISK REGISTER — TRIGGERS AND RESPONSES

Pre-decided, so you are not making judgement calls while tired.

| Trigger | Response |
|---|---|
| P1 not green by end of Day 1 AM | Take the exact PyInstaller/Tauri error to Claude Code. Do not try variations blindly. |
| P2 not green by end of Day 1 | **Sacrifice Day 2 AM.** Nothing else matters until the spine runs. |
| Overpass rate-limits | `--offline`; the cached extract is committed |
| netconvert gives an empty network | Widen `aoi_radius_m`; if still empty, move the benchmark |
| Junctions disconnected in netedit | Move the benchmark. Do not try to fix OSM. |
| Closure delta ≈ 0 | Lower `SIM["period"]`. This is P5, not a bug. |
| Teleport warnings | Raise `period`. Metrics are describing gridlock, not congestion. |
| **Gate 2 red at end of Day 3** | **Cut P7+P8. Ship without AI.** See below. |
| SAM mask covers whole image | Reduce `max_points`; verify the centerline projection |
| SAM mask nearly empty | Your transform is wrong. Re-check `lonlat_to_pixel`. |
| torch install fights CUDA | Fall back to CPU. `-tiny` models. It is slower, not broken. |
| Installer breaks on Day 5 | You have nightly installers. Ship the last good one. |
| Venue wifi dead | Everything cached. This is why P0.4 exists. |
| Live demo fails on stage | Play the backup video. Keep talking. |

---

# 3. THE CUT LADDER

When you are behind, cut **in this order**, without renegotiating:

```
1. Notebooks                      documentation, not product
2. Street-level object detection  keep the SAM lane measurement
3. Map visual polish              functional map is enough
4. Geocoding                      manual lat/lon still works
5. EDIT action in review          accept/reject carries the story
6. Multi-seed averaging           3 seeds, never 1, and disclose it
7. ── everything above the line is optional ──────────────────
8. ALL of P7 + P8 (the AI layer)  ship the deterministic twin
```

**NEVER CUT, in priority order:**

```
1. Location confirmation
2. OSM baseline acquisition
3. RoadTwin canonical model
4. OpenDRIVE export
5. SUMO baseline
6. Lane-closure experiment with real metrics
7. Project export
```

3D is not on this ladder because it is never started.

---

# 4. MINIMUM SHIPPABLE

If everything goes wrong, this is still a strong SIH submission — and it is
what Gate 2 guarantees you have by the end of Day 3:

> An installed Windows application where an engineer confirms a real Indian
> road location, the system acquires OSM, builds a canonical road model with
> full provenance including honest flags where OSM data is missing, compiles it
> to a valid OpenDRIVE file and a SUMO network, runs a controlled lane-closure
> experiment across five seeds, reports travel time, queue length and completed
> vehicles with a significance check, and exports the whole thing as an
> auditable project package.

No AI in that sentence, and it still answers the problem statement. The AI
layer makes it *better*; it is not what makes it *valid*. Internalise that now,
so that if Day 4 goes badly you cut cleanly instead of panicking.

---

# 5. DAILY RHYTHM

```
MORNING    read context/CURRENT_STATE.md
           python scripts/selftest.py
           ▶ paste prompts/master.md + the phase prompt into Claude Code

DURING     after every meaningful change: python scripts/selftest.py

EVENING    python scripts/run_benchmark.py
           rebuild the installer
           update context/CURRENT_STATE.md
           git commit && git push
           check the phase gate BEFORE you sleep
```

---

# 6. WHAT TO SAY WHEN ASKED

**"Isn't this just netconvert?"**
netconvert is our compiler backend, the way LLVM is a compiler backend. The
contribution is the layer above it: georeferenced evidence, a human validation
gate, and a provenance chain from OSM tag to simulation result. Rewriting a
mature compiler would have been the least novel and most fragile part of the
system.

**"How do you know the AI is right?"**
We don't, and the architecture assumes we don't. Model output is never
committed silently — it creates a review item with a confidence score, and the
human decision is authoritative and recorded. That is the design, not a
limitation.

**"Why does a lane closure matter?"**
It is the smallest experiment that proves the model is simulation-grade rather
than a picture. Same network, same demand, same seeds — the only variable is
the closure, so the delta is causal.

**"What was genuinely hard?"**
Georeferencing visual evidence so it can be compared against map data at all,
and keeping an auditable chain from OSM tag to simulation result. Most of the
code exists to make the second one true.

**"What doesn't it do?"**
Answer from KNOWN LIMITATIONS, without hedging. Signals aren't in the
OpenDRIVE export — they're in the SUMO network and the model. Street-level
detections are image-space only. Demand is synthetic, not field-calibrated.
One scenario type. A team that knows its own limits reads as competent.

---

# 7. QUICK REFERENCE

```powershell
# tests -- no SUMO, no network, ~2 seconds. Run constantly.
python scripts/selftest.py

# environment gate
python scripts/verify_environment.py

# full pipeline
python scripts/run_benchmark.py
python scripts/run_benchmark.py --offline        # cached OSM
python scripts/run_benchmark.py --skip-sim       # build only
python scripts/run_benchmark.py --seeds 1        # fast calibration loop
python scripts/run_benchmark.py --edit-lanes 3   # simulate an accepted correction

# installer
cd apps\desktop && npm run tauri build

# inspect the network
netedit projects\benchmark\sumo\network.net.xml
```

| Need | File |
|---|---|
| What we're building | `context/PROJECT_CONTEXT.md` |
| How it fits together | `context/ARCHITECTURE.md` |
| Schemas | `context/DATA_CONTRACT.md` |
| Why decisions were made | `context/DECISIONS.md` (13 ADRs) |
| Current truth | `context/CURRENT_STATE.md` |
| Benchmark + demo script | `context/DEMO_SPEC.md` |
| Environment install | `SETUP.md` |
| Claude Code constraints | `prompts/master.md` |

---

**Start now: Phase 0, step 0.1. Do not read further until `selftest.py` shows
83 passed.**
