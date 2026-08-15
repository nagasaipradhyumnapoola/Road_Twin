#!/usr/bin/env python3
"""Unit tests for everything that does NOT shell out to SUMO.

    python scripts/selftest.py

These run in seconds with no network and no SUMO, so run them constantly.
They cover the logic that is easy to get subtly and silently wrong:

  - tile georeferencing        (a bug here quietly ruins every AI coordinate)
  - lane-count evidence math   (a bug here quietly ruins your headline claim)
  - SUMO output parsing        (a bug here quietly ruins your metrics)
  - plain-XML lane edits       (a bug here quietly ruins the edit->recompile loop)
  - closure scenario XML       (a bug here means the closure silently does nothing)

The netconvert/sumo subprocess calls cannot be covered here; they are covered
by scripts/run_benchmark.py on a machine with SUMO installed.
"""
from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL {name}  {detail}")


def section(t: str) -> None:
    print(f"\n{t}\n" + "-" * len(t))


# ===========================================================================
def test_tiles():
    section("vision/tiles.py  -- georeferencing (audit item B2)")
    from vision.tiles import (Mosaic, deg2num, ground_resolution, num2deg,
                              plan_mosaic)

    lat, lon, z = 12.8231, 80.0442, 19

    x, y = deg2num(lat, lon, z)
    blat, blon = num2deg(x, y, z)
    check("deg2num/num2deg agree to sub-tile precision",
          abs(blat - lat) < 0.001 and abs(blon - lon) < 0.001,
          f"tile=({x},{y})")

    res = ground_resolution(lat, z)
    check("ground resolution sane at z19 (~0.25 m/px)", 0.2 < res < 0.35,
          f"{res:.4f} m/px")
    check("resolution halves per zoom level",
          abs(ground_resolution(lat, z) * 2 - ground_resolution(lat, z - 1)) < 1e-9)

    d = 500 / 111320.0
    m = plan_mosaic((lat - d, lon - d, lat + d, lon + d), z)
    check("mosaic covers the requested bbox",
          m.west <= lon - d and m.east >= lon + d
          and m.south <= lat - d and m.north >= lat + d,
          f"{m.width_px}x{m.height_px}px")

    # the transform must round-trip: this is the assertion the whole
    # vision->GeoJSON path rests on
    worst = 0.0
    for fx in (0.05, 0.25, 0.5, 0.75, 0.95):
        for fy in (0.05, 0.25, 0.5, 0.75, 0.95):
            px, py = fx * m.width_px, fy * m.height_px
            lo, la = m.pixel_to_lonlat(px, py)
            bx, by = m.lonlat_to_pixel(lo, la)
            worst = max(worst, math.hypot(bx - px, by - py))
    check("pixel->lonlat->pixel round-trip < 0.01 px", worst < 0.01,
          f"worst {worst:.2e} px")

    # a known distance should measure correctly through the transform
    lo1, la1 = m.pixel_to_lonlat(0, m.height_px / 2)
    lo2, la2 = m.pixel_to_lonlat(1000, m.height_px / 2)
    east_m = (lo2 - lo1) * 111320.0 * math.cos(math.radians(la1))
    expect = 1000 * m.meters_per_pixel()
    check("1000 px measures the expected ground distance",
          abs(east_m - expect) / expect < 0.02,
          f"{east_m:.1f}m vs {expect:.1f}m")


