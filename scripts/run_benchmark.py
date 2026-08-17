#!/usr/bin/env python3
"""THE regression test, the demo backup, and the proof that the pipeline is real.

Run this at the end of every day. If it passes, you have a product. If it
breaks, you broke it in the last few hours and you know exactly where to look.

    python scripts/run_benchmark.py
    python scripts/run_benchmark.py --offline        # cached OSM, no network
    python scripts/run_benchmark.py --edit-lanes 3   # simulate an accepted
                                                     # vision correction

Pipeline:
    location -> Overpass -> netconvert -> plain XML -> [edits] -> netconvert
             -> net.xml + road_network.xodr -> randomTrips -> SUMO baseline
             -> SUMO closure -> metrics -> RoadTwin_Project.zip
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config as C                                          # noqa: E402
from core import provenance as P                            # noqa: E402
from core.acquire import overpass                           # noqa: E402
from core.build import netconvert as NC                     # noqa: E402
from core.export import package as EX                       # noqa: E402
from core.model import edits as ED                          # noqa: E402
from core.sim import demand, metrics as M, run, scenario    # noqa: E402


def step(n: int, msg: str) -> float:
    print(f"\n{'='*70}\n[{n}] {msg}\n{'='*70}")
    return time.time()


def skip_sim_exit_code(roundtrip_ok: bool) -> int:
    """Exit code for a --skip-sim run, given the OpenDRIVE round-trip result.

    Phase 0's whole claim is "--skip-sim produced a VALID network.net.xml and
    road_network.xodr". Before this existed, run_benchmark computed the
    round-trip result, printed PASS/FAIL, and then returned 0 unconditionally --
    so a FAILED OpenDRIVE export still looked like a green Phase 0 gate. The
    round-trip is the only automated evidence the .xodr is real, so it must
    decide the exit code.
    """
    return 0 if roundtrip_ok else 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="use cached OSM only")
    ap.add_argument("--project", default="benchmark")
    ap.add_argument("--edit-lanes", type=int, default=None,
                    help="apply an accepted lane-count correction to the closure edge")
    ap.add_argument("--seeds", type=int, default=None, help="override seed count")
    ap.add_argument("--skip-sim", action="store_true")
    args = ap.parse_args()

    t_all = time.time()
    proj = C.PROJECTS_DIR / args.project
    build = proj / "build"
    sumo_dir = proj / "sumo"
    proj.mkdir(parents=True, exist_ok=True)
    prov = P.ProvenanceLog(proj / "provenance.json")

    seeds = C.SIM["seeds"][: args.seeds] if args.seeds else C.SIM["seeds"]

    # -- 1 location ---------------------------------------------------------
    t = step(1, f"LOCATION  {C.BENCHMARK['name']}")
    location = {
        "name": C.BENCHMARK["name"],
        "lat": C.BENCHMARK["lat"],
        "lon": C.BENCHMARK["lon"],
        "aoi_radius_m": C.BENCHMARK["aoi_radius_m"],
        "crs": "EPSG:4326",
        "confirmed": True,
        "confirmation_method": "benchmark_config",
    }
    (proj / "location.json").write_text(json.dumps(location, indent=2))
    bbox = overpass.bbox_from_point(location["lat"], location["lon"],
                                    location["aoi_radius_m"])
    print(f"    bbox = {tuple(round(v, 5) for v in bbox)}   ({time.time()-t:.1f}s)")

    # -- 2 acquisition ------------------------------------------------------
    t = step(2, "ACQUIRE  OSM via Overpass")
    osm = overpass.fetch_osm(
        bbox, build / "benchmark.osm",
        endpoint=C.OVERPASS["endpoint"],
        user_agent=C.OVERPASS["user_agent"],
        timeout_s=C.OVERPASS["timeout_s"],
        cache_dir=C.BENCHMARK_DIR,
        allow_network=not args.offline,
    )
    prov.add(P.record(source="osm", tool="overpass", outputs=[osm],
                      extra={"bbox": list(bbox), "endpoint": C.OVERPASS["endpoint"]}))
    print(f"    ({time.time()-t:.1f}s)")

    # -- 3 build ------------------------------------------------------------
    t = step(3, "BUILD  netconvert: OSM -> plain XML")
    # bbox is passed so netconvert CLIPS to the AOI. Overpass hands back whole
    # ways that merely touch the bbox, so without this the built network is far
    # larger than aoi_radius_m advertises. See core/build/netconvert.py.
    plain = NC.osm_to_plain(osm, build, aoi_bbox=bbox)
    prov.add(P.record(source="netconvert", tool="netconvert", inputs=[osm],
                      outputs=[plain["net"], plain["edg"], plain["nod"]]))
    edges = scenario.read_net_edges(plain["net"])
    print(f"    {len(edges)} edges, "
          f"{sum(e['num_lanes'] for e in edges.values())} lanes  ({time.time()-t:.1f}s)")
    if not edges:
        print("    FATAL: empty network. Move the benchmark or widen aoi_radius_m.")
        return 2

    # -- 4 choose the experiment edge --------------------------------------
    t = step(4, "SELECT  closure candidate")
    cand = scenario.pick_closure_candidate(plain["net"])
    if not cand:
        print("    FATAL: no multi-lane edge in the AOI. This location cannot "
              "support a lane-closure experiment -- pick another (see Day 0).")
        return 2
    print(f"    edge={cand['edge_id']}  lanes={cand['num_lanes']}  "
          f"length={cand['length_m']}m")

    # -- 5 optional edit (stands in for an accepted vision correction) ------
    if args.edit_lanes:
        t = step(5, f"EDIT  lane count -> {args.edit_lanes} (simulated human accept)")
        e = ED.Edit(edge_id=cand["edge_id"], attribute="numLanes", old_value=None,
                    new_value=str(args.edit_lanes), source="accepted_vision",
                    observation_id="obs-001", confidence=0.82)
        ED.apply_edits(plain["edg"], [e])
        ED.write_validation_report([e], [], proj / "validation_report.json")
        prov.add(P.record(source="human", tool="human",
                          outputs=[proj / "validation_report.json"],
                          extra={"user_action": "accept", "edge": cand["edge_id"]}))

    # -- 6 recompile: network + OpenDRIVE ----------------------------------
    t = step(6, "COMPILE  plain XML -> network.net.xml + road_network.xodr")
    out = NC.plain_to_net(plain, sumo_dir / "network.net.xml",
                          xodr_out=proj / "road_network.xodr")
    prov.add(P.record(source="netconvert", tool="netconvert",
                      inputs=[plain["edg"]], outputs=[out["net"], out["xodr"]]))
    print(f"    xodr = {out['xodr'].stat().st_size/1024:.0f} KB  ({time.time()-t:.1f}s)")

    t = step(7, "VERIFY  re-import our own OpenDRIVE (proves it is valid)")
    ok = NC.verify_xodr_roundtrip(out["xodr"], build / "roundtrip.net.xml")
    print(f"    OpenDRIVE round-trip: {'PASS' if ok else 'FAIL'}")

    if args.skip_sim:
        code = skip_sim_exit_code(ok)
        if code:
            print("\n--skip-sim stopping here, but the OpenDRIVE round-trip FAILED.")
            print("   road_network.xodr is not verifiably valid. Phase 0 is NOT green.")
        else:
            print("\n--skip-sim set, stopping here.")
        return code

    # -- 8 demand -----------------------------------------------------------
    t = step(8, f"DEMAND  randomTrips period={C.SIM['period']}")
    d = demand.generate_routes(
        out["net"], sumo_dir,
        begin=C.SIM["begin"], end=C.SIM["end"], period=C.SIM["period"],
        fringe_factor=C.SIM["fringe_factor"], seed=seeds[0],
    )
    print(f"    ({time.time()-t:.1f}s)")

    # -- 9 scenario ---------------------------------------------------------
    t = step(9, "SCENARIO  lane closure additional-file")
    closure_lane = cand["num_lanes"] - 1          # close the leftmost lane
    desc = scenario.build_lane_closure(
        out["net"], sumo_dir / "closure.add.xml",
        edge_id=cand["edge_id"], lane_index=closure_lane,
        begin=C.CLOSURE["begin"], end=C.CLOSURE["end"],
    )
    (proj / "scenario.json").write_text(json.dumps(desc, indent=2))

    # -- 10 experiment ------------------------------------------------------
    t = step(10, f"SIMULATE  baseline vs closure, {len(seeds)} seeds")
    result = run.run_experiment(
        out["net"], d["routes"], sumo_dir / "results",
        sumo_dir / "closure.add.xml",
        seeds=seeds, begin=C.SIM["begin"], end=C.SIM["end"],
        closed_edge=cand["edge_id"],
    )
    (proj / "metrics.json").write_text(json.dumps(
        {k: v for k, v in result.items() if k != "table"}, indent=2))
    print()
    print(result["table"])
    print(f"    ({time.time()-t:.1f}s)")

    # -- 11 export ----------------------------------------------------------
    t = step(11, "EXPORT  RoadTwin_Project.zip")
    EX.write_source_manifest(proj, prov.entries)
    EX.write_readme(proj, location=location, results_table=result["table"])
    zp = EX.export_project(proj, proj.parent / f"RoadTwin_Project_{args.project}.zip")

    print(f"\n{'='*70}")
    print(f"DONE in {time.time()-t_all:.1f}s   ->  {zp}")
    print(f"{'='*70}")
    if not result["comparison"]["significant"]:
        print("\n!! The closure did not move the metrics beyond seed noise.")
        print("   Lower SIM['period'] in config.py and re-run. Do not demo this.")
        return 1
    return 0


if __name__ == "__main__":
    # Our own errors carry actionable messages. Print them cleanly rather than
    # burying the useful sentence under a traceback -- you will read this
    # output a hundred times over five days.
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"\n{'='*70}\nPIPELINE STOPPED\n{'='*70}\n{exc}\n")
        raise SystemExit(2)
    except KeyboardInterrupt:
        print("\ninterrupted")
        raise SystemExit(130)
