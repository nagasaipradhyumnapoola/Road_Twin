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

    # Physically implausible width must be refused, not reported as many lanes.
    # This is the 51.53 m / 15-lane benchmark false positive, generalised: a mask
    # wider than lane_width_m * max_lanes is a mask that bled off the carriageway.
    wide, wide_c = band(60.0)          # 60 m -> ~17 lanes on one edge: absurd
    check("implausible width (> max_lanes) refuses (insufficient)",
          lane_count_evidence(wide, wide_c, mpp) is None,
          "60 m band should be rejected as implausible")

    # Poor road overlap -- the mask supports only part of the centerline. A
    # consistent width over a mask that only grazed the road must NOT pass.
    partial = np.zeros((H, W), dtype=bool)
    _half = int(round((10.5 / mpp) / 2))
    partial[H // 2 - _half: H // 2 + _half, :250] = True
    check("poor road overlap refuses (insufficient)",
          lane_count_evidence(partial, centre, mpp) is None,
          "mask covering <50% of centerline should be rejected")

    # A good result carries overlap_ratio, ~1.0 for a fully-supported mask.
    good_ev = lane_count_evidence(*band(10.5), mpp)
    check("evidence reports road overlap ratio",
          good_ev is not None and good_ev.get("overlap_ratio", 0) >= 0.9,
          f"overlap={good_ev.get('overlap_ratio') if good_ev else None}")

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

    # A run where no vehicle completed has avg_travel_time_s = None. The
    # `tt_sd == 0` shortcut used to call that significant, so an empty
    # simulation exited 0 and read as a successful experiment.
    empty = M.aggregate([{"avg_travel_time_s": None, "mean_queue_length_m": None,
                          "completed_vehicles": 0}])
    check("compare: empty simulation is NEVER significant",
          M.compare(empty, empty)["significant"] is False)
    check("compare: one-sided empty result is NEVER significant",
          M.compare(base, empty)["significant"] is False
          and M.compare(empty, base)["significant"] is False)
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

        # road closure — whole edge, closingReroute (P11)
        from core.sim.scenario import build_road_closure
        radd = d / "road.add.xml"
        rdesc = build_road_closure(net, radd, edge_id="E1", begin=300, end=3600)
        check("road closure file written", radd.exists())
        check("road closure reports the actual edge length",
              rdesc["actual_closed_length_m"] == 340.5)
        rroot = etree.parse(str(radd)).getroot()
        clr = rroot.find(".//closingReroute")
        check("road closure emits closingReroute for the whole edge",
              clr is not None and clr.get("id") == "E1")
        check("road closure rerouter triggers on upstream too",
              "E0" in rroot.find("rerouter").get("edges"))
        try:
            build_road_closure(net, d / "y.xml", edge_id="NOPE")
            check("road closure: unknown edge refused", False, "no exception")
        except ValueError:
            check("road closure: unknown edge refused", True)


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


def test_paired():
    section("core/sim/metrics.py  -- paired significance + breakdown regime")
    from core.sim import metrics as M

    def arm(per_seed):
        """Build an aggregate the way run_scenario would, from per-seed runs."""
        seeds = sorted(per_seed)
        runs = [per_seed[s] for s in seeds]
        return M.aggregate(runs, seeds=seeds)

    def run(tt, speed=12.0, tel=1.0, running=20.0):
        return {"avg_travel_time_s": tt, "mean_queue_length_m": 10.0,
                "completed_vehicles": 1000, "teleports": tel,
                "still_running_at_end": running, "mean_speed_end": speed}

    # aggregate() must keep the per-seed values, or pairing is impossible
    a = arm({42: run(80.0), 43: run(90.0)})
    check("aggregate keeps per-seed values", set(a["per_seed"]) == {42, 43})
    check("aggregate still reports the mean", a["avg_travel_time_s"] == 85.0)

    # A small, CONSISTENT shift is significant when paired even though the
    # arm-level spread dwarfs it -- this is the case the old unpaired rule got
    # wrong. Baseline seeds range 80-120 (sd ~14); every seed gains exactly 5s.
    base = arm({s: run(t) for s, t in zip(range(42, 52), range(80, 130, 5))})
    clos = arm({s: run(t + 5) for s, t in zip(range(42, 52), range(80, 130, 5))})
    pe = M.paired_effect(base, clos)
    check("paired: consistent shift detected despite large arm spread",
          pe is not None and pe["significant"] and pe["mean_delta"] == 5.0,
          f"mean={pe['mean_delta']} CI={pe['ci95']}" if pe else "None")
    check("paired: unpaired 2-sigma rule would have MISSED it",
          abs(clos["avg_travel_time_s"] - base["avg_travel_time_s"])
          <= 2 * max(base["avg_travel_time_s_sd"], clos["avg_travel_time_s_sd"]))
    check("paired: reports direction and seed tally",
          pe["direction"] == "increase" and pe["n_positive"] == 10
          and pe["n_negative"] == 0)
    check("paired: CI excludes zero when significant",
          pe["ci95"][0] > 0 and pe["ci95"][1] > 0, str(pe["ci95"]))
    check("compare() uses the paired test when per-seed data exists",
          M.compare(base, clos)["method"].startswith("paired"))

    # Pure noise must NOT pass. Same seeds, deltas alternating +/-, mean ~0.
    noisy_b = arm({s: run(80.0) for s in range(42, 52)})
    noisy_c = arm({s: run(80.0 + (6 if s % 2 else -6)) for s in range(42, 52)})
    pn = M.paired_effect(noisy_b, noisy_c)
    check("paired: alternating noise is NOT significant",
          pn is not None and not pn["significant"], str(pn["ci95"]) if pn else "None")

    # A significant SPEED-UP must be reported as such, not silently passed.
    fast = arm({s: run(70.0) for s in range(42, 52)})
    pf = M.paired_effect(noisy_b, fast)
    check("paired: significant speed-up flagged as a decrease",
          pf["significant"] and pf["direction"] == "decrease")
    check("compare() verdict warns on a significant speed-up",
          "FASTER" in M.compare(noisy_b, fast)["verdict"].upper()
          or "DECREASED" in M.compare(noisy_b, fast)["verdict"].upper())

    # Falls back cleanly when pairing is impossible.
    check("paired: returns None without per-seed data",
          M.paired_effect({"avg_travel_time_s": 80.0},
                          {"avg_travel_time_s": 90.0}) is None)
    check("paired: returns None with a single shared seed",
          M.paired_effect(arm({42: run(80.0)}), arm({42: run(90.0)})) is None)
    legacy = M.compare({"avg_travel_time_s": 42.0, "avg_travel_time_s_sd": 1.0},
                       {"avg_travel_time_s": 56.0, "avg_travel_time_s_sd": 1.5})
    check("compare() falls back to the unpaired rule for legacy aggregates",
          legacy["significant"] is True and "fallback" in legacy["method"])

    # ---- one-seed safety -------------------------------------------------
    # `--seeds 1` used to reach the unpaired fallback, where a lone run has
    # sd == 0 and the zero-variance shortcut returned significant = True. That
    # let ANY one-seed result exit 0, including a closure that made the network
    # faster. SETUP.md recommended exactly that command.
    one_b = arm({42: run(85.0)})
    one_faster = arm({42: run(70.0)})
    one_slower = arm({42: run(120.0)})

    r1 = M.compare(one_b, one_faster)
    check("one seed: a significant-looking SPEED-UP cannot pass",
          r1["significant"] is False, r1["method"])
    check("one seed: exit gate would fail (significant is False)",
          r1["significant"] is False)
    check("one seed: method names the reason",
          "insufficient seeds" in r1["method"], r1["method"])
    check("one seed: verdict says smoke test, not experiment",
          "SMOKE TEST" in r1["verdict"])
    check("one seed: a large slowdown also cannot pass",
          M.compare(one_b, one_slower)["significant"] is False)

    # Two seeds is the smallest set that can be paired at all, and the paired
    # method must take over again the moment it is available.
    two = M.compare(arm({42: run(85.0), 43: run(85.0)}),
                    arm({42: run(90.0), 43: run(90.0)}))
    check("two seeds: paired method takes over",
          two["method"].startswith("paired") and two["significant"] is True,
          two["method"])
    check("20 seeds: paired method still used (normal path unchanged)",
          M.compare(arm({s: run(85.0) for s in range(42, 62)}),
                    arm({s: run(90.0) for s in range(42, 62)})
                    )["method"].startswith("paired"))

    # The guard keys on n_seeds, which hand-built aggregates do not carry, so
    # legacy callers keep the old fallback rather than being blocked.
    legacy_ok = M.compare({"avg_travel_time_s": 42.0, "avg_travel_time_s_sd": 1.0},
                          {"avg_travel_time_s": 56.0, "avg_travel_time_s_sd": 1.5})
    check("legacy aggregates without n_seeds are not blocked by the guard",
          legacy_ok["significant"] is True and "fallback" in legacy_ok["method"])

    # Breakdown regime: counted separately, criterion is relative to the
    # seed's OWN baseline so it transfers across networks.
    bd_b = arm({s: run(80.0, speed=12.0) for s in range(42, 46)})
    bd_c = arm({42: run(200.0, speed=4.0, tel=50.0, running=60.0),
                43: run(85.0, speed=11.0),
                44: run(85.0, speed=11.0),
                45: run(85.0, speed=11.0)})
    bd = M.classify_breakdown(bd_b, bd_c)
    check("breakdown: counts only the collapsed seed",
          bd["n_breakdown"] == 1 and bd["breakdown_seeds"] == [42])
    check("breakdown: reports a probability", bd["breakdown_probability"] == 0.25)
    check("breakdown: conditional severity describes only breakdown runs",
          bd["conditional_severity"]["closure_travel_time_s"] == 200.0)
    check("breakdown: normal regime reported separately",
          bd["normal_regime"]["n"] == 3)
    check("breakdown: unfinished vehicles surfaced (they are censored trips)",
          bd["conditional_severity"]["closure_still_running_at_end"] == 60.0)
    check("breakdown: significance is independent of breakdown count",
          M.compare(bd_b, bd_c)["breakdown"]["n_breakdown"] == 1)


def test_phase0_gate():
    section("scripts/run_benchmark.py  -- the Phase 0 --skip-sim gate")
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_rb", ROOT / "scripts" / "run_benchmark.py")
    rb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rb)

    # Phase 0's claim is "--skip-sim produced a VALID .xodr". run_benchmark used
    # to compute the round-trip result, print it, and return 0 regardless -- so
    # a broken OpenDRIVE export still read as a green gate. Lock that shut.
    check("round-trip PASS -> exit 0", rb.skip_sim_exit_code(True) == 0)
    check("round-trip FAIL -> non-zero exit",
          rb.skip_sim_exit_code(False) != 0,
          f"got {rb.skip_sim_exit_code(False)}")
    check("a failed round-trip can never be reported as success",
          rb.skip_sim_exit_code(False) != rb.skip_sim_exit_code(True))

    # The AOI clip is a netconvert CLI flag, so it cannot be exercised without
    # SUMO. What IS pure logic, and easy to get silently backwards, is the
    # coordinate ORDER: bbox is (south, west, north, east) but netconvert wants
    # lon-min,lat-min,lon-max,lat-max. Swapping them clips an empty region.
    from core.acquire.overpass import bbox_from_point
    south, west, north, east = bbox_from_point(12.8261, 80.0413, 500)
    check("AOI bbox brackets the requested centre",
          south < 12.8261 < north and west < 80.0413 < east,
          f"({south:.5f},{west:.5f},{north:.5f},{east:.5f})")
    check("geo-boundary string is lon,lat,lon,lat -- not lat,lon",
          f"{west},{south},{east},{north}".split(",")[0].startswith("80."),
          f"{west:.5f},{south:.5f},{east:.5f},{north:.5f}")


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
BENCH_NET = """<?xml version="1.0" encoding="UTF-8"?>
<net>
  <edge id=":j2_0" function="internal">
    <lane id=":j2_0_0" index="0" speed="13.89" length="5.00"/>
  </edge>
  <edge id="A" from="j1" to="j2" priority="10">
    <lane id="A_0" index="0" speed="16.67" length="100.00"/>
    <lane id="A_1" index="1" speed="16.67" length="100.00"/>
  </edge>
  <edge id="B" from="j2" to="j3" priority="10">
    <lane id="B_0" index="0" speed="16.67" length="200.00"/>
  </edge>
  <junction id="j1" type="priority" x="0" y="0"/>
  <junction id="j2" type="traffic_light" x="100" y="0"/>
  <junction id="j3" type="dead_end" x="300" y="0"/>
  <junction id=":j2_0" type="internal" x="100" y="0"/>
</net>
"""


