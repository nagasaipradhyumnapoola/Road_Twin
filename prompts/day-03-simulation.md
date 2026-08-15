# DAY 3 — Simulation and the traffic experiment ★ CRITICAL DAY

(Paste `prompts/master.md` first.)

---

This is the day the project either has a product or does not. By tonight every
"never cut" item must be done.

## 1. Demand generation and calibration

`core/sim/demand.py` wraps `randomTrips.py`. It is written; your job is to
**calibrate it**.

A lane closure on an empty road changes nothing. "42s baseline vs 42s closure"
makes the entire project look pointless, and that is a demand-calibration
failure, not a modelling failure.

Iterate on `SIM["period"]` in `config.py`:

| Symptom | Action |
|---|---|
| closure delta ≈ 0 | **lower** `period` (more traffic) |
| teleport warning in metrics | **raise** `period` — the network is gridlocked and the numbers are meaningless |
| baseline barely above free-flow | lower `period` |
| delta 20–60%, no teleports | stop, you are calibrated |

Target roughly 75–85% of corridor capacity. Two or three iterations is normal.

**Write the final value into `context/CURRENT_STATE.md` under CALIBRATION
RECORD**, along with the vehicle counts and baseline travel time.

Routes are generated **once** and reused by both runs. Do not regenerate them
per scenario.

## 2. Closure scenario

`core/sim/scenario.py` is written and unit-tested. It emits:

```xml
<rerouter id="..." edges="UPSTREAM CLOSED">
  <interval begin="300" end="3600">
    <closingLaneReroute id="EDGE_2" allow="authority"/>
  </interval>
</rerouter>
```

**Do not modify the network to close a lane** (ADR-006). The rerouter is placed
on the closed edge *and its upstream edges* so vehicles learn about the closure
early enough to divert.

Surface the honest limitation in the UI: SUMO closes a lane for a whole edge,
so report `actual_closed_length_m` — the real edge length — not an arbitrary
requested distance.

## 3. Running the experiment

`core/sim/run.py` runs baseline and closure across the seed set. Same network,
same routes, same seeds — the only difference is the additional-file. This is
what makes the delta causal, and it is exactly what a judge will probe.

`--device.rerouting.probability 1` is already set. Without it vehicles cannot
respond to the closure at all and the scenario is meaningless.

## 4. Metrics

`core/sim/metrics.py` is written and unit-tested. Three metrics only:

- average travel time (from `--tripinfo-output`)
- queue length (from `--queue-output`)
- completed vehicles (count of tripinfo entries)

Report mean and standard deviation across seeds. `metrics.compare()` sets
`significant: false` when the change is within seed noise — **respect that
flag**. Do not present noise as a finding.

**Never hardcode a metric.**

## 5. OpenDRIVE validation

`netconvert.verify_xodr_roundtrip()` re-imports our own `.xodr`. This turns
"is your OpenDRIVE valid?" from an assertion into evidence. It must print PASS.

## 6. Experiment UI

- road selector, lane selector, length display
- RUN EXPERIMENT
- comparison table: baseline / closure / delta %, with the seed count shown
- explicit, clear error if the selected lane cannot be closed (single-lane
  edge, out-of-range index, unknown edge) — **never a fabricated experiment**
- export `RoadTwin_Project.zip` from the UI

---

## Verify before you claim completion

1. `python scripts/selftest.py` → 0 failed
2. `python scripts/run_benchmark.py` → `significant: true`
3. OpenDRIVE round-trip prints PASS
4. baseline and closure both run **from the UI**
5. closing a single-lane edge shows a clear error
6. ZIP exports from the UI
7. CALIBRATION RECORD filled in

## Gate 3 is a genuine go/no-go

If this does not pass tonight, stop all feature work. Spend Day 4 fixing it and
Day 5 on polish and rehearsal, and **ship with zero AI**. A twin that provably
simulates beats one that detects traffic lights but cannot simulate.
