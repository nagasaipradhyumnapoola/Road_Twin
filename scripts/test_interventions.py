"""End-to-end P13 intervention-engine test — REAL SUMO.

Generates candidate interventions for a real lane-closure scenario, evaluates a
lane-configuration and an alternative-routing candidate with real SUMO through
the actual /scenario/{id}/interventions* endpoints, ranks them, and proves the
canonical network is byte-for-byte unchanged. Also proves the failed-candidate
path returns a reason with NO fabricated metrics.

Requires SUMO (like run_benchmark.py); skips + exits 0 without it.

    .venv/Scripts/python scripts/test_interventions.py
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

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

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
        return subprocess.run([sumo_bin("sumo"), "--version"],
                              capture_output=True, text=True).returncode == 0
    except Exception:
        return False


def main() -> int:
    if not sumo_available():
        print("SKIP: SUMO not found.")
        return 0
    bench = ROOT / "projects" / "benchmark"
    if not (bench / "build" / "plain.edg.xml").exists():
        print("SKIP: benchmark plain files missing; run run_benchmark first.")
        return 0

    data_root = Path(tempfile.mkdtemp(prefix="rt_int_"))
    try:
        active = data_root / "projects" / "active"
        (active / "sumo").mkdir(parents=True)
        (active / "build").mkdir(parents=True)
        # Use the build/ net so the reference and the recompiled lane-config
        # branch share the same plain source.
        shutil.copy(bench / "build" / "network.net.xml", active / "sumo" / "network.net.xml")
        shutil.copy(bench / "sumo" / "routes.rou.xml", active / "sumo" / "routes.rou.xml")
        for f in ("nod", "edg", "con", "tll", "typ"):
            src = bench / "build" / f"plain.{f}.xml"
            if src.exists():
                shutil.copy(src, active / "build" / f"plain.{f}.xml")
        json.dump({"name": "t", "lat": 12.8261, "lon": 80.0413, "aoi_radius_m": 500,
                   "crs": "EPSG:4326", "confirmed": True}, open(active / "location.json", "w"))
        os.environ["ROADTWIN_DATA_DIR"] = str(data_root)

        net = active / "sumo" / "network.net.xml"
        plain_edg = active / "build" / "plain.edg.xml"
        net_sha0, edg_sha0 = sha(net), sha(plain_edg)

        from fastapi.testclient import TestClient
        import core.main as M
        from core.sim.scenario import pick_closure_candidate

        client = TestClient(M.app, raise_server_exceptions=False)

        cand = pick_closure_candidate(net)
        edge = cand["edge_id"]
        print(f"[scenario] closing lane on {edge} ({cand['num_lanes']} lanes)")

        # ---- create + run the lane-closure scenario (small seed set) ----------
        r = client.post("/scenario/create", json={
            "name": "P13 lane closure", "type": "lane_closure",
            "parameters": {"edge_id": edge, "lane_index": 0}, "seeds": [42, 43, 44]})
        check("scenario created", r.status_code == 200, r.text[:120])
        sid = r.json()["scenario"]["scenario_id"]
        rr = client.post(f"/scenario/{sid}/run")
        check("scenario ran (real SUMO)", rr.status_code == 200, rr.text[:120])

        # ---- generate candidates ---------------------------------------------
        g = client.post(f"/scenario/{sid}/interventions")
        check("candidates generated", g.status_code == 200, g.text[:160])
        payload = g.json()
        cands = payload["candidates"]
        types = {c["type"] for c in cands}
        check("both mandatory intervention types are generated",
              {"lane_configuration", "alternative_routing"} <= types, str(types))
        check("candidates are structured (id/scenario/type/params/validation_state)",
              all(all(k in c for k in
                      ("intervention_id", "scenario_id", "type", "name", "parameters",
                       "validation_state")) for c in cands))
        check("generated candidates are valid",
              all(c["validation_state"] == "valid" for c in cands),
              str([(c["type"], c["validation_state"]) for c in cands]))
        check("intervention definitions persisted",
              (active / "scenarios" / f"{sid}.interventions.json").exists())

        # ---- evaluate all with real SUMO (2 seeds for speed) ------------------
        run = client.post(f"/scenario/{sid}/interventions/run", json={"seeds": [42, 43]})
        check("interventions evaluated", run.status_code == 200, run.text[:200])
        pay = run.json()
        results = pay["results"]
        ev = [x for x in results if x["status"] == "evaluated"]
        check("every candidate produced a result", len(results) == len(cands))
        check("at least two candidates ran through SUMO", len(ev) >= 2, str(len(ev)))
        check("results carry REAL baseline + intervention metrics + deltas",
              all(isinstance(x["baseline"]["avg_travel_time_s"], (int, float))
                  and isinstance(x["intervention"]["avg_travel_time_s"], (int, float))
                  and x["deltas"]["travel_time_s"] is not None for x in ev))
        lane = next((x for x in ev if x["type"] == "lane_configuration"), None)
        route = next((x for x in ev if x["type"] == "alternative_routing"), None)
        check("lane-configuration candidate evaluated with real SUMO", lane is not None)
        check("alternative-routing candidate evaluated with real SUMO", route is not None)
        check("results persisted", (active / "scenarios" / f"{sid}.interventions.json").exists())

        # ---- ranking ----------------------------------------------------------
        rank = pay["ranking"]
        check("ranking selects a best tested option from real results",
              rank["best_tested_option"] is not None and bool(rank["ranked"]))
        check("winner is the top-ranked candidate",
              rank["best_tested_option"]["intervention_id"] == rank["ranked"][0])
        check("wording is 'best tested option', never 'optimal'",
              "optimal" not in rank["message"].lower())
        check("intervention endpoint serves the persisted result",
              client.get(f"/scenario/{sid}/interventions").json()["ranking"]["ranked"] == rank["ranked"])

        # ---- reproducible: rerun gives the same ranking -----------------------
        run2 = client.post(f"/scenario/{sid}/interventions/run", json={"seeds": [42, 43]})
        check("ranking is reproducible (same seeds, same order)",
              run2.json()["ranking"]["ranked"] == rank["ranked"],
              f'{run2.json()["ranking"]["ranked"]} vs {rank["ranked"]}')

        # ---- failed candidate: validation fails, reason kept, no fake metrics -
        from core.intervention import evaluator as IE
        from core.intervention.models import Candidate, INVALID
        bad = Candidate("int-bad", sid, "lane_configuration", "bad",
                        {"edge_id": "does-not-exist", "to_lanes": 9},
                        validation_state=INVALID, failure_reason="Edge 'does-not-exist' is not in the network.")
        fres = IE.evaluate(bad, net_file=net, base_routes=active / "sumo" / "routes.rou.xml",
                           closure_additional="x", closed_edge=None, reference={},
                           work_dir=data_root / "junk", seeds=[42], project_dir=active)
        check("failed candidate: status is failed with a reason",
              fres["status"] == "failed" and bool(fres.get("failure_reason")))
        check("failed candidate: NO fabricated metrics",
              "intervention" not in fres and "baseline" not in fres)

        # ---- canonical invariants --------------------------------------------
        check("canonical network is byte-for-byte unchanged",
              sha(net) == net_sha0, f"{net_sha0[:12]} -> {sha(net)[:12]}")
        check("canonical plain.edg.xml is byte-for-byte unchanged",
              sha(plain_edg) == edg_sha0)

        print("\n" + "=" * 60)
        print(f"{PASS} passed, {FAIL} failed")
        print("=" * 60)
        return 1 if FAIL else 0
    finally:
        shutil.rmtree(data_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
