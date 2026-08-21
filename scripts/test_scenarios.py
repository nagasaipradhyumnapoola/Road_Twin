"""End-to-end P11 what-if scenario test — REAL SUMO.

selftest.py deliberately runs no SUMO, so the scenario *engine* (definitions,
validation, builder XML) is covered there but the actual baseline-vs-scenario
simulation is not. This script closes that gap: it drives the real /scenario/*
endpoints (the same path the UI uses) through create -> validate -> run ->
persist -> rerun -> verify-linkage for the baseline and all three V1 scenarios,
and proves the canonical network is byte-for-byte unchanged with a SHA-256 hash.

Requires SUMO (like run_benchmark.py). If SUMO is not found it SKIPS and exits 0
so a machine without SUMO does not report a false failure. Run it on a SUMO
machine for real evidence.

    python scripts/test_scenarios.py
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# UTF-8 stdout: SUMO change-summaries contain non-ASCII (e.g. the multiply sign),
# which crashes on a cp1252 console otherwise.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

EDGE = "568057022#0"   # a multi-lane edge in the benchmark network
PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}" + (f"  ({detail})" if detail else ""))


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def sumo_available() -> bool:
    try:
        from core.build.netconvert import sumo_bin
        binary = sumo_bin("sumo")
        out = subprocess.run([binary, "--version"], capture_output=True, text=True)
        return out.returncode == 0
    except Exception:
        return False


REQUIRED_FIELDS = {
    "scenario_id", "base_twin_id", "name", "type", "parameters", "demand", "seeds",
}


def main() -> int:
    if not sumo_available():
        print("SKIP: SUMO not found (set SUMO_HOME). Nothing simulated.")
        return 0

    src = ROOT / "projects" / "benchmark" / "sumo"
    if not (src / "network.net.xml").exists() or not (src / "routes.rou.xml").exists():
        print("SKIP: projects/benchmark network/routes missing; run run_benchmark first.")
        return 0

    data_root = Path(tempfile.mkdtemp(prefix="rt_scn_"))
    try:
        active = data_root / "projects" / "active"
        (active / "sumo").mkdir(parents=True)
        shutil.copy(src / "network.net.xml", active / "sumo" / "network.net.xml")
        shutil.copy(src / "routes.rou.xml", active / "sumo" / "routes.rou.xml")
        json.dump(
            {"name": "test", "lat": 12.8261, "lon": 80.0413, "aoi_radius_m": 500,
             "crs": "EPSG:4326", "confirmed": True},
            open(active / "location.json", "w"),
        )
        os.environ["ROADTWIN_DATA_DIR"] = str(data_root)

        net = active / "sumo" / "network.net.xml"
        scen_dir = active / "scenarios"
        net_sha_before = sha(net)

        # Import AFTER ROADTWIN_DATA_DIR is set so the project root resolves here.
        from fastapi.testclient import TestClient
        import core.main as M

        client = TestClient(M.app, raise_server_exceptions=False)

        # ---- type catalogue -------------------------------------------------
        types = [t["type"] for t in client.get("/scenario/types").json()["types"]]
        check("all three V1 types + baseline are offered",
              set(types) == {"baseline", "lane_closure", "road_closure", "traffic_increase"},
              str(types))

        def def_has_fields(sid: str) -> bool:
            d = json.loads((scen_dir / f"{sid}.json").read_text(encoding="utf-8"))
            return REQUIRED_FIELDS.issubset(d.keys())

        def create(name: str, typ: str, params: dict) -> str:
            r = client.post("/scenario/create",
                            json={"name": name, "type": typ, "parameters": params})
            check(f"create {typ}", r.status_code == 200, f"{r.status_code} {r.text[:120]}")
            sid = r.json()["scenario"]["scenario_id"]
            check(f"{typ} definition persisted with all required fields",
                  (scen_dir / f"{sid}.json").exists() and def_has_fields(sid))
            return sid

        def run(sid: str) -> dict:
            r = client.post(f"/scenario/{sid}/run")
            check(f"run {sid}", r.status_code == 200, f"{r.status_code} {r.text[:160]}")
            check(f"{sid} result persisted",
                  (scen_dir / f"{sid}.result.json").exists())
            res = r.json().get("result", {})
            check(f"{sid} result linked to its scenario_id",
                  res.get("scenario_id") == sid, str(res.get("scenario_id")))
            return res

        def tt(arm: dict | None) -> float | None:
            return (arm or {}).get("avg_travel_time_s")

        # ---- baseline: real metrics, NO fabricated comparison ---------------
        print("\n[baseline]")
        client.post("/scenario/scn-baseline/run")
        bres = client.get("/scenario/scn-baseline").json()["result"]
        check("baseline has real travel-time metric", isinstance(tt(bres["baseline"]), (int, float)))
        check("baseline does not fabricate a comparison",
              bres.get("comparison") is None and bres.get("scenario") is None)

        # ---- the three V1 scenarios -----------------------------------------
        cases = [
            ("Lane closure test", "lane_closure", {"edge_id": EDGE, "lane_index": 0}),
            ("Road closure test", "road_closure", {"edge_id": EDGE}),
            ("Traffic increase test", "traffic_increase", {"demand_multiplier": 1.5}),
        ]
        for name, typ, params in cases:
            print(f"\n[{typ}]")
            sid = create(name, typ, params)
            res1 = run(sid)

            base_tt, scen_tt = tt(res1.get("baseline")), tt(res1.get("scenario"))
            check(f"{typ} produced real baseline + scenario metrics",
                  isinstance(base_tt, (int, float)) and isinstance(scen_tt, (int, float)),
                  f"base={base_tt} scen={scen_tt}")
            check(f"{typ} has a real comparison (two arms, not fabricated)",
                  res1.get("comparison") is not None and bool(res1["comparison"].get("rows")))

            # ---- P12 impact attribution -------------------------------------
            imp = res1.get("impact")
            check(f"{typ} produced a P12 impact block",
                  isinstance(imp, dict) and bool(imp.get("edges")))
            if imp:
                edges = imp["edges"]
                attrs = [e["attribution"] for e in edges]
                n_direct = attrs.count("DIRECTLY_AFFECTED")
                n_sec = attrs.count("SECONDARILY_AFFECTED")
                summ = imp["summary"]
                check(f"{typ} measured many edges (real edgeData)", len(edges) >= 5,
                      f"n={len(edges)}")
                check(f"{typ} edgeData collected for BOTH arms",
                      bool(res1["baseline"].get("edges")) and bool(res1["scenario"].get("edges")))
                base_ed = list((active / "sumo" / "scenarios" / sid / "baseline").glob("seed_*/edgedata.xml"))
                scen_ed = list((active / "sumo" / "scenarios" / sid / "scenario").glob("seed_*/edgedata.xml"))
                check(f"{typ} edgedata.xml written to disk for both arms",
                      len(base_ed) >= 1 and len(scen_ed) >= 1, f"base={len(base_ed)} scen={len(scen_ed)}")
                check(f"{typ} summary.affected_roads agrees with raw edge list",
                      summ["affected_roads"] == n_direct + n_sec,
                      f"{summ['affected_roads']} vs {n_direct + n_sec}")
                check(f"{typ} summary.edges_measured agrees with raw edge list",
                      summ["edges_measured"] == len(edges))
                check(f"{typ} summary.travel_time_delta_pct traces to comparison",
                      summ["travel_time_delta_pct"] == next(
                          (r["delta_pct"] for r in res1["comparison"]["rows"]
                           if r["metric"] == "Average travel time"), "MISS"))
                check(f"{typ} critical junctions ranked from real deltas (score>0)",
                      isinstance(imp["critical_junctions"], list)
                      and all(j["impact_score"] > 0 for j in imp["critical_junctions"]))
                check(f"{typ} impact endpoint returns the persisted block",
                      client.get(f"/scenario/{sid}/impact").json().get("summary", {}).get("edges_measured") == len(edges))
                if typ in ("lane_closure", "road_closure"):
                    direct_ids = [e["edge_id"] for e in edges if e["attribution"] == "DIRECTLY_AFFECTED"]
                    check(f"{typ} closed edge {EDGE} is DIRECTLY_AFFECTED",
                          EDGE in direct_ids, str(direct_ids))
                    check(f"{typ} unchanged edges remain UNCHANGED",
                          "UNCHANGED" in attrs)
                    check(f"{typ} provenance records the closed edge + real source",
                          EDGE in imp["provenance"]["closed_edges"]
                          and "edgeData" in imp["provenance"]["metric_source"])
                else:
                    check(f"{typ} network-wide demand change affects roads",
                          summ["affected_roads"] >= 1, str(summ))

            if typ == "traffic_increase":
                check("more demand raises travel time (causal, real SUMO)",
                      scen_tt > base_tt, f"base={base_tt} scen={scen_tt}")

            # ---- rerun from stored config: reproducible ----------------------
            res2 = run(sid)
            check(f"{typ} rerun reproduces the same metric (fixed seeds)",
                  tt(res2.get("scenario")) == scen_tt,
                  f"first={scen_tt} rerun={tt(res2.get('scenario'))}")

        # ---- linkage across the whole list ----------------------------------
        print("\n[linkage + invariants]")
        items = client.get("/scenario/list").json()["scenarios"]
        check("every scenario in the list has a stored result",
              all(it["has_result"] for it in items), str([it["scenario"]["scenario_id"] for it in items]))

        # ---- canonical network untouched (hash proof) -----------------------
        check("canonical network is byte-for-byte unchanged",
              sha(net) == net_sha_before, f"{net_sha_before[:12]} -> {sha(net)[:12]}")
        check("no plain.edg.xml written into the project (no net edit)",
              not (active / "sumo" / "plain.edg.xml").exists())

        print("\n" + "=" * 60)
        print(f"{PASS} passed, {FAIL} failed")
        print("=" * 60)
        return 1 if FAIL else 0
    finally:
        shutil.rmtree(data_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
