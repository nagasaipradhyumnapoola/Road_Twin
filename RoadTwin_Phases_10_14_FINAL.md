# RoadTwin — FINAL EXECUTION PLAN
## Phases 10–14 — The Complete High-Impact Extension

**Purpose:** Continue directly from the completed P0–P9 RoadTwin core.

P0–P9 establish:

```text
Real Indian location
      ↓
OSM acquisition
      ↓
Canonical RoadTwin
      ↓
Provenance
      ↓
Visual evidence
      ↓
Human validation
      ↓
OpenDRIVE / SUMO
      ↓
Controlled traffic simulation
```

P10–P14 deliberately compress the remaining work into five phases:

> **Measure → Create What-If → Understand Impact → Test Alternatives → Make a Decision**

---

# PHASE 10 — ACCELERATION PROOF ⭐

**Priority: MANDATORY · 3–4 hours**

## Objective

Directly demonstrate the **“accelerating”** part of PS95.

RoadTwin must show how much of the road-network modeling process is automated and how much human effort remains.

## 10.1 Benchmark record

Store:

```json
{
  "benchmark_id": "accel-001",
  "location": "...",
  "network": {
    "roads": 143,
    "junctions": 31,
    "lanes": 284
  },
  "timings": {
    "acquisition_s": 12.4,
    "model_generation_s": 2.8,
    "compilation_s": 4.1,
    "export_s": 1.7,
    "total_s": 21.0
  },
  "human_actions": {
    "location_confirmation": 1,
    "evidence_reviews": 3,
    "manual_edits": 0
  }
}
```

Use actual measured values. **Never invent a manual baseline or unsupported “X times faster” claim.**

## 10.2 Measure

Record:

- OSM acquisition
- RoadTwin construction
- Geometry processing
- Compilation
- OpenDRIVE export
- SUMO network generation
- Total processing time
- Location confirmations
- Evidence reviews
- Manual edits

## 10.3 Benchmark UI

```text
ROADTWIN — MODELING BENCHMARK

NETWORK
143 Roads
31 Junctions
284 Lanes

AUTOMATED PROCESSING
────────────────────────────
OSM Acquisition        12.4 s
Twin Generation         2.8 s
Compilation             4.1 s
Export                  1.7 s
────────────────────────────
TOTAL                  21.0 s

HUMAN INPUT
────────────────────────────
Location confirmation       1
Evidence reviews            3
Manual edits                0
```

## DONE WHEN

```text
✓ benchmark is reproducible
✓ actual processing time is recorded
✓ human effort is recorded
✓ network size is recorded
✓ benchmark is visible in the application
✓ no unsupported speed claim exists
```

**CUT IF LATE:** Nothing. This directly strengthens PS95.

---

# PHASE 11 — WHAT-IF SCENARIO ENGINE

**Priority: MANDATORY · 4–5 hours**

## Objective

Turn the existing lane-closure experiment into a reusable **What-If engine**.

The canonical RoadTwin remains unchanged. Every experiment becomes a scenario branch.

```text
                    VERIFIED ROADTWIN
                           │
             ┌─────────────┼─────────────┐
             ↓             ↓             ↓
         BASELINE      LANE CLOSURE   ROAD CLOSURE
             │             │             │
             └─────────────┼─────────────┘
                           ↓
                       SIMULATION
```

## 11.1 Scenario model

Create:

```text
core/scenario/
    models.py
    builder.py
    validator.py
    registry.py
```

```json
{
  "scenario_id": "scn-001",
  "base_twin_id": "roadtwin-001",
  "name": "Main Road Lane Closure",
  "type": "lane_closure",
  "parameters": {},
  "demand": {},
  "seeds": [1,2,3,4,5]
}
```

## 11.2 V1 scenarios

Keep the scope small:

```text
Lane Closure
Road Closure
Traffic Increase
```

Optional:

```text
Diversion
```

## 11.3 Scenario UI

```text
SCENARIOS

BASELINE
Main Road — Lane Closure
Main Road — Road Closure
Traffic Demand +20%

[ + NEW SCENARIO ]
```

## 11.4 Execution

```text
Scenario
   ↓
Validation
   ↓
SUMO configuration
   ↓
Simulation
   ↓
Metrics
   ↓
Stored result
```

No fabricated scenario results.

## DONE WHEN

```text
✓ scenarios can be created
✓ baseline remains unchanged
✓ at least 3 scenario types work
✓ scenario configurations are stored
✓ scenarios can be rerun
✓ results are linked to their scenario
```

**CUT IF LATE:** Keep Baseline + Lane Closure + Road Closure.

---

# PHASE 12 — IMPACT MAP & NETWORK ANALYSIS ⭐

**Priority: MANDATORY · 5–6 hours**

## Objective

Move from:

> “Travel time increased.”

to:

> **“Here is where the impact went.”**

