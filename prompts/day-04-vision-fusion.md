# DAY 4 — Visual evidence and human validation

(Paste `prompts/master.md` first.)

---

Only start this if Gate 3 passed. If it did not, go fix Gate 3.

## 1. Separate sidecar, separate venv (ADR-007)

Vision runs in its own process with its own virtualenv containing `torch` and
`transformers`. **The core sidecar must run fully without it.** This keeps the
frozen installer at ~300 MB instead of 3–5 GB, and makes the "AI unavailable →
continue with OSM" path structural rather than aspirational.

## 2. Georeferenced imagery — non-negotiable (ADR-005)

SAM returns pixels. Grounding DINO returns pixels. `road_mask.geojson` needs
degrees. That conversion exists **only** because we build the image ourselves
from XYZ tiles and keep the transform.

`vision/tiles.py` is written and unit-tested (pixel↔lon/lat round-trips to
4e-09 px). Use it. Persist `mosaic.to_dict()` into `source_manifest.json`.

Set `ROADTWIN_TILE_URL` from the environment. Check the provider's terms, send
a real `User-Agent`, do not commit an API key.

## 3. SAM 2.1 road segmentation

Use `transformers` (`Sam2Model`, `Sam2Processor`) — **never the upstream
`segment-anything-2` repo**, which has a build step that fails on Windows.

**Prompt SAM with the OSM centerline.** Project the centerline into mosaic pixel
coordinates with `Mosaic.lonlat_to_pixel()` and feed those points as positive
prompts. Do not ask SAM to segment everything and then guess which blob is the
road — you already know where the road is. This single change is the difference
between a usable mask and an afternoon of disappointment.

`vision/segment.py` implements this, including sanity warnings when the mask
covers >75% (SAM segmented the whole scene) or <1% (the transform is wrong).

## 4. Lane-count evidence — the quantitative claim

`vision/evidence.py::lane_count_evidence()` measures mask width perpendicular
to the centerline, converts pixels to metres via the mosaic's ground
resolution, and divides by 3.5 m.

It returns `None` when there is not enough usable evidence. **Preserve that
behaviour** — refusing to answer is correct, and emitting a confident lane count
from three noisy samples is how you get caught.

Confidence combines measurement consistency and how close the estimate is to a
whole number of lanes. A width halfway between 3 and 4 lanes reports low
confidence, because that is exactly when a human should look.

## 5. Street-level detection (optional, image-space only)

Use `transformers` `AutoModelForZeroShotObjectDetection` with
`IDEA-Research/grounding-dino-tiny` — **never the IDEA-Research repo**, which
compiles a custom CUDA op at install time and fails on Windows.

Prompt format is lowercase and period-separated:
`"a traffic light. a traffic sign. a road barrier."` The comma/title-case form
scores far worse.

Every detection from a non-georeferenced image is tagged
`geometry_kind: "image_space"` with a `pixel_bbox` and an `attached_to.road_id`,
and **claims no coordinate**. That one field pre-empts the sharpest question a
technical judge can ask.

**No pothole class** (ADR-013).

## 6. Fusion and the review queue

Deterministic. No probabilistic magic.

- observations are **immutable**; rejecting sets `status`, never deletes
- disagreement → REVIEW item
- agreement → AGREEMENT item (show it — corroboration is evidence too)
- low confidence → filtered out
- the human decision is authoritative and recorded

UI per `context/DEMO_SPEC.md`:

```
ROAD FEATURE — lane count

OSM:      no data  (inferred: 2, confidence 40%)
VISION:   3 lanes  (mask width 10.8 m / 3.5 m, confidence 82%)

[ ACCEPT VISION ]   [ KEEP BASELINE ]   [ EDIT ]
```

## 7. Accept → recompile → re-simulate

Accepting creates an `Edit` which flows through `apply_edits()` →
`plain_to_net()` → new `net.xml`, new `road_network.xodr`, new simulation.

Write `validation_report.json`. The invariant
`baseline plain XML + decisions == final model` is tested by `edits.replay()`.
Do not break it.

## 8. Graceful degradation

If the vision sidecar is unavailable or errors, the UI shows
`[ Continue with OSM ]` and the pipeline proceeds. Test this by killing the
sidecar mid-session.

## 9. Cache everything

Mosaic, mask, detections → `assets/benchmark/`. Demo insurance.

---

## Verify before you claim completion

1. `python scripts/selftest.py` → 0 failed
2. a real discrepancy appears in the review queue
3. **accepting it changes the model, net.xml, .xodr AND the simulation result**
4. rejecting preserves the original observation with status REJECTED
5. `validation_report.json` replays to the same final model
6. killing the vision sidecar degrades gracefully with no crash

Item 3 is the money shot of the entire demo. Make sure it is smooth.

Update `context/CURRENT_STATE.md`.
