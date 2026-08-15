# DECISIONS (ADRs)

Short, dated, and binding. If you want to violate one, change it here first
and write down why.

---

## ADR-001 — OSM is the deterministic baseline
OSM gives complete topology. Its attributes are patchy but its geometry is
trustworthy enough to build on. Everything else is layered on top of it.

## ADR-002 — AI produces evidence; it never mutates the baseline
Model output goes to `observations.json` with a confidence and
`status: REVIEW`. It becomes a change only when a human accepts it. This is the
central design commitment of the product — an AI road builder that is wrong 15%
of the time is unusable; an AI evidence generator that is right 85% of the time
is valuable.

## ADR-003 — netconvert is the OpenDRIVE writer. We do not hand-write .xodr
**Rejected alternative:** a custom RoadTwin → OpenDRIVE compiler.
**Why:** OpenDRIVE is a geometry specification, not a serialisation format.
Correct junctions require connecting roads with consistent lane links, and the
failure mode is not a crash — netconvert imports the file, says little, and
produces a disconnected network in which no vehicle can route. Realistic cost
2–3 days with a high chance of never working.
**Consequence:** the exported `.xodr` carries geometry, lanes and junctions but
not signals (SUMO's exporter documents this). Signals live in `plain.tll.xml`
and `roadtwin.json`. Stated in KNOWN LIMITATIONS, not hidden.

## ADR-004 — netconvert plain XML is the editable substrate
`.nod/.edg/.con/.tll/.typ` are small, readable, and round-trip through
netconvert losslessly. Editing `numLanes` on an edge and recompiling gives a
new network and a new `.xodr` in one step. This replaces a bespoke model
compiler with about 150 lines of XML editing.

## ADR-005 — Real-world geometry from AI requires georeferenced imagery
SAM and Grounding DINO return pixels. `road_mask.geojson` requires degrees.
That conversion exists only if we build the image ourselves from XYZ tiles and
keep the transform. Detections from a non-georeferenced street photo are tagged
`geometry_kind: "image_space"` and attached to a `road_id`, with no coordinate
claimed.

## ADR-006 — Lane closure is a rerouter, not a network edit
`<closingLaneReroute>` in an additional-file. Baseline and closure share the
network, the routes and the seed set, so the measured difference is causal.
Rebuilding the network to close a lane would change ids and break the
comparison.
**Consequence:** SUMO closes a lane for a whole edge; the reported closure
length is the actual edge length. We report the real number.

## ADR-007 — Vision runs as an optional second sidecar
Keeps `torch` out of the frozen core binary (3–5 GB → ~300 MB) and makes the
"AI unavailable → continue with OSM" path structural rather than aspirational.

## ADR-008 — SUMO is an external prerequisite, discovered via SUMO_HOME
Bundling adds hundreds of MB and an EPL-2.0 notice obligation for no demo
benefit. README states it; startup checks it and errors clearly.

## ADR-009 — Files and folders. No SQLite, no PostGIS
One project is one directory. At this scale a database adds ceremony and
removes inspectability — and being able to open the artifacts in a text editor
in front of a judge is worth more than query performance we do not need.

## ADR-010 — No cloud backend. Network for acquisition only
Everything runs locally. Overpass, geocoding and tiles need network on first
fetch; all are cached. A saved project reopens and re-simulates fully offline.
Say it this way — the earlier phrasing "no cloud dependency" was not true.

## ADR-011 — Runtime dependencies are deliberately minimal
`fastapi uvicorn pydantic requests lxml numpy pillow` and nothing else in the
frozen binary. **GDAL, Rasterio, GeoPandas, NetworkX and OSMnx are excluded**:
they were never load-bearing here, and they are the hardest libraries to freeze
with PyInstaller. OSMnx may be used in notebooks.

## ADR-012 — No 3D view in the five-day build
A rushed three.js scene looks worse than a good 2D map and costs four times as
much. Not on the cut list because it is never started.

## ADR-013 — No pothole detection
Open-vocabulary detectors cannot do it reliably at any altitude; a pothole is a
texture, not a nameable object shape. Demoing it invites the model to box
manhole covers in front of a judge.