# ===========================================================================
def test_evidence():
    section("vision/evidence.py  -- lane-count claim from a mask")
    from vision.evidence import build_review_items, lane_count_evidence

    H, W = 400, 800
    mpp = 0.25                      # metres per pixel, z19-ish

    def band(width_m: float) -> tuple[np.ndarray, list]:
        half = int(round((width_m / mpp) / 2))
        mask = np.zeros((H, W), dtype=bool)
        mask[H // 2 - half: H // 2 + half, :] = True
        centre = [(float(x), float(H // 2)) for x in range(20, W - 20, 20)]
        return mask, centre

    for true_m, want_lanes in [(7.0, 2), (10.5, 3), (14.0, 4)]:
        mask, centre = band(true_m)
        ev = lane_count_evidence(mask, centre, mpp)
        check(f"{true_m} m band -> {want_lanes} lanes",
              ev is not None and ev["value"] == want_lanes,
              f"measured {ev['measured_width_m']}m -> {ev['value']} lanes, "
              f"conf {ev['confidence']}" if ev else "None")

    mask, centre = band(10.5)
    ev = lane_count_evidence(mask, centre, mpp)
    check("clean mask yields high confidence", ev["confidence"] > 0.8,
          f"conf={ev['confidence']}")

    # Ragged edges -> lower confidence. Reporting 0.95 on a mask whose width
    # swings by 40% is the failure mode that gets a demo torn apart, so the
    # confidence formula must actually react to width VARIANCE.
    rng = np.random.default_rng(0)
    noisy = np.zeros((H, W), dtype=bool)
    for x in range(W):
        half = int(round((10.5 / mpp) / 2)) + int(rng.integers(-9, 10))
        noisy[max(H // 2 - half, 0): min(H // 2 + half, H), x] = True
    ev2 = lane_count_evidence(noisy, centre, mpp)
    check("variable-width mask reports materially lower confidence",
          ev2 is not None and ev2["confidence"] < ev["confidence"] - 0.1,
          f"noisy {ev2['confidence']} vs clean {ev['confidence']}" if ev2 else "None")

    # A width that sits halfway between 3 and 4 lanes must NOT be reported
    # confidently -- that is exactly when the engineer needs to look.
    amb, amb_c = band(12.25)        # 3.5 lanes
    ev3 = lane_count_evidence(amb, amb_c, mpp)
    check("ambiguous width (3.5 lanes) reports low confidence",
          ev3 is not None and ev3["confidence"] < 0.65,
          f"conf={ev3['confidence']} raw={ev3['raw_estimate']}" if ev3 else "None")

    check("too few samples returns None (refuses to guess)",
          lane_count_evidence(mask, centre[:2], mpp) is None)

    empty = np.zeros((H, W), dtype=bool)
    check("empty mask returns None", lane_count_evidence(empty, centre, mpp) is None)

    obs = [{"id": "obs-001", "value": 3, "confidence": 0.82, "feature": "lane_count",
            "attached_to": {"road_id": "r1"}}]
    base = {"r1": {"lane_count": 2,
                   "lane_count_provenance": {"source": "inferred_default"}}}
    items = build_review_items(obs, base)
    check("disagreement becomes a REVIEW item",
          len(items) == 1 and items[0]["status"] == "REVIEW"
          and items[0]["baseline_value"] == 2 and items[0]["observed_value"] == 3)

    base_same = {"r1": {"lane_count": 3}}
    check("agreement is recorded as AGREEMENT, not silently dropped",
          build_review_items(obs, base_same)[0]["status"] == "AGREEMENT")

    low = [{**obs[0], "confidence": 0.1}]
    check("low-confidence evidence is filtered out",
          len(build_review_items(low, base)) == 0)


# ===========================================================================
TRIPINFO = """<?xml version="1.0"?>
<tripinfos>
 <tripinfo id="v0" depart="0.00" duration="40.00" routeLength="500" waitingTime="2.0" timeLoss="5.0"/>
 <tripinfo id="v1" depart="1.00" duration="44.00" routeLength="500" waitingTime="4.0" timeLoss="9.0"/>
 <tripinfo id="v2" depart="2.00" duration="42.00" routeLength="500" waitingTime="3.0" timeLoss="7.0"/>
</tripinfos>
"""

QUEUE = """<?xml version="1.0"?>
<queue-export>
 <data timestep="0.00"><lanes>
   <lane id="E1_0" queueing_time="0.00" queueing_length="10.00"/>
   <lane id="E1_1" queueing_time="0.00" queueing_length="20.00"/>
   <lane id="E2_0" queueing_time="0.00" queueing_length="99.00"/>
 </lanes></data>
 <data timestep="1.00"><lanes>
   <lane id="E1_0" queueing_time="0.00" queueing_length="30.00"/>
   <lane id="E1_1" queueing_time="0.00" queueing_length="40.00"/>
   <lane id="E2_0" queueing_time="0.00" queueing_length="1.00"/>
 </lanes></data>
</queue-export>
"""

SUMMARY = """<?xml version="1.0"?>
<summary>
 <step time="0.00" loaded="3" inserted="1" running="1" ended="0" teleports="0" collisions="0"/>
 <step time="60.00" loaded="3" inserted="3" running="0" ended="3" teleports="0" collisions="0"/>
</summary>
"""


def test_metrics():
    section("core/sim/metrics.py  -- SUMO output parsing")
    from core.sim import metrics as M

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "tripinfo.xml").write_text(TRIPINFO)
        (d / "queue.xml").write_text(QUEUE)
        (d / "summary.xml").write_text(SUMMARY)

        ti = M.parse_tripinfo(d / "tripinfo.xml")
        check("tripinfo: mean travel time", ti["avg_travel_time_s"] == 42.0,
              str(ti["avg_travel_time_s"]))
        check("tripinfo: completed vehicles", ti["completed_vehicles"] == 3)
        check("tripinfo: mean time loss", ti["avg_time_loss_s"] == 7.0)

        q = M.parse_queue(d / "queue.xml")
        # per timestep max = 99, 40  -> mean 69.5, peak 99
        check("queue: mean of per-step maxima", q["mean_queue_length_m"] == 69.5,
              str(q["mean_queue_length_m"]))
        check("queue: absolute peak", q["max_queue_length_m"] == 99.0)

        qf = M.parse_queue(d / "queue.xml", edge_filter="E1")
        # E1 only: max 20, 40 -> mean 30
        check("queue: edge filter isolates one edge", qf["mean_queue_length_m"] == 30.0,
              str(qf["mean_queue_length_m"]))

        s = M.parse_summary(d / "summary.xml")
        check("summary: reads the final step", s["ended"] == 3.0 and s["loaded"] == 3.0)

        r = M.collect_run(d)
        check("collect_run merges all three outputs",
              r["avg_travel_time_s"] == 42.0 and r["mean_queue_length_m"] == 69.5)

    a = M.aggregate([
        {"avg_travel_time_s": 40.0, "mean_queue_length_m": 10.0, "completed_vehicles": 100},
        {"avg_travel_time_s": 44.0, "mean_queue_length_m": 14.0, "completed_vehicles": 102},
    ])
    check("aggregate: mean across seeds", a["avg_travel_time_s"] == 42.0)
    check("aggregate: reports spread", a["avg_travel_time_s_sd"] == 2.0)
    check("aggregate: records seed count", a["n_seeds"] == 2)

    base = {"avg_travel_time_s": 42.0, "avg_travel_time_s_sd": 1.0,
            "mean_queue_length_m": 18.0, "completed_vehicles": 102, "n_seeds": 5}
    clos = {"avg_travel_time_s": 56.0, "avg_travel_time_s_sd": 1.5,
            "mean_queue_length_m": 47.0, "completed_vehicles": 97, "n_seeds": 5}
    c = M.compare(base, clos)
    check("compare: computes percentage delta",
          abs(c["rows"][0]["delta_pct"] - 33.3) < 0.1, f"{c['rows'][0]['delta_pct']}%")
    check("compare: large change flagged significant", c["significant"] is True)

    noise = M.compare(base, {**base, "avg_travel_time_s": 42.5})
    check("compare: change within seed noise flagged NOT significant",
          noise["significant"] is False)
    check("format_table renders", "BASELINE" in M.format_table(c))


# ===========================================================================
EDG = """<?xml version="1.0" encoding="UTF-8"?>
<edges>
  <edge id="E1" from="n1" to="n2" priority="10" type="highway.trunk" numLanes="2" speed="16.67"/>
  <edge id="E2" from="n2" to="n3" priority="10" type="highway.trunk" numLanes="3" speed="16.67"/>
</edges>
"""


def test_edits():
    section("core/model/edits.py  -- the edit -> recompile funnel")
    from core.model.edits import (Edit, apply_edits, lane_ids_for_edge,
                                  read_edges, replay, write_validation_report)

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        src = d / "plain.edg.xml"
        src.write_text(EDG)

        edges = read_edges(src)
        check("reads edges", set(edges) == {"E1", "E2"})
        check("reads numLanes", edges["E1"]["numLanes"] == "2")

        check("lane ids follow SUMO convention",
              lane_ids_for_edge(src, "E1") == ["E1_0", "E1_1"])

        e = Edit(edge_id="E1", attribute="numLanes", old_value=None, new_value="3",
                 source="accepted_vision", observation_id="obs-001", confidence=0.82)
        out = d / "edited.edg.xml"
        apply_edits(src, [e], out)

        after = read_edges(out)
        check("edit applied", after["E1"]["numLanes"] == "3")
        check("old value captured for the audit trail", e.old_value == "2")
        check("untouched edge unchanged", after["E2"]["numLanes"] == "3")
        check("other attributes preserved", after["E1"]["speed"] == "16.67"
              and after["E1"]["from"] == "n1")

        missing = Edit(edge_id="NOPE", attribute="numLanes", old_value=None, new_value="9")
        apply_edits(src, [missing], d / "m.edg.xml")
        check("unknown edge does not crash the pipeline",
              read_edges(d / "m.edg.xml")["E1"]["numLanes"] == "2")

        rep = write_validation_report([e], [{"id": "obs-001", "status": "REVIEW"}],
                                      d / "validation_report.json")
        check("validation report written", rep.exists())

        # the replayability claim, tested rather than asserted
        rp = replay(src, rep, d / "replayed.edg.xml")
        check("REPLAY: baseline + report reproduces the final model",
              read_edges(rp)["E1"]["numLanes"] == "3")

        rej = Edit(edge_id="E2", attribute="numLanes", old_value=None, new_value="9",
                   user_action="reject")
        rep2 = write_validation_report([e, rej], [], d / "vr2.json")
        rp2 = replay(src, rep2, d / "replay2.edg.xml")
        check("REPLAY: rejected decisions are not applied",
              read_edges(rp2)["E2"]["numLanes"] == "3")


# ===========================================================================
NET = """<?xml version="1.0" encoding="UTF-8"?>
<net>
  <edge id=":n2_0" function="internal">
    <lane id=":n2_0_0" index="0" speed="13.89" length="5.00"/>
  </edge>
  <edge id="E0" from="n0" to="n1" priority="10">
    <lane id="E0_0" index="0" speed="16.67" length="200.00"/>
    <lane id="E0_1" index="1" speed="16.67" length="200.00"/>
  </edge>
  <edge id="E1" from="n1" to="n2" priority="10">
    <lane id="E1_0" index="0" speed="16.67" length="340.50"/>
    <lane id="E1_1" index="1" speed="16.67" length="340.50"/>
    <lane id="E1_2" index="2" speed="16.67" length="340.50"/>
  </edge>
  <edge id="E9" from="n8" to="n9" priority="1">
    <lane id="E9_0" index="0" speed="8.33" length="50.00"/>
  </edge>
  <connection from="E0" to="E1" fromLane="0" toLane="0"/>
  <connection from="E0" to="E1" fromLane="1" toLane="1"/>
  <connection from=":n2_0" to="E1" fromLane="0" toLane="0"/>
</net>
"""


def test_scenario():
    section("core/sim/scenario.py  -- closure without touching the network")
    from lxml import etree

    from core.sim.scenario import (build_lane_closure, pick_closure_candidate,
                                   read_net_edges, upstream_edges)

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        net = d / "network.net.xml"
        net.write_text(NET)

        edges = read_net_edges(net)
        check("internal junction edges are skipped", ":n2_0" not in edges)
        check("real edges found", set(edges) == {"E0", "E1", "E9"})
        check("lane count read", edges["E1"]["num_lanes"] == 3)
        check("edge length read", edges["E1"]["length_m"] == 340.5)

        check("upstream edges resolved", upstream_edges(net, "E1") == ["E0"])

        cand = pick_closure_candidate(net)
        check("candidate picker prefers the widest/longest edge",
              cand["edge_id"] == "E1", str(cand))

        add = d / "closure.add.xml"
        desc = build_lane_closure(net, add, edge_id="E1", lane_index=2,
                                  begin=300, end=3600)
        check("closure file written", add.exists())
        check("reports the ACTUAL closed length, not a fabricated one",
              desc["actual_closed_length_m"] == 340.5)

        root = etree.parse(str(add)).getroot()
        rr = root.find("rerouter")
        clr = root.find(".//closingLaneReroute")
        check("rerouter element present", rr is not None)
        check("rerouter also triggers on upstream edges",
              "E0" in rr.get("edges") and "E1" in rr.get("edges"), rr.get("edges"))
        check("closingLaneReroute targets the right lane", clr.get("id") == "E1_2")
        check("closed lane is restricted to authority",
              clr.get("allow") == "authority")
        iv = root.find(".//interval")
        check("interval timing written", iv.get("begin") == "300"
              and iv.get("end") == "3600")

        for bad, why in [
            (dict(edge_id="E9", lane_index=0), "single-lane edge refused"),
            (dict(edge_id="E1", lane_index=7), "out-of-range lane refused"),
            (dict(edge_id="NOPE", lane_index=0), "unknown edge refused"),
        ]:
            try:
                build_lane_closure(net, d / "x.xml", **bad)
                check(why, False, "no exception raised")
            except ValueError:
                check(why, True)


# ===========================================================================
GEONET = """<?xml version="1.0" encoding="UTF-8"?>
<net>
 <location netOffset="-395795.40,-1417357.74"
           convBoundary="0.00,0.00,968.96,814.85"
           origBoundary="80.0398,12.8194,80.0487,12.8268"
           projParameter="+proj=utm +zone=44 +ellps=WGS84 +datum=WGS84 +units=m +no_defs"/>
 <edge id=":n2_0" function="internal">
   <lane id=":n2_0_0" index="0" length="5.00" speed="13.89" shape="10,10 12,12"/>
 </edge>
 <edge id="E1" from="n1" to="n2" priority="10">
   <lane id="E1_0" index="0" length="340.50" speed="16.67" shape="0.00,0.00 968.96,814.85"/>
   <lane id="E1_1" index="1" length="340.50" speed="16.67" shape="0.00,3.20 968.96,818.05"/>
   <lane id="E1_2" index="2" length="340.50" speed="16.67" shape="0.00,6.40 968.96,821.25"/>
 </edge>
 <junction id="n1" type="priority" x="0.00" y="0.00"/>
 <junction id="n2" type="traffic_light" x="968.96" y="814.85"/>
 <junction id=":n2_0" type="internal" x="484.48" y="407.43"/>
</net>
"""


def test_geometry():
    section("core/model/geometry.py  -- network XY <-> WGS84")
    import warnings

    from core.model.geometry import (NetGeo, densify_lonlat, edge_centerline_lonlat,
                                     edges_to_geojson, junctions_to_geojson,
                                     read_edge_shapes)

    with tempfile.TemporaryDirectory() as td:
        net = Path(td) / "n.net.xml"
        net.write_text(GEONET)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            geo = NetGeo(net)
        print(f"  ..   mode: {'exact (pyproj)' if geo.exact else 'boundary interpolation'}")

        lon, lat = geo.xy_to_lonlat(0.0, 0.0)
        check("SW corner maps to origBoundary SW",
              abs(lon - 80.0398) < 2e-4 and abs(lat - 12.8194) < 2e-4,
              f"{lon:.5f},{lat:.5f}")
        lon, lat = geo.xy_to_lonlat(968.96, 814.85)
        check("NE corner maps to origBoundary NE",
              abs(lon - 80.0487) < 2e-4 and abs(lat - 12.8268) < 2e-4,
              f"{lon:.5f},{lat:.5f}")

        worst = 0.0
        for x, y in [(0, 0), (242, 204), (484, 407), (968, 814), (137, 613)]:
            lo, la = geo.xy_to_lonlat(x, y)
            bx, by = geo.lonlat_to_xy(lo, la)
            worst = max(worst, math.hypot(bx - x, by - y))
        check("xy -> lonlat -> xy round-trip < 1 cm", worst < 0.01, f"worst {worst:.2e} m")

        sh = read_edge_shapes(net)
        check("internal edges excluded from shapes", ":n2_0" not in sh)
        check("median lane used as the centerline (lies ON the road)",
              sh["E1"][0][1] == 3.20, f"y0={sh['E1'][0][1]}")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            line = edge_centerline_lonlat(net, "E1", geo=geo)
            dense = densify_lonlat(line, every_m=10.0)
            gj = edges_to_geojson(net)
            jj = junctions_to_geojson(net)

        check("centerline returned in lon/lat",
              len(line) == 2 and 80.0 < line[0][0] < 80.1, str(line[0]))
        # netconvert collapses straight runs to 2 points; SAM needs coverage
        check("densify produces prompts along the whole road", len(dense) > 100,
              f"{len(dense)} pts from {len(line)}")
        lo, la = dense[len(dense) // 2]
        check("densified midpoint stays inside the AOI",
              80.039 < lo < 80.049 and 12.819 < la < 12.827, f"{lo:.5f},{la:.5f}")
        check("max_points subsamples",
              len(edge_centerline_lonlat(net, "E1", geo=geo, max_points=2)) == 2)

        check("edges GeoJSON is a LineString collection",
              len(gj["features"]) == 1
              and gj["features"][0]["geometry"]["type"] == "LineString")
        check("GeoJSON declares its georeferencing mode", "_georeferencing" in gj,
              gj["_georeferencing"])

        ids = {f["properties"]["junction_id"] for f in jj["features"]}
        check("junctions: internal and dead-end excluded", ids == {"n1", "n2"}, str(ids))
        check("signalised junction flagged",
              any(f["properties"]["has_signal"] for f in jj["features"]))

        try:
            edge_centerline_lonlat(net, "NOPE", geo=geo)
            check("unknown edge raises", False, "no exception")
        except KeyError:
            check("unknown edge raises", True)


def test_export():
    section("core/export/package.py  -- the deliverable")
    from core.export.package import export_project, write_readme

    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "proj"
        (d / "sumo" / "results" / "baseline" / "seed_42").mkdir(parents=True)
        (d / "roadtwin.json").write_text("{}")
        (d / "sumo" / "network.net.xml").write_text("<net/>")
        (d / "sumo" / "results" / "baseline" / "seed_42" / "queue.xml").write_text("<q/>")
        (d / "__pycache__").mkdir()
        (d / "__pycache__" / "junk.pyc").write_text("x")

        write_readme(d, location={"name": "Test Rd", "lat": 12.8231, "lon": 80.0442,
                                  "aoi_radius_m": 500}, results_table="TABLE")
        check("README generated from the real run", (d / "README.md").exists())
        check("README carries the real coordinates",
              "12.823100" in (d / "README.md").read_text())

        z = export_project(d, Path(td) / "out.zip")
        import zipfile
        names = zipfile.ZipFile(z).namelist()
        check("zip contains the model", "roadtwin.json" in names)
        check("bulky per-seed queue dumps excluded",
              not any("seed_42/queue.xml" in n for n in names))
        check("__pycache__ excluded", not any("__pycache__" in n for n in names))


# ===========================================================================
def main() -> int:
    print("=" * 72)
    print("RoadTwin self-test  (no SUMO, no network required)")
    print("=" * 72)
    test_tiles()
    test_evidence()
    test_metrics()
    test_edits()
    test_scenario()
    test_geometry()
    test_export()
    print("\n" + "=" * 72)
    print(f"{PASS} passed, {FAIL} failed")
    print("=" * 72)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