This is the major visual payoff.

## 12.1 Collect edge-level results

For relevant edges:

```text
edge_id
travel_time
waiting_time
queue_length
mean_speed
vehicle_count
```

Compare:

```text
BASELINE
   VS
SCENARIO
```

## 12.2 Calculate impact

```text
travel_time_delta
queue_delta
speed_delta
```

Example:

```json
{
  "edge_id": "edge-017",
  "travel_time_delta": 13.4,
  "queue_delta": 28.2
}
```

## 12.3 Impact classes

Use configurable deterministic thresholds:

```text
LOW
MODERATE
HIGH
SEVERE
```

## 12.4 Impact map

The map distinguishes:

```text
UNCHANGED
DIRECTLY AFFECTED
SECONDARILY AFFECTED
```

The visual story should be immediately understandable:

```text
ROAD CLOSED HERE
       ↓
CONGESTION SPREADS HERE
       ↓
JUNCTION BECOMES CRITICAL
```

## 12.5 Impact summary

```text
SCENARIO IMPACT

Travel Time       +34%
Queue             +71%
Affected Roads       7
Critical Junctions   3
```

All values come directly from simulation results.

## 12.6 Critical junctions

Rank using measurable changes such as:

```text
queue increase
waiting-time increase
travel-time increase
```

Show:

```text
MOST AFFECTED JUNCTIONS

1. J-07
2. J-11
3. J-03
```

## DONE WHEN

```text
✓ baseline vs scenario edge metrics are available
✓ affected roads are visible
✓ impact classes are displayed
✓ critical junctions are identified
✓ aggregate metrics match simulation output
✓ direct and secondary impact are distinguishable
```

**CUT IF LATE:** Drop animated propagation. Keep the static impact map.

---

# PHASE 13 — INTERVENTION ENGINE ⭐⭐⭐

**Priority: MANDATORY / WOW FEATURE · 6–8 hours**

## Objective

Move RoadTwin from:

> **“This is what happens.”**

to:

> **“What can we do about it?”**

The system tests a small number of possible interventions using actual simulation.

## 13.1 User action

```text
SCENARIO RESULT

Travel Time       +34%
Queue             +71%

[ FIND BETTER OPTIONS ]
```

## 13.2 Intervention model

Create:

```text
core/intervention/
    models.py
    candidates.py
    validator.py
    evaluator.py
    ranking.py
```

## 13.3 V1 interventions

Start with:

```text
1. Lane configuration
2. Alternative routing / diversion
```

Optional:

```text
3. Demand redistribution
4. Turn restriction
```

Only include interventions the current SUMO architecture can represent reliably.

## 13.4 Candidate pipeline

```text
SCENARIO
    ↓
GENERATE CANDIDATES
    ↓
VALIDATE
    ↓
RUN SUMO
    ↓
COLLECT METRICS
    ↓
COMPARE
    ↓
RANK
```

The LLM never invents numerical outcomes.

## 13.5 Candidate comparison

```text
TESTED OPTIONS

                         TRAVEL TIME     QUEUE

Baseline                    58.2 s         71 m
Lane configuration          49.3 s         51 m
Alternative routing         51.7 s         58 m
```

Use actual results.

## 13.6 Best tested option

```text
BEST TESTED OPTION

Lane Configuration

Travel Time
58.2 s → 49.3 s

Queue
71 m → 51 m

Seeds
5
```

Use **“Best tested option”**, not “optimal”, unless the feasible search space is actually exhaustive.

## 13.7 Failed candidates

```text
INTERVENTION FAILED

Candidate:
Lane configuration

Reason:
Invalid lane configuration for selected edge.
```

Never hide failures.

## DONE WHEN

```text
✓ intervention candidates are structured
✓ candidates are validated
✓ candidates run through SUMO
✓ results use real simulation metrics
✓ candidates can be compared
✓ best tested option is shown
✓ failed candidates are explained
```

**CUT IF LATE:** Implement only Lane Configuration + Alternative Routing.

---

# PHASE 14 — ENGINEER GOAL → DECISION ⭐⭐

**Priority: HIGH · 4–5 hours**

## Objective

Make RoadTwin answer the real engineering question:

> **“I have a goal. What tested option can achieve it?”**

## 14.1 Goal interface

```text
ENGINEERING GOAL

Objective:
○ Reduce travel time
○ Reduce queue
○ Increase completed vehicles

Target:
[ 20 ] %

Maximum interventions:
[ 1 ]

[ FIND SOLUTIONS ]
```

Keep the first version simple.

## 14.2 Search pipeline

```text
ENGINEER GOAL
      ↓
GENERATE CANDIDATES
      ↓
VALIDATE
      ↓
SIMULATE
      ↓
COMPARE
      ↓
FILTER BY GOAL
      ↓
BEST TESTED OPTION
```

