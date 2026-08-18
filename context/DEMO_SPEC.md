# DEMO_SPEC

The exact thing that must work, in the exact order it will be shown.

---

## Benchmark

```
Location        (set in config.py BENCHMARK)
Default         GST Road, Chennai — 12.8261, 80.0413
AOI radius      500 m            (ENFORCED by netconvert --keep-edges.in-geo-boundary)
```

> Relocated 2026-08-18. The old centre (12.8231, 80.0442) sat 462 m from GST
> Road, so the corridor only clipped the AOI corner.

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
verified on       2026-08-18  (PARTIAL — OSM extract only, netconvert BLOCKED: no SUMO)
main road         Grand Southern Trunk Road — OSM ways 47572742, 95222417,
                  568057022, 1080757453
lanes tag         lanes=4, explicit on all four trunk ways        CONFIRMED
maxspeed          ABSENT on all 86 drivable ways -> class default WARN
junction          present: 52 junction nodes inside the AOI, 6 on the trunk.
                  NO traffic_signals node inside the AOI          UNSIGNALISED
closure edge      predicted way 95222417, 4 lanes, ~498 m         NOT YET BUILT
```

Still unverified — needs SUMO, then netedit / satellite imagery:

- [ ] netconvert produces a connected network (open it in netedit and look)
- [ ] lane markings clearly visible in satellite imagery at zoom 19
- [ ] actual closure-edge id and length from the built network

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
| 12 | Metrics table | "Across 20 matched seeds, the closure increased travel time on 18 of 20 runs. Paired mean about +16.8s. Five of the twenty tipped into network breakdown." | Numbers must be live -- quote what the run actually shows, not these |
| 13 | Export ZIP | "Everything, with a provenance chain from OSM tag to result." | Open the zip and show the files |

### The single most important moment

Beat 9 → 12. **The engineer accepts a piece of AI evidence and the traffic
numbers change.** That is what makes the twin feel real rather than
decorative. Rehearse that transition specifically.

---

## Expected result shape

Calibrated 2026-08-18 on this benchmark network. `SIM.period = 3.0`
(1200 vehicles over 3600 s), 20 seeds (42-61), closure on the edge chosen
automatically by `pick_closure_candidate()` -- currently `95222417#0`, a
4-lane / 477 m GST Road trunk edge with upstream and downstream connectivity.

### How significance is decided

**The test is PAIRED.** Baseline and closure share the same network, the same
`routes.rou.xml` and the same seed list; only the closure differs. Seed 46's
closure run is therefore the same traffic as seed 46's baseline run, so the
two arms are matched, not independent samples. `compare()` computes the
per-seed difference and runs a two-sided one-sample t-test on those
differences at the 95% level: **significant when the confidence interval for
the mean difference excludes zero.**

This replaced an unpaired rule (`|delta| > 2 x max(baseline_sd, closure_sd)`).
That rule asked the wrong question of a matched design, and on this network it
failed in a specific way: the closure is what *creates* the between-seed
spread, so the harder the closure bit, the larger `closure_sd`, and the harder
the rule became to satisfy. Removing a measurement bias and recovering
censored vehicles pushed it *further* from passing. The paired test is not a
lower bar -- it reports a significant *speed-up* just as readily, and
`run_benchmark.py` treats that as a failure too, because a closure that makes
a network faster means the baseline is gridlocked or the closed edge is a
fringe entry edge.

The unpaired rule is retained as a fallback for aggregates with no per-seed
data (a single seed, or hand-built dicts).

### Two regimes, reported separately

The closure response on this network is **bimodal**, so a single mean is not an
honest summary and the benchmark does not present one alone:

```
BREAKDOWN   ~25% of seeds   network mean speed collapses to ~0.4x baseline,
                            tens of vehicles unfinished at the horizon
NORMAL      ~75% of seeds   closure absorbed, median travel time +~6%
```

Breakdown is counted by a *relative* criterion -- closure network mean speed
below half its own baseline -- so it transfers across networks instead of
encoding an m/s threshold fitted to this one. On this benchmark the regimes
separate cleanly (breakdown 0.33-0.40 of baseline speed, normal 0.81-0.97,
nothing between).

The honest headline is therefore a **probability plus a conditional severity**,
not a percentage:

> Closing one of four lanes caused network-wide breakdown in ~25% of runs; in
> the rest the network absorbed it with a median ~6% travel-time increase.

### Numbers are network-specific

Any figure here is what *this* benchmark measured, not a property of the
method. It moves with location, AOI, demand and seed set. An earlier draft of
this file quoted +34% travel time and +161% queue as the "expected" shape;
those were illustrative, were never measured here, and are not reachable on a
193-edge network with one usable multi-lane corridor. They were removed so
nobody tunes toward them.

Two things to know when reading a run:

- **Queue length is filtered to the closed edge**, so it normally *falls* under
  closure -- a lane is gone, so fewer vehicles can queue there. Congestion
  moves upstream, where this metric does not look. Read travel time instead.
- **Vehicles still running at the horizon are censored.** They never enter
  `tripinfo.xml`, so the travel-time mean omits exactly the worst-affected
  trips, and it does so hardest in breakdown runs. The breakdown block reports
  the unfinished count for this reason. Raising `SIM.end` to 7200 s drains the
  network and removes the censoring entirely.

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
