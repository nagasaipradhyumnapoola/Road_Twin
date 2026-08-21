#!/usr/bin/env python3
"""Phase 7: Visual evidence extraction pipeline.

Pipeline:
    Location BBox -> XYZ Tile Mosaic -> Georeferenced PNG + Transform
    -> OSM Centerline Densification -> SAM 2.1 Road Surface Mask
    -> Mask Width Sampling -> Lane Count Quantitative Claim
    -> observations.json + road_mask.geojson -> Cache to assets/benchmark/

Usage:
    .venv-vision\Scripts\python scripts/run_vision.py
    .venv-vision\Scripts\python scripts/run_vision.py --project benchmark
    .venv-vision\Scripts\python scripts/run_vision.py --offline  # use cached mosaic
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config as C
from core.acquire.overpass import bbox_from_point
from core.model.geometry import NetGeo, edge_centerline_lonlat, densify_lonlat
from vision import tiles, segment, evidence


def step(n: int, msg: str) -> float:
    print(f"\n{'='*70}\n[7.{n}] {msg}\n{'='*70}", flush=True)
    return time.time()


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 7: Visual Evidence Extraction")
    ap.add_argument("--project", default="benchmark", help="project directory name")
    ap.add_argument("--zoom", type=int, default=18, help="XYZ tile zoom level (18 = ~0.5m/px, 19 = ~0.25m/px)")
    ap.add_argument("--edge", default=None, help="override edge ID to segment (default: best multi-lane road)")
    ap.add_argument("--offline", action="store_true", help="use cached mosaic only")
    ap.add_argument("--device", default=None, help="torch device: 'cuda' or 'cpu'")
    args = ap.parse_args()

    t_all = time.time()
    proj = C.PROJECTS_DIR / args.project
    vision_dir = proj / "vision"
    vision_dir.mkdir(parents=True, exist_ok=True)
    benchmark_cache = C.BENCHMARK_DIR

    # -------------------------------------------------------------------------
    # 7.1 Location & Bounding Box
    # -------------------------------------------------------------------------
    t = step(1, "LOCATION & AOI Bounding Box")
    loc_file = proj / "location.json"
    if loc_file.exists():
        location = json.loads(loc_file.read_text(encoding="utf-8"))
    else:
        location = {
            "name": C.BENCHMARK["name"],
            "lat": C.BENCHMARK["lat"],
            "lon": C.BENCHMARK["lon"],
            "aoi_radius_m": C.BENCHMARK["aoi_radius_m"],
            "crs": "EPSG:4326",
            "confirmed": True,
            "confirmation_method": "benchmark_config",
        }
        loc_file.write_text(json.dumps(location, indent=2), encoding="utf-8")

    bbox = bbox_from_point(location["lat"], location["lon"], location["aoi_radius_m"])
    print(f"    Location: {location['name']} ({location['lat']:.5f}, {location['lon']:.5f})")
    print(f"    BBox: south={bbox[0]:.5f}, west={bbox[1]:.5f}, north={bbox[2]:.5f}, east={bbox[3]:.5f}  ({time.time()-t:.1f}s)", flush=True)

    # -------------------------------------------------------------------------
    # 7.2 Georeferenced Mosaic (ADR-005)
    # -------------------------------------------------------------------------
    t = step(2, "GEOREFERENCED MOSAIC (aerial XYZ tiles)")
    mosaic_png = vision_dir / "mosaic.png"
    cached_mosaic_png = benchmark_cache / "mosaic.png"

    def _write_manifest(extra: dict) -> Path:
        """Merge into source_manifest.json -- never clobber sibling keys."""
        mf = proj / "source_manifest.json"
        data: dict = {}
        if mf.exists():
            try:
                loaded = json.loads(mf.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = loaded
            except Exception:
                data = {}
        data.update(extra)
        mf.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return mf

    def _insufficient(reason: str, imagery_meta: dict) -> int:
        """Honest refusal: no mosaic, mask, or lane count is fabricated."""
        (proj / "observations.json").write_text("[]", encoding="utf-8")
        _write_manifest({
            "imagery": imagery_meta,
            "vision_status": {"sufficient": False, "reason": reason},
        })
        print(f"\n    [INSUFFICIENT EVIDENCE] {reason}", flush=True)
        print("    observations.json = []  (no road or lane count invented).", flush=True)
        print(f"\n{'='*70}\nPHASE 7 COMPLETE (insufficient evidence) in "
              f"{time.time()-t_all:.1f}s\n{'='*70}", flush=True)
        return 0

    # --- Aerial imagery gate (ADR-005 / P7) -------------------------------------
    # Lane WIDTH is a physical measurement; it can only come from genuine overhead
    # imagery. An OSM cartographic raster draws roads as fixed-width casings, so
    # measuring it yields nonsense (the 51 m / 15-lane benchmark artifact). Require
    # an explicitly-declared aerial source; otherwise refuse. Never substitute
    # street tiles silently.
    tile_url = C.IMAGERY.get("tile_url", "").strip()
    user_agent = C.IMAGERY.get("user_agent") or "RoadTwin-DigitalTwin-Research/0.1.0"
    declared_aerial = bool(C.IMAGERY.get("aerial", False))
    _cartographic_hints = ("openstreetmap.org", "opentopomap", "cartocdn",
                           "stamen", "wikimedia.org/osm", "/osm/")
    host = tile_url.split("/")[2] if "://" in tile_url else (tile_url[:48] or "<unset>")
    is_cartographic = (not tile_url) or any(h in tile_url.lower() for h in _cartographic_hints)
    aerial_ok = bool(tile_url) and declared_aerial and not is_cartographic
    imagery_meta = {
        "tile_url_host": host,
        "declared_aerial": declared_aerial,
        "cartographic_source": is_cartographic,
        "aerial": aerial_ok,
        "source": "aerial-xyz" if aerial_ok else ("cartographic-osm" if is_cartographic else "unknown"),
        "user_agent": user_agent,
        "crs": "EPSG:4326",
    }
    print(f"    Imagery source: host={host} declared_aerial={declared_aerial} "
          f"cartographic={is_cartographic} -> aerial_ok={aerial_ok}")
    if not aerial_ok:
        return _insufficient(
            "no aerial imagery source configured (set ROADTWIN_TILE_URL to an "
            "aerial/satellite XYZ provider and ROADTWIN_TILE_AERIAL=1). OSM "
            "cartographic tiles are not measurable for lane width.",
            imagery_meta,
        )

    m_planned = tiles.plan_mosaic(bbox, args.zoom)
    print(f"    Planned: {m_planned.width_px}x{m_planned.height_px}px @ zoom {args.zoom} ({m_planned.meters_per_pixel():.3f} m/px)")

    # Always stitch from the per-TILE cache; the whole-mosaic shortcut is gone
    # because a filename+size key silently served a stale mosaic under a different
    # location or a dead host. The tile cache is keyed by z/x/y AND by imagery HOST
    # -- a per-tile cache shared across sources would let a dead or swapped host
    # silently reuse another provider's tiles, which is the same substitution one
    # level down. A dead host therefore has an empty cache -> real fetch -> refuse.
    import re as _re
    host_slug = _re.sub(r"[^a-z0-9.]+", "_", host.lower()) or "unknown"
    tile_cache_dir = benchmark_cache / f"tiles_{host_slug}"
    try:
        mosaic = tiles.fetch_mosaic(
            bbox, args.zoom, tile_url, mosaic_png,
            user_agent=user_agent,
            max_tiles=int(C.IMAGERY.get("max_tiles", 64)),
            cache_dir=tile_cache_dir,
        )
        if mosaic_png.exists():
            import shutil
            shutil.copy(mosaic_png, cached_mosaic_png)
    except Exception as exc:
        # No synthetic canvas. Imagery unavailable -> insufficient evidence.
        return _insufficient(f"aerial tile download failed: {exc}", imagery_meta)

    # Persist mosaic transform + imagery source (merge, so export cannot clobber).
    import hashlib
    try:
        imagery_meta["mosaic_sha256"] = hashlib.sha256(mosaic_png.read_bytes()).hexdigest()
    except Exception:
        pass
    _write_manifest({
        "mosaic": mosaic.to_dict(),
        "imagery": imagery_meta,
        "vision_status": {"sufficient": True, "reason": "aerial imagery present"},
    })
    print(f"    Mosaic transform + imagery source persisted to source_manifest.json  ({time.time()-t:.1f}s)", flush=True)

    # -------------------------------------------------------------------------
    # 7.3 Centerline Extraction & Pixel Projection
    # -------------------------------------------------------------------------
    t = step(3, "CENTERLINE PROJECTION (OSM -> Mosaic Pixels)")
    net_file = proj / "sumo" / "network.net.xml"
    if not net_file.exists():
        net_file = proj / "build" / "network.net.xml"
    if not net_file.exists():
        raise RuntimeError(f"Compiled network not found at {net_file}. Run baseline pipeline first.")

    from core.sim.scenario import read_net_edges, pick_closure_candidate
    edges = read_net_edges(net_file)
    geo = NetGeo(net_file)

    target_edge = args.edge
    valid_px: list[tuple[float, float]] = []

    if target_edge and target_edge in edges:
        raw_centerline = edge_centerline_lonlat(net_file, target_edge, geo=geo)
        densified_line = densify_lonlat(raw_centerline, every_m=10.0)
        centerline_px = [mosaic.lonlat_to_pixel(lon, lat) for lon, lat in densified_line]
        valid_px = [pt for pt in centerline_px if 0 <= pt[0] < mosaic.width_px and 0 <= pt[1] < mosaic.height_px]
    else:
        # Find best candidate with valid in-bounds centerline
        sorted_candidates = sorted(
            edges.items(),
            key=lambda item: (item[1]["num_lanes"], item[1]["length_m"]),
            reverse=True,
        )
        for eid, info in sorted_candidates:
            try:
                raw_cl = edge_centerline_lonlat(net_file, eid, geo=geo)
                dens_cl = densify_lonlat(raw_cl, every_m=10.0)
                px_cl = [mosaic.lonlat_to_pixel(lon, lat) for lon, lat in dens_cl]
                in_bounds = [pt for pt in px_cl if 0 <= pt[0] < mosaic.width_px and 0 <= pt[1] < mosaic.height_px]
                if len(in_bounds) >= 5:
                    target_edge = eid
                    valid_px = in_bounds
                    raw_centerline = raw_cl
                    densified_line = dens_cl
                    centerline_px = px_cl
                    break
            except Exception:
                continue

    if not target_edge or not valid_px:
        # Fallback to first available edge
        cand = pick_closure_candidate(net_file)
        target_edge = cand["edge_id"] if cand else list(edges.keys())[0]
        raw_centerline = edge_centerline_lonlat(net_file, target_edge, geo=geo)
        densified_line = densify_lonlat(raw_centerline, every_m=10.0)
        centerline_px = [mosaic.lonlat_to_pixel(lon, lat) for lon, lat in densified_line]
        valid_px = [pt for pt in centerline_px if 0 <= pt[0] < mosaic.width_px and 0 <= pt[1] < mosaic.height_px]
        if not valid_px:
            valid_px = centerline_px

    edge_info = edges[target_edge]
    print(f"    Target edge: '{target_edge}' ({edge_info['num_lanes']} lanes, {edge_info['length_m']:.1f}m)")
    print(f"    Centerline: {len(raw_centerline)} raw points -> {len(densified_line)} densified points (every 10m)")
    print(f"    In-bounds pixel coords: {len(valid_px)} pts (first: ({valid_px[0][0]:.1f}, {valid_px[0][1]:.1f}), last: ({valid_px[-1][0]:.1f}, {valid_px[-1][1]:.1f}))  ({time.time()-t:.1f}s)", flush=True)

    # -------------------------------------------------------------------------
    # 7.4 SAM 2.1 Road Surface Segmentation
    # -------------------------------------------------------------------------
    t = step(4, "SAM 2.1 ROAD SURFACE SEGMENTATION")
    mask_geojson_path = proj / "road_mask.geojson"

    try:
        mask = segment.segment_road(
            mosaic_png,
            valid_px,
            max_points=24,
            device=args.device,
        )
        print(f"    SAM inference completed on {mask.shape[1]}x{mask.shape[0]} canvas")
    except Exception as exc:
        # No synthetic ribbon. SAM unavailable/failed -> insufficient evidence.
        return _insufficient(f"SAM segmentation unavailable/failed: {exc}", imagery_meta)

    road_mask_geojson = segment.mask_to_geojson(mask, mosaic)
    mask_geojson_path.write_text(json.dumps(road_mask_geojson, indent=2), encoding="utf-8")
    print(f"    road_mask.geojson written ({len(road_mask_geojson['features'])} feature(s))  ({time.time()-t:.1f}s)", flush=True)

    # -------------------------------------------------------------------------
    # 7.5 Lane Count Evidence (Quantitative Claim)
    # -------------------------------------------------------------------------
    t = step(5, "LANE-COUNT EVIDENCE EXTRACTION")
    ev = evidence.lane_count_evidence(
        mask,
        valid_px,
        mosaic.meters_per_pixel(),
        lane_width_m=float(C.VISION.get("nominal_lane_width_m", 3.5)),
        max_lanes=int(C.VISION.get("max_plausible_lanes", 8)),
    )

    if ev:
        print(f"    Measured width: {ev['measured_width_m']:.2f} m")
        print(f"    Estimated lanes: {ev['value']} (raw estimate: {ev['raw_estimate']:.2f})")
        print(f"    Samples: {ev['samples_used']}/{ev['samples']} valid  (overlap {ev['overlap_ratio']:.2f})")
        print(f"    Confidence score: {ev['confidence']*100:.1f}%")
        obs_id = "obs-001"
        obs = evidence.make_observation(obs_id, ev, road_id=f"rt-road-{target_edge}")
        obs_list = [obs]
    else:
        print("    [evidence] Insufficient/implausible evidence -> Refused estimate (honest refusal)")
        obs_list = []

    # Final imagery/evidence status reflects the ACTUAL outcome, not merely that a
    # mosaic was fetched. Aerial present but a refused mask -> sufficient=False.
    _write_manifest({"vision_status": {
        "sufficient": bool(obs_list),
        "reason": ("lane evidence produced" if obs_list else
                   "aerial imagery present but SAM mask yielded no plausible lane "
                   "evidence (implausible width or insufficient road overlap)"),
    }})

    # Write observations.json
    obs_file = proj / "observations.json"
    obs_file.write_text(json.dumps(obs_list, indent=2), encoding="utf-8")
    print(f"    observations.json written ({len(obs_list)} observation(s))  ({time.time()-t:.1f}s)", flush=True)

    # -------------------------------------------------------------------------
    # 7.6 Cache to assets/benchmark/
    # -------------------------------------------------------------------------
    t = step(6, "CACHE TO assets/benchmark/")
    import shutil
    benchmark_cache.mkdir(parents=True, exist_ok=True)
    if mask_geojson_path.exists():
        shutil.copy(mask_geojson_path, benchmark_cache / "road_mask.geojson")
    if obs_file.exists():
        shutil.copy(obs_file, benchmark_cache / "observations.json")
    if mosaic_png.exists():
        shutil.copy(mosaic_png, benchmark_cache / "mosaic.png")
    print(f"    Artifacts cached into assets/benchmark/  ({time.time()-t:.1f}s)", flush=True)

    print(f"\n{'='*70}")
    print(f"PHASE 7 COMPLETE in {time.time()-t_all:.1f}s")
    print(f"{'='*70}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
