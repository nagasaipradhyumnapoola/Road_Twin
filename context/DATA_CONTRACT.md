# DATA_CONTRACT

Canonical schemas. Change them here first, then in `core/model/`.

---

## location.json

```json
{
  "name": "GST Road, Chennai",
  "lat": 12.8231,
  "lon": 80.0442,
  "aoi_radius_m": 500,
  "crs": "EPSG:4326",
  "confirmed": true,
  "confirmation_method": "user"
}
```

`confirmed` gates the entire pipeline. `confirmation_method` is one of
`user` (dragged/approved the marker), `manual_coords`, `benchmark_config`.

---

## roadtwin.json — the canonical model

```json
{
  "schema_version": "0.2",
  "project_id": "benchmark",
  "location": { "...": "location.json" },
  "roads": [],
  "lanes": [],
  "junctions": [],
  "objects": [],
  "observations": [],
  "validation": [],
  "provenance": []
}
```

### Road

```json
{
  "id": "rt-road-007",
  "sumo_edge_id": "E1",
  "osm_way_id": 123456789,
  "geometry": {"type": "LineString", "coordinates": [[80.0441, 12.8230]]},
  "direction": "forward",
  "road_type": "trunk",
  "speed_kph": 60,
  "length_m": 340.5,
  "lane_count": 2,
  "lane_count_provenance": {
    "source": "osm_tag",
    "rule": null,
    "confidence": 1.0
  }
}
```

**`lane_count_provenance.source` is mandatory** and must be one of:

| source | meaning |
|---|---|
| `osm_tag` | OSM carried an explicit `lanes` tag |
| `inferred_default` | no tag; a road-class default was applied |
| `accepted_vision` | a human accepted an AI observation |
| `human` | a human typed the value |

Indian OSM roads frequently lack `lanes`. Recording `inferred_default` with a
low confidence is what lets the review UI say *"OSM has no data — we inferred 2
— vision suggests 3"*, which is both honest and a better demo than pretending
OSM said 2.

### Lane

```json
{
  "id": "rt-lane-007-1",
  "road_id": "rt-road-007",
  "sumo_lane_id": "E1_1",
  "index": 1,
  "direction": "forward",
  "width_m": 3.5,
  "speed_kph": 60
}
```

SUMO lane ids are `<edge_id>_<index>`, index 0 = rightmost. Keep that mapping;
the closure scenario depends on it.

### Junction

```json
{
  "id": "rt-junction-003",
  "sumo_node_id": "n2",
  "geometry": {"type": "Point", "coordinates": [80.0442, 12.8231]},
  "incoming_roads": ["rt-road-007"],
  "outgoing_roads": ["rt-road-008"],
  "has_signal": true,
  "connections": [{"from_lane": "E1_0", "to_lane": "E2_0"}]
}
```

---

## observations.json — immutable AI evidence

Two shapes, distinguished by `geometry_kind`. **This field is mandatory.**

### Georeferenced (from the overhead tile mosaic)

```json
{
  "id": "obs-001",
  "source": "sam2",
  "model": "facebook/sam2.1-hiera-small",
  "type": "lane_count_estimate",
  "feature": "lane_count",
  "value": 3,
  "geometry_kind": "georeferenced",
  "attached_to": {"road_id": "rt-road-007"},
  "confidence": 0.82,
  "status": "REVIEW",
  "evidence": {
    "measured_width_m": 10.8,
    "assumed_lane_width_m": 3.5,
    "raw_estimate": 3.09,
    "samples": 34,
    "width_cv": 0.07,
    "method": "mask width perpendicular to OSM centerline / nominal lane width"
  }
}
```

### Image-space (from a street-level photo)

```json
{
  "id": "obs-014",
  "source": "grounding_dino",
  "model": "IDEA-Research/grounding-dino-tiny",
  "type": "traffic_light",
  "geometry_kind": "image_space",
  "pixel_bbox": [812, 344, 861, 428],
  "source_image": "site_photo_01.jpg",
  "attached_to": {"road_id": "rt-road-007"},
  "geometry": null,
  "confidence": 0.87,
  "status": "REVIEW",
  "note": "Detected in a non-georeferenced image. No real-world coordinate is claimed."
}
```

`status` ∈ `REVIEW` | `ACCEPTED` | `REJECTED` | `EDITED`.
Observations are **append-only**. Rejecting one sets its status; it is never
deleted.

---

## imagery manifest (inside source_manifest.json)

Without this the mosaic is just a picture again.

```json
{
  "provider": "xyz-tiles",
  "zoom": 19,
  "tile_range": {"x": [478112, 478119], "y": [271330, 271337]},
  "bbox_wgs84": [80.0398, 12.8194, 80.0487, 12.8268],
  "size_px": [2048, 2048],
  "meters_per_pixel": 0.2911,
  "crs": "EPSG:4326"
}
```

---

## validation_report.json — the audit trail

```json
{
  "schema_version": "0.1",
  "generated_at": "2026-08-15T09:14:22+00:00",
  "observations": ["... every observation, including rejected ones ..."],
  "decisions": [
    {
      "edge_id": "E1",
      "attribute": "numLanes",
      "old_value": "2",
      "new_value": "3",
      "source": "accepted_vision",
      "observation_id": "obs-001",
      "confidence": 0.82,
      "user_action": "accept",
      "timestamp": "2026-08-15T09:15:03+00:00"
    }
  ],
  "replay_note": "Apply decisions in order to the baseline plain/*.edg.xml, then netconvert."
}
```

**Invariant:** `baseline plain XML + decisions == final model`.
Tested by `core.model.edits.replay()`; covered in `scripts/selftest.py`.

---

## metrics.json

```json
{
  "baseline": {
    "label": "baseline", "n_seeds": 5,
    "avg_travel_time_s": 42.1, "avg_travel_time_s_sd": 1.2,
    "mean_queue_length_m": 18.2, "max_queue_length_m": 41.0,
    "completed_vehicles": 102
  },
  "closure": { "...": "same shape" },
  "comparison": {
    "rows": [
      {"metric": "Average travel time", "baseline": 42.1, "scenario": 56.4,
       "delta": 14.3, "delta_pct": 34.0, "unit": "s"}
    ],
    "significant": true,
    "verdict": "Closure produced a change larger than seed-to-seed variation."
  }
}
```

`significant` is false when the change is within seed noise. **Do not present a
non-significant result as a finding** — increase demand or pick a more critical
edge.

---

## scenario.json

```json
{
  "edge_id": "E1",
  "lane_id": "E1_2",
  "lane_index": 2,
  "lanes_on_edge": 3,
  "actual_closed_length_m": 340.5,
  "begin": 300,
  "end": 3600,
  "trigger_edges": ["E1", "E0"],
  "note": "SUMO closes the lane for the full edge length; the effective closure is 340 m."
}
```

`actual_closed_length_m` is the real number, not the requested one. See ADR-006.

---

## provenance entry

```json
{
  "source": "netconvert",
  "tool": "netconvert",
  "tool_version": "Eclipse SUMO netconvert v1_20_0",
  "created_at": "2026-08-15T09:14:22+00:00",
  "inputs":  [{"path": "build/benchmark.osm", "sha256": "..."}],
  "outputs": [{"path": "sumo/network.net.xml", "sha256": "..."}]
}
```