def test_benchmark():
    section("core/benchmark.py  -- P10 acceleration record (no fabricated claim)")
    import json as _json

    from core import benchmark as BM

    with tempfile.TemporaryDirectory() as td:
        proj = Path(td)
        net = proj / "network.net.xml"
        net.write_text(BENCH_NET)

        ns = BM.network_size_from_net(net)
        check("network size: drivable edges counted as roads", ns["roads"] == 2, str(ns))
        check("network size: lanes summed across edges", ns["lanes"] == 3, str(ns))
        # j1 (priority) + j2 (traffic_light) are real; :j2_0 (internal) and
        # j3 (dead_end) are excluded -- same rule the canonical model uses.
        check("network size: internal + dead-end junctions excluded",
              ns["junctions"] == 2, str(ns))

        # human effort is computed live from project files, never fabricated
        ha0 = BM.human_actions_from_project(proj)
        check("human actions: zero when no files present",
              ha0 == {"location_confirmation": 0, "evidence_reviews": 0, "manual_edits": 0},
              str(ha0))

        (proj / "location.json").write_text(_json.dumps({"confirmed": True, "name": "X"}))
        (proj / "validation_report.json").write_text(_json.dumps({"decisions": [
            {"user_action": "accept"}, {"user_action": "edit"},
        ]}))
        ha = BM.human_actions_from_project(proj)
        check("human actions: confirmed location counts once",
              ha["location_confirmation"] == 1)
        check("human actions: reviews = number of decisions", ha["evidence_reviews"] == 2)
        check("human actions: manual edits = decisions with action 'edit'",
              ha["manual_edits"] == 1, str(ha))

        # load returns None until a record with timings exists
        check("load: None before any run recorded",
              BM.load(proj) is None)

        BM.record_run(proj, timings={
            "acquisition_s": 12.4, "model_generation_s": 2.8,
            "compilation_s": 4.1, "export_s": 1.7, "simulation_s": 30.0,
        }, net_file=net, seeds=5)

        rec = BM.load(proj)
        check("load: returns a record after run", rec is not None)
        # total is the sum of the MODELING stages only -- simulation is excluded
        check("total_s = sum of modeling stages (sim excluded)",
              rec["timings"]["total_s"] == 21.0, str(rec["timings"]["total_s"]))
        check("simulation reported separately, not in total",
              rec["timings"]["simulation_s"] == 30.0)
        check("network size embedded in record", rec["network"]["roads"] == 2)
        check("human actions merged live into record",
              rec["human_actions"]["manual_edits"] == 1)
        check("location merged live into record", rec["location"]["name"] == "X")

        # the "no unsupported speed claim" rule, enforced not asserted: a
        # forbidden comparative field must never survive to disk
        raw = _json.loads((proj / "benchmark.json").read_text())
        forbidden = {"manual_baseline", "speedup", "faster", "times_faster"}
        check("record on disk carries no fabricated speed-claim field",
              not (forbidden & set(raw)) and not (forbidden & set(raw.get("timings", {}))),
              str(sorted(raw)))

        # and the writer strips one even if a caller sneaks it in
        raw["speedup"] = "10x"
        (proj / "benchmark.json").write_text(_json.dumps(raw))
        BM.update_stage(proj, "export_s", 1.9)
        after = _json.loads((proj / "benchmark.json").read_text())
        check("writer strips a forbidden speed-claim key on next write",
              "speedup" not in after, str(sorted(after)))


