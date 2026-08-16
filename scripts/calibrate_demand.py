"""Automated demand calibration loop.

Iterates period values and picks the one where closure delta is 20-60%
with no teleport warnings. Run this once on Day 3.

Usage:
    python scripts/calibrate_demand.py
    python scripts/calibrate_demand.py --edge 568057022#0 --lane 3
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config as C
from core.build.netconvert import plain_to_net, osm_to_plain
from core.sim import demand, run, scenario
from core.acquire.overpass import fetch_osm, bbox_from_point


def build_network() -> tuple[dict, Path]:
    """Return (plain_files, net_file). Uses cache — does not re-download OSM."""
    proj = C.PROJECTS_DIR / "benchmark"
    build = proj / "build"
    build.mkdir(parents=True, exist_ok=True)

    bbox = bbox_from_point(C.BENCHMARK["lat"], C.BENCHMARK["lon"], C.BENCHMARK["aoi_radius_m"])
    osm = fetch_osm(
        bbox, build / "benchmark.osm",
        endpoint=C.OVERPASS["endpoint"],
        user_agent=C.OVERPASS["user_agent"],
        timeout_s=C.OVERPASS["timeout_s"],
        cache_dir=C.BENCHMARK_DIR,
        allow_network=False,   # never re-download during calibration
    )
    plain = osm_to_plain(osm, build)
    net_result = plain_to_net(plain, proj / "sumo" / "network.net.xml",
                               xodr_out=proj / "road_network.xodr")
    return plain, net_result["net"]


def calibrate_period(
    net_file: Path,
    edge_id: str,
    lane_index: int,
    period: float,
    *,
    seed: int = 42,
) -> dict:
    """One calibration iteration: generate routes, run 1-seed experiment, return result."""
    proj = C.PROJECTS_DIR / "benchmark"
    work = proj / "sumo" / "calibrate"

    # Generate routes
    d = demand.generate_routes(
        net_file, work,
        begin=C.SIM["begin"], end=C.SIM["end"],
        period=period, fringe_factor=C.SIM["fringe_factor"],
        seed=seed, prefix="calib",
    )

    # Build closure
    closure_file = work / "closure.add.xml"
    desc = scenario.build_lane_closure(
        net_file, closure_file,
        edge_id=edge_id, lane_index=lane_index,
        begin=C.CLOSURE["begin"], end=C.CLOSURE["end"],
    )

    # Run 1-seed experiment
    result = run.run_experiment(
        net_file, d["routes"], work / "results", closure_file,
        seeds=[seed], begin=C.SIM["begin"], end=C.SIM["end"],
        closed_edge=edge_id,
    )

    cmp = result["comparison"]
    base_tt = result["baseline"].get("avg_travel_time_s")
    clos_tt = result["closure"].get("avg_travel_time_s")
    teleports = result["baseline"].get("warnings", []) + result["closure"].get("warnings", [])
    delta_pct = cmp["rows"][0].get("delta_pct") if cmp["rows"] else None

    return {
        "period":        period,
        "veh_count":     d["count"],
        "base_tt_s":     base_tt,
        "clos_tt_s":     clos_tt,
        "delta_pct":     delta_pct,
        "significant":   cmp["significant"],
        "verdict":       cmp["verdict"],
        "has_teleports": bool(teleports),
        "table":         result["table"],
        "desc":          desc,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--edge", default=None,
                    help="edge to close (default: pick_closure_candidate)")
    ap.add_argument("--lane", type=int, default=None,
                    help="lane index to close (default: topmost, num_lanes-1)")
    ap.add_argument("--periods", default="0.2,0.3,0.4,0.5,0.6,0.8",
                    help="comma-separated periods to try (ascending)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    print("\n=== DEMAND CALIBRATION LOOP ===")
    print("Target: delta 20-60%, zero teleports\n")

    _, net_file = build_network()

    # Resolve edge
    edges = scenario.read_net_edges(net_file)
    if args.edge:
        edge_id = args.edge
        if edge_id not in edges:
            print(f"ERROR: edge '{edge_id}' not in network")
            return 2
    else:
        cand = scenario.pick_closure_candidate(net_file)
        if not cand:
            print("ERROR: no closure candidate found")
            return 2
        edge_id = cand["edge_id"]

    lane_index = args.lane if args.lane is not None else edges[edge_id]["num_lanes"] - 1
    print(f"Edge: {edge_id}  lanes={edges[edge_id]['num_lanes']}  "
          f"len={edges[edge_id]['length_m']:.0f}m  closing lane {lane_index}\n")

    periods = sorted([float(p) for p in args.periods.split(",")], reverse=True)
    best = None

    print(f"{'PERIOD':>8}  {'VEHICLES':>9}  {'BASE_TT':>9}  {'CLOS_TT':>9}  "
          f"{'DELTA%':>8}  {'TELEPORTS':>10}  STATUS", flush=True)
    print("-" * 80, flush=True)

    for period in periods:
        try:
            print(f"Testing period {period:.2f}...", end="\r", flush=True)
            r = calibrate_period(net_file, edge_id, lane_index, period, seed=args.seed)
        except Exception as exc:
            print(f"{period:8.2f}  ERROR: {exc}", flush=True)
            continue

        base = f"{r['base_tt_s']:.1f}s" if r['base_tt_s'] else "N/A"
        clos = f"{r['clos_tt_s']:.1f}s" if r['clos_tt_s'] else "N/A"
        delta = f"{r['delta_pct']:+.1f}%" if r['delta_pct'] is not None else "N/A"
        tele = "YES" if r['has_teleports'] else "no"

        # Is this a good calibration?
        good = (
            r['delta_pct'] is not None
            and 15.0 <= r['delta_pct'] <= 70.0
            and not r['has_teleports']
            and r['significant']
        )
        status = "✓ CALIBRATED" if good else ("TELEPORT" if r['has_teleports'] else "...")

        print(f"{period:8.2f}  {r['veh_count']:9d}  {base:>9}  {clos:>9}  "
              f"{delta:>8}  {tele:>10}  {status}", flush=True)

        if good and best is None:
            best = r

        # Stop once we have a good result and the next period might gridlock
        if r['has_teleports'] and best:
            print("\nTeleports detected — stopping (have a good result already)")
            break

    print()
    if best:
        print("=" * 80)
        print(f"BEST PERIOD: {best['period']}")
        print()
        print(best['table'])
        print()
        print("Write this into config.py:")
        print(f"    SIM['period'] = {best['period']}")
        print()
        print("Write this into context/CURRENT_STATE.md CALIBRATION RECORD:")
        print(f"    SIM.period            = {best['period']}")
        print(f"    vehicles generated    = {best['veh_count']}")
        print(f"    baseline travel time  = {best['base_tt_s']}s")
        print(f"    closure edge          = {edge_id}")
        print(f"    closure lane index    = {lane_index}")
        print(f"    actual closed length  = {best['desc']['actual_closed_length_m']}m")
        print(f"    closure travel time   = {best['clos_tt_s']}s")
        print(f"    delta travel time     = {best['delta_pct']:+.1f}%")
        return 0
    else:
        print("!! No period found that gives 20-60% delta without teleports.")
        print("   Try a smaller AOI or different benchmark location.")
        print("   Or try --edge with a shorter / more critical road.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
