# DAY 2 — Location gateway, acquisition, model, edit loop

(Paste `prompts/master.md` first.)

---

## 1. Location verification gateway

**Hard rule: no downstream step runs until the location is confirmed.** Enforce
it in the backend, not just the UI.

Build:

- address input and latitude/longitude input
- an address resolver **behind a swappable adapter interface** — set a real
  identifying `User-Agent`, rate-limit to 1 request/second, and cache results.
  The provider may become unavailable; the adapter is how you survive that.
- a MapLibre map. **Verify tiles actually render before building anything on
  top of the map** — MapLibre ships no map data, and a grey rectangle
  discovered during a demo is mortifying.
- a draggable marker with a live coordinate readout
- an "Open in Maps" action using **`tauri-plugin-opener`**. Tauri 2 has no
  `shell.open` — most tutorials online are v1 and will not work.
- an explicit "Confirm Location" action
- persistence to `location.json` per `context/DATA_CONTRACT.md`

Fallbacks: if geocoding fails, manual lat/lon must still work. If tiles fail,
coordinate confirmation must still work.

## 2. OSM acquisition

`core/acquire/overpass.py` is written and tested. Wire it to the confirmed
coordinates and `aoi_radius_m`. Keep the raw `.osm` — it is netconvert's input
and our provenance record.

Cache by bbox into `assets/benchmark/`. This is demo insurance, not an
optimisation.

## 3. The RoadTwin canonical model

Implement the Pydantic models in `core/model/roadtwin.py` per
`context/DATA_CONTRACT.md`: Road, Lane, Junction, Object, Observation. Stable
ids, provenance, round-trip serialisation.

**The detail that matters most: `lane_count_provenance`.**

Indian OSM roads frequently have no `lanes` tag. When it is absent, apply a
road-class default and record:

```json
{"source": "inferred_default", "rule": "highway=trunk -> 2 lanes", "confidence": 0.4}
```

Never silently emit a lane count as though OSM supplied it. This turns a data
gap into the strongest beat in the demo: *"OSM has no lane data here — we
inferred 2, and we say so — vision measured 3."*

Also emit `roads.geojson` and `junctions.geojson` for the map (EPSG:4326 at
the boundary only).

## 4. The edit → recompile loop

`core/model/edits.py` and `core/build/netconvert.py` are written and tested.
Expose them through the API so that accepting a change:

1. rewrites `plain.edg.xml` via `apply_edits()`
2. calls `plain_to_net()` once
3. regenerates **both** `network.net.xml` and `road_network.xodr`

Prove it:

```
python scripts/run_benchmark.py --edit-lanes 3
```

## 5. Units

Every metre-based quantity comes from the SUMO network (already in projected
metres) or the mosaic ground resolution. Never subtract degrees.

---

## Verify before you claim completion

1. `python scripts/selftest.py` → 0 failed
2. address → map → drag marker → confirm → OSM downloads → model validates
3. invalid address handled; manual coordinates work
4. `--edit-lanes 3` regenerates net.xml **and** road_network.xodr
5. `python scripts/run_benchmark.py` still passes
6. the installer still builds

Update `context/CURRENT_STATE.md`.

## Do not

- start downstream work from an unconfirmed location
- add geopandas/osmnx/gdal to the core sidecar
- emit a lane count without `lane_count_provenance`