# ===========================================================================
def test_scenario_engine():
    section("core/scenario/*  -- P11 what-if engine (definitions, no SUMO)")
    from core.scenario import registry as R
    from core.scenario.builder import build_execution
    from core.scenario.models import SCENARIO_TYPES, TYPE_SPECS, Scenario
    from core.scenario.validator import validate

    # models round-trip + catalogue completeness
    s = Scenario(scenario_id="scn-001", name="Test", type="lane_closure",
                 parameters={"edge_id": "E1", "lane_index": 2}, seeds=[1, 2, 3])
    check("scenario round-trips through dict",
          Scenario.from_dict(s.to_dict()).parameters == {"edge_id": "E1", "lane_index": 2})
    check("every scenario type has a spec",
          all(t in TYPE_SPECS for t in SCENARIO_TYPES))

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        net = d / "network.net.xml"
        net.write_text(NET)   # E0 (2 lanes), E1 (3 lanes), E9 (1 lane)

        # ---- validator -------------------------------------------------
        def valid(sc):
            try:
                validate(sc, net); return True
            except ValueError:
                return False

        check("validator accepts a baseline",
              valid(Scenario("b", "B", "baseline", seeds=[1])))
        check("validator accepts a legal lane closure",
              valid(Scenario("s", "S", "lane_closure",
                             parameters={"edge_id": "E1", "lane_index": 2}, seeds=[1])))
        check("validator rejects lane closure on a single-lane edge",
              not valid(Scenario("s", "S", "lane_closure",
                                 parameters={"edge_id": "E9", "lane_index": 0}, seeds=[1])))
        check("validator rejects an out-of-range lane",
              not valid(Scenario("s", "S", "lane_closure",
                                 parameters={"edge_id": "E1", "lane_index": 9}, seeds=[1])))
        check("validator rejects an unknown edge",
              not valid(Scenario("s", "S", "road_closure",
                                 parameters={"edge_id": "NOPE"}, seeds=[1])))
        check("validator accepts a legal road closure",
              valid(Scenario("s", "S", "road_closure",
                             parameters={"edge_id": "E1"}, seeds=[1])))
        check("validator rejects demand multiplier <= 1",
              not valid(Scenario("s", "S", "traffic_increase",
                                 parameters={"demand_multiplier": 1.0}, seeds=[1])))
        check("validator accepts demand multiplier > 1",
              valid(Scenario("s", "S", "traffic_increase",
                             parameters={"demand_multiplier": 1.2}, seeds=[1])))
        check("validator rejects empty seeds",
              not valid(Scenario("s", "S", "baseline", seeds=[])))

        # ---- builder (closure additionals are pure XML, no SUMO) -------
        wk = d / "work"
        base_routes = d / "routes.rou.xml"   # not read for these types
        base_spec = build_execution(Scenario("b", "B", "baseline", seeds=[1]),
                                    net_file=net, base_routes=base_routes, work_dir=wk)
        check("baseline execution modifies nothing",
              base_spec["scenario_additional"] is None
              and base_spec["edge_filter"] is None)

        lc = build_execution(
            Scenario("s", "S", "lane_closure",
                     parameters={"edge_id": "E1", "lane_index": 2}, seeds=[1]),
            net_file=net, base_routes=base_routes, work_dir=wk)
        check("lane-closure execution writes an additional + sets the filter",
              Path(lc["scenario_additional"]).exists() and lc["edge_filter"] == "E1")

        rc = build_execution(
            Scenario("s", "S", "road_closure",
                     parameters={"edge_id": "E1"}, seeds=[1]),
            net_file=net, base_routes=base_routes, work_dir=wk)
        check("road-closure execution writes an additional + sets the filter",
              Path(rc["scenario_additional"]).exists() and rc["edge_filter"] == "E1")

        # ---- registry --------------------------------------------------
        proj = d / "proj"
        R.ensure_baseline(proj, [1, 2, 3])
        check("registry ensures a baseline scenario", R.load(proj, "scn-baseline") is not None)
        first = R.next_id(proj)
        check("next_id ignores the named baseline", first == "scn-001", first)
        R.save(proj, Scenario(first, "One", "road_closure",
                              parameters={"edge_id": "E1"}, seeds=[1]))
        check("next_id increments past saved scenarios",
              R.next_id(proj) == "scn-002")
        ids = [s.scenario_id for s in R.list_scenarios(proj)]
        check("list puts baseline first", ids[0] == "scn-baseline", str(ids))
        R.save_result(proj, first, {"scenario_id": first, "type": "road_closure"})
        check("result round-trips", R.load_result(proj, first)["type"] == "road_closure")
        check("a result file is not listed as a scenario definition",
              "scn-001.result" not in ids)


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
    test_paired()
    test_phase0_gate()
    test_export()
    test_benchmark()
    test_scenario_engine()
    print("\n" + "=" * 72)
    print(f"{PASS} passed, {FAIL} failed")
    print("=" * 72)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