## 14.3 Successful result

```text
TARGET ACHIEVED ✓

Goal
20% travel-time reduction

Best tested option
Alternative Routing

Simulated improvement
23.4%

Queue reduction
18.7%
```

## 14.4 No-solution result

```text
TARGET NOT ACHIEVED

Requested improvement
20%

Best tested result
14.2%

No tested intervention satisfied
the requested target.
```

Never force a recommendation.

## 14.5 Final decision card

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       ROADTWIN DECISION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LOCATION
Main Road / Junction J-07

SCENARIO
Lane Closure

IMPACT
Travel Time       +34%
Queue             +71%
Affected Roads       7

BEST TESTED OPTION
Alternative Routing

RESULT
Travel Time       -21.8%
Queue             -38.2%

SIMULATION
5 Seeds

ASSUMPTIONS
Synthetic Demand

LIMITATIONS
Field calibration unavailable
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[ EXPORT REPORT ]
```

## DONE WHEN

```text
✓ engineer can specify a measurable goal
✓ candidates are tested against that goal
✓ constraints are enforced
✓ success and no-solution states work
✓ decision card is generated
✓ result can be exported
```

---

# FINAL P10–P14 INTEGRATION

The five phases must feel like one workflow:

```text
                         ROADTWIN
                            │
                            ▼
                  P10 — ACCELERATION
                            │
                            ▼
                    P11 — WHAT-IF
                            │
                            ▼
                  P12 — IMPACT MAP
                            │
                            ▼
                P13 — TEST OPTIONS
                            │
                            ▼
               P14 — ENGINEER GOAL
                            │
                            ▼
                     DECISION CARD
```

The user experience:

```text
REAL ROAD
    ↓
ROAD TWIN
    ↓
VERIFY
    ↓
"WHAT IF?"
    ↓
SIMULATE
    ↓
SEE IMPACT
    ↓
"FIND A BETTER OPTION"
    ↓
TEST ALTERNATIVES
    ↓
SET ENGINEERING GOAL
    ↓
COMPARE
    ↓
DECISION
    ↓
EXPORT
```

---

# FINAL DEMO

Use **one strong real location** and one scenario.

### Beat 1 — Build
Show the real road becoming the RoadTwin.

### Beat 2 — Prove acceleration
Show the measured modeling benchmark.

### Beat 3 — Verify
Show one meaningful data/evidence discrepancy and accept the validated evidence.

### Beat 4 — What-if
Choose:

> **Close this lane.**

Run simulation.

### Beat 5 — Impact
Show:

```text
Travel Time   +34%
Queue         +71%
```

Then show the impact map.

### Beat 6 — Intervention
Click:

> **FIND BETTER OPTIONS**

Run the tested alternatives.

### Beat 7 — Decision
Show:

> **Best tested option: Alternative Routing**

with the actual simulation improvement.

### Beat 8 — Audit
Show:

```text
Decision
 ↓
Simulation
 ↓
Scenario
 ↓
RoadTwin
 ↓
Evidence
 ↓
Source
```

### Beat 9 — Export
Export the decision report/project ZIP.

---

# NON-NEGOTIABLE RULES

1. **Real simulation metrics only.**
2. **Human validation remains authoritative.**
3. **Canonical RoadTwin remains stable.**
4. **Every result is reproducible from twin + scenario + configuration + seed.**
5. **Unknown is better than an invented answer.**
6. **Synthetic demand must be clearly labeled.**
7. **“Best tested” is not automatically “optimal.”**
8. **Do not add new architecture during the final polish period.**

---

# CUT LADDER

If time becomes extremely limited:

## NEVER CUT

```text
P10 Acceleration
P11 Basic Scenarios
P12 Impact Map
```

## KEEP AT LEAST

```text
P13 Lane Configuration
```

## OPTIONAL

```text
P13 Alternative Routing
P14 Goal Interface
Decision-card polish
```

Minimum impressive extension:

```text
ACCELERATION
     ↓
WHAT-IF
     ↓
IMPACT MAP
     ↓
BETTER OPTION
```

---

# FINAL DEFINITION OF DONE

```text
✓ RoadTwin modeling effort/time is measured
✓ A verified RoadTwin can produce multiple scenarios
✓ A scenario can be simulated from the same baseline twin
✓ Network-wide impact is visualized
✓ Critical roads/junctions are identified
✓ At least two interventions can be tested
✓ Intervention results come from real SUMO runs
✓ Best tested option is compared against baseline
✓ Engineer can specify a simple measurable goal
✓ System can report success OR no solution
✓ Decision card is generated
✓ Complete result can be exported
```

## FINAL PRODUCT MESSAGE

> **Build the road digitally. Verify what is uncertain. Test the change virtually. Then make the real-world decision.**

**RoadTwin: Build → Verify → Simulate → Decide.**
