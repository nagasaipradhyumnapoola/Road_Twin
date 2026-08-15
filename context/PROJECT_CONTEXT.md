# PROJECT_CONTEXT

> Claude Code: read this file and CURRENT_STATE.md before changing anything.

## Problem

Traffic engineers who want to test a road intervention — a lane closure, a
diversion, a new signal — must first rebuild the road network by hand in a
simulation tool. For an Indian arterial that is days of work per site, and it
has to be redone whenever the road changes. The map data that could bootstrap
it (OpenStreetMap) is incomplete: lane counts, medians and barriers are often
missing or stale, so nobody trusts it enough to use it unedited.

## Solution

RoadTwin takes a confirmed real-world location and produces a simulation-ready
road model in minutes instead of days, by combining three sources with clearly
different levels of trust:

1. **OSM** — the deterministic baseline. Complete topology, patchy attributes.
2. **Visual AI** — pretrained SAM 2.1 and Grounding DINO, producing *evidence*
   about what is actually on the ground.
3. **The engineer** — who adjudicates every disagreement and whose decision is
   authoritative and recorded.

The output is an OpenDRIVE network plus a SUMO experiment, with a provenance
chain from OSM tag to simulation result.

## Target user

A traffic or highway engineer at a municipal corporation, state highways
department or consultancy, who can read a road network but is not going to
hand-build one in netedit for every study.

## Product boundary

RoadTwin **is** a road-model construction and validation tool that ends at a
runnable traffic experiment.

RoadTwin **is not** a traffic prediction system, a calibrated microsimulation
study, a mapping platform, or an autonomous-driving scenario suite. It hands
off to those via OpenDRIVE.

## Inputs

- an address, or a latitude/longitude pair
- optionally, a street-level photograph of the site
- the engineer's decisions on each review item

## Outputs

- `roadtwin.json` — canonical model with provenance
- `road_network.xodr` — OpenDRIVE, for interoperability
- `sumo/` — network, routes, scenario, raw results
- `observations.json` — immutable AI evidence
- `validation_report.json` — every human decision, replayable
- `metrics.json` — baseline vs scenario
- `RoadTwin_Project.zip` — all of the above

## Non-goals (deliberate, defend these in the demo)

| Not doing | Why |
|---|---|
| Training any model | Pretrained is sufficient; training is a research project, not a product |
| Full 3D reconstruction | Engineering visualisation answers the question; photorealism does not |
| Hand-written OpenDRIVE compiler | netconvert already does it correctly (ADR-003) |
| Video or temporal fusion | Out of scope for the first vertical slice |
| LLM / natural-language control | Adds demo surface, adds no engineering proof |
| PostGIS, microservices, Kubernetes | One local backend, files on disk |
| Pothole detection | Open-vocabulary models cannot do it reliably; claiming it invites embarrassment |

## Hackathon scope

Five days, one builder. The vertical slice
`location → OSM → RoadTwin → OpenDRIVE → SUMO → lane closure → export`
must work end to end before any of the AI layer is built, because the
simulation is the proof and the AI is the differentiator. Losing the AI hurts;
losing the simulation is fatal.

## The one-sentence claim

> RoadTwin turns a real Indian road into an editable, simulation-ready digital
> road model without requiring engineers to rebuild the road network by hand —
> and shows its working at every step.
