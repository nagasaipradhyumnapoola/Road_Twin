# DEMO_SPEC

The exact thing that must work, in the exact order it will be shown.

---

## Benchmark

```
Location        (set in config.py BENCHMARK)
Default         GST Road, Chennai — 12.8231, 80.0442
AOI radius      500 m
```

### Day 0 verification — do this before anything is built

The benchmark must satisfy all four. If it does not, **change the location, not
the plan.** Ten minutes of relocating beats two days of fighting bad data.

- [ ] the main road carries an OSM `lanes` tag
- [ ] at least one real junction inside the AOI
- [ ] `maxspeed` present, or a sensible class default applies
- [ ] lane markings clearly visible in satellite imagery at zoom 19
- [ ] `netconvert` produces a connected network (open it in netedit and look)
- [ ] at least one multi-lane edge ≥ 100 m long, for the closure

Record the verified values here:

```
verified on       (date)
main road         (name / OSM way id)
lanes tag         (value, or "absent -> inferred")
junction          (present? signalised?)
closure edge      (id, lanes, length)
```

---

## Expected artifacts

```
projects/benchmark/
├── location.json
├── roadtwin.json
├── road_network.xodr
├── observations.json
├── validation_report.json
├── source_manifest.json
├── provenance.json
├── scenario.json
├── metrics.json
├── README.md
├── build/         benchmark.osm, plain.*.xml
└── sumo/          network.net.xml, routes.rou.xml, closure.add.xml, results/
```

---

## Demo script — 4 minutes, rehearse it three times

| # | Beat | Say | Watch out for |
|---|---|---|---|
| 1 | Launch RoadTwin.exe | "This is an installed desktop app, no cloud backend." | Cold start — open it before you begin talking |
| 2 | Type the address | "Geocoding is only a suggestion." | Have lat/lon ready if geocoding is slow |
| 3 | Drag the marker, Open in Maps | "The engineer confirms the site. Nothing runs until they do." | This is the credibility beat — do not rush it |
| 4 | Confirm Location | "Now we acquire." | — |
| 5 | OSM acquired, network appears | "OSM gives us complete topology and patchy attributes." | Use the cached extract |
| 6 | Show a road with no `lanes` tag | "OSM has no lane data here. We inferred 2, and we say so." | **This is the strongest beat. Land it.** |
| 7 | Run AI Analysis | "SAM segments the road surface. We measure its width." | Pre-warm the model |
| 8 | Review item appears | "10.8 m of surface. That is 3 lanes, not 2. Confidence 82%." | — |
| 9 | Click ACCEPT | "The engineer decides. Not the model." | — |
| 10 | Model + .xodr regenerate | "One edit, and the network and the OpenDRIVE both recompile." | — |
| 11 | Run the experiment | "Same network, same demand, same seeds. Only the closure differs." | — |
| 12 | Metrics table | "Travel time up 34%. That is causal, not noise — five seeds." | Numbers must be live |
| 13 | Export ZIP | "Everything, with a provenance chain from OSM tag to result." | Open the zip and show the files |

### The single most important moment

Beat 9 → 12. **The engineer accepts a piece of AI evidence and the traffic
numbers change.** That is what makes the twin feel real rather than
decorative. Rehearse that transition specifically.

---

## Expected result shape

```
                        BASELINE      CLOSURE      DELTA
Average travel time        42.1s        56.4s      +34.0%
Queue length               18.2m        47.6m     +161.5%
Completed vehicles           102           97       -4.9%
mean of 5 seeds | Closure produced a change larger than seed-to-seed variation.
```

Numbers will differ. **If the delta is not significant, the demo is not ready** —
lower `SIM.period` in config.py and re-run. Do not present noise as a finding.

---

## Demo insurance checklist

Every item here has ended somebody's hackathon.

- [ ] `assets/benchmark/osm_*.osm` committed
- [ ] tile mosaic cached
- [ ] vision outputs (mask, detections) cached
- [ ] a pre-built `RoadTwin_Project.zip` on disk to open if live generation fails
- [ ] **full backup demo video recorded, stored locally**
- [ ] app installed and SmartScreen/antivirus whitelisted, days early
- [ ] SUMO installed, `SUMO_HOME` set on the demo machine
- [ ] laptop plugged in, GPU on the performance profile
- [ ] rehearsed three times, timed

---

## The four questions, and the answers

**"Isn't this just netconvert?"**
netconvert is our compiler backend, the way LLVM is a compiler backend. The
contribution is the layer above it: georeferenced evidence, a human validation
gate, and a provenance chain. Rewriting a mature compiler would have been the
least novel and most fragile part of the system.

**"How do you know the AI is right?"**
We don't, and the architecture assumes we don't. AI output is never committed
silently — it creates a review item with a confidence score, and the human
decision is authoritative and recorded. That is the design, not a limitation.

**"Why does a lane closure matter?"**
It is the smallest experiment that proves the model is simulation-grade rather
than a picture. Same network, same demand, same seeds — the only variable is
the closure, so the delta is causal.

**"What was genuinely hard?"**
Georeferencing visual evidence so it can be compared against map data at all,
and keeping a human-auditable chain from OSM tag to simulation result. Most of
the code exists to make the second one true.
