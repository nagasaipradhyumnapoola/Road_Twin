"""Turning a segmentation mask into a lane-count claim.

This is the project's primary QUANTITATIVE ai result, and the one worth
demoing. "Grounding DINO found a traffic light" is a picture. "The road surface
is 10.8 m wide, therefore 3 lanes, therefore OSM's 2 is wrong, confidence 0.82"
is an engineering finding, and it is the discrepancy the whole review UI exists
to resolve.

Method: sample points along the OSM centerline, measure the mask width along
the perpendicular at each, convert pixels to metres with the mosaic's ground
resolution, divide by nominal lane width.

Deliberately measured in RASTER space, not with polygon geometry. It needs only
numpy (no shapely, no pyproj), it is more robust to ragged mask edges, and it
is trivially unit-testable -- see scripts/selftest.py.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np


def _unit_normal(p_prev: tuple[float, float], p_next: tuple[float, float]) -> tuple[float, float]:
    dx, dy = p_next[0] - p_prev[0], p_next[1] - p_prev[1]
    n = math.hypot(dx, dy)
    if n == 0:
        return 0.0, 0.0
    return -dy / n, dx / n          # rotate tangent by 90 degrees


def measure_width_px(
    mask: np.ndarray,
    point: tuple[float, float],
    normal: tuple[float, float],
    *,
    max_halfwidth_px: int = 200,
    gap_tolerance_px: int = 3,
) -> float | None:
    """Walk out from `point` along +/- `normal` while the mask stays True.

    gap_tolerance_px bridges lane markings and small holes in the mask, which
    otherwise cut a perfectly good measurement in half.
    """
    h, w = mask.shape
    nx, ny = normal
    if nx == 0 and ny == 0:
        return None

    px, py = point
    if not (0 <= int(round(py)) < h and 0 <= int(round(px)) < w):
        return None
    if not mask[int(round(py)), int(round(px))]:
        return None                 # centerline not on the road: reject sample

    total = 0.0
    for sign in (1, -1):
        gap = 0
        steps = 0
        for s in range(1, max_halfwidth_px + 1):
            x = int(round(px + sign * nx * s))
            y = int(round(py + sign * ny * s))
            if not (0 <= y < h and 0 <= x < w):
                break
            if mask[y, x]:
                steps = s
                gap = 0
            else:
                gap += 1
                if gap > gap_tolerance_px:
                    break
        total += steps
    return total + 1.0              # +1 for the centre pixel itself


def lane_count_evidence(
    mask: np.ndarray,
    centerline_px: Sequence[tuple[float, float]],
    meters_per_pixel: float,
    *,
    lane_width_m: float = 3.5,
    max_halfwidth_px: int = 200,
    min_samples: int = 5,
) -> dict[str, Any] | None:
    """Estimate lane count from mask width along the centerline.

    Returns None when there is not enough usable evidence -- which is the
    correct behaviour. Emitting a confident lane count from three noisy samples
    is how you get caught.
    """
    if len(centerline_px) < 3:
        return None

    widths_px: list[float] = []
    for i in range(1, len(centerline_px) - 1):
        normal = _unit_normal(centerline_px[i - 1], centerline_px[i + 1])
        wpx = measure_width_px(mask, centerline_px[i], normal,
                               max_halfwidth_px=max_halfwidth_px)
        if wpx:
            widths_px.append(wpx)

    if len(widths_px) < min_samples:
        return None

    arr = np.asarray(widths_px, dtype=float)
    # trim the tails: junctions and driveways make the mask locally very wide
    lo, hi = np.percentile(arr, [10, 90])
    trimmed = arr[(arr >= lo) & (arr <= hi)]
    if trimmed.size < 3:
        trimmed = arr

    median_px = float(np.median(trimmed))
    width_m = median_px * meters_per_pixel
    raw_lanes = width_m / lane_width_m
    lanes = max(1, int(round(raw_lanes)))

    # Confidence has two components:
    #   consistency -- how stable the width is along the road
    #   integrality -- how close the estimate is to a whole number of lanes
    cv = float(np.std(trimmed) / max(np.mean(trimmed), 1e-6))
    consistency = max(0.0, 1.0 - min(cv / 0.30, 1.0))
    integrality = 1.0 - 2.0 * abs(raw_lanes - round(raw_lanes))
    # Weighted evenly on purpose. A width that sits halfway between 3 and 4
    # lanes is exactly the case a human should adjudicate, so integrality must
    # be able to drag confidence down even when the measurement is very stable.
    confidence = round(max(0.0, min(1.0, 0.5 * consistency + 0.5 * integrality)), 3)

    return {
        "feature": "lane_count",
        "value": lanes,
        "raw_estimate": round(raw_lanes, 2),
        "measured_width_m": round(width_m, 2),
        "assumed_lane_width_m": lane_width_m,
        "samples": len(widths_px),
        "samples_used": int(trimmed.size),
        "width_cv": round(cv, 3),
        "confidence": confidence,
        "method": "mask width perpendicular to OSM centerline / nominal lane width",
    }


def make_observation(
    obs_id: str,
    evidence: dict[str, Any],
    road_id: str,
    *,
    source: str = "sam2",
    model: str = "facebook/sam2.1-hiera-small",
) -> dict[str, Any]:
    """Wrap evidence in the canonical observation envelope.

    status is always REVIEW. AI never commits (ADR-002).
    """
    return {
        "id": obs_id,
        "source": source,
        "model": model,
        "type": "lane_count_estimate",
        "feature": evidence["feature"],
        "value": evidence["value"],
        "geometry_kind": "georeferenced",
        "attached_to": {"road_id": road_id},
        "confidence": evidence["confidence"],
        "status": "REVIEW",
        "evidence": evidence,
    }


def build_review_items(
    observations: list[dict[str, Any]],
    baseline: dict[str, dict[str, Any]],
    *,
    min_confidence: float = 0.4,
) -> list[dict[str, Any]]:
    """Deterministic fusion: compare evidence to baseline, emit review items.

    No probabilistic magic. A disagreement becomes a question for the engineer,
    never an automatic overwrite (ADR-002). Agreement is recorded too -- it is
    corroboration, and it is worth showing.
    """
    items = []
    for obs in observations:
        road_id = obs.get("attached_to", {}).get("road_id")
        base = baseline.get(road_id)
        if base is None:
            continue
        base_val = base.get("lane_count")
        obs_val = obs.get("value")
        if obs.get("confidence", 0) < min_confidence:
            continue

        items.append({
            "id": f"review-{obs['id']}",
            "road_id": road_id,
            "feature": obs.get("feature", "lane_count"),
            "baseline_value": base_val,
            "baseline_provenance": base.get("lane_count_provenance", {}),
            "observed_value": obs_val,
            "observation_id": obs["id"],
            "confidence": obs["confidence"],
            "evidence": obs.get("evidence", {}),
            "agrees": base_val == obs_val,
            "status": "AGREEMENT" if base_val == obs_val else "REVIEW",
            "actions": ["ACCEPT_VISION", "KEEP_BASELINE", "EDIT"],
        })
    return items
