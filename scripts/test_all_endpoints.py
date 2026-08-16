"""Comprehensive live test of all FastAPI endpoints in RoadTwin."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from core.main import app

def run_comprehensive_check():
    print("=" * 70)
    print("COMPREHENSIVE ENDPOINT & WORKFLOW TEST")
    print("=" * 70)

    client = TestClient(app)

    # 1. Health
    r = client.get("/health")
    assert r.status_code == 200, f"Health failed: {r.text}"
    health_data = r.json()
    assert health_data["status"] == "ok"
    assert health_data["sumo"] is True
    print("[1] /health: OK", health_data)

    # 2. Vision status
    r = client.get("/vision/status")
    assert r.status_code == 200, f"Vision status failed: {r.text}"
    vision_data = r.json()
    assert vision_data["available"] is True
    print("[2] /vision/status: OK", vision_data)

    # 3. Location confirm
    loc_payload = {
        "name": "GST Road, Chennai",
        "lat": 12.8231,
        "lon": 80.0442,
        "aoi_radius_m": 500.0,
        "confirmed": True
    }
    r = client.post("/location/confirm", json=loc_payload)
    assert r.status_code == 200, f"Location confirm failed: {r.text}"
    print("[3] /location/confirm: OK")

    # 4. Location get
    r = client.get("/location")
    assert r.status_code == 200
    assert r.json()["confirmed"] is True
    print("[4] /location: OK")

    # 5. Network edges
    r = client.get("/network/edges")
    assert r.status_code == 200, f"Network edges failed: {r.text}"
    edges_data = r.json()
    assert len(edges_data["edges"]) > 0
    print(f"[5] /network/edges: OK ({len(edges_data['edges'])} edges found)")

    # 6. Demand generate
    r = client.post("/demand/generate", json={"period": 3.0, "force": False})
    assert r.status_code == 200, f"Demand generate failed: {r.text}"
    print("[6] /demand/generate: OK", r.json())

    # 7. Scenario build
    first_edge = list(edges_data["edges"].keys())[0]
    r = client.post("/scenario/build", json={"edge_id": first_edge, "lane_index": 0})
    assert r.status_code == 200, f"Scenario build failed: {r.text}"
    print(f"[7] /scenario/build for edge '{first_edge}': OK", r.json())

    # 8. Vision observations
    r = client.get("/vision/observations")
    assert r.status_code == 200, f"Vision observations failed: {r.text}"
    print(f"[8] /vision/observations: OK ({len(r.json().get('observations', []))} observations)")

    # 9. Review queue
    r = client.get("/review/queue")
    assert r.status_code == 200, f"Review queue failed: {r.text}"
    queue_data = r.json()
    assert queue_data["total"] >= 1
    target_obs_id = queue_data["items"][0]["observation_id"]
    print(f"[9] /review/queue: OK ({queue_data['total']} items in queue)")

    # 10. Review decision: ACCEPT_VISION
    r = client.post("/review/decision", json={
        "observation_id": target_obs_id,
        "action": "ACCEPT_VISION"
    })
    assert r.status_code == 200, f"Review decision ACCEPT failed: {r.text}"
    dec_data = r.json()
    assert dec_data["ok"] is True
    print(f"[10] /review/decision (ACCEPT_VISION): OK -> new lanes: {dec_data['new_value']}")

    # 11. Review decision: EDIT
    r = client.post("/review/decision", json={
        "observation_id": target_obs_id,
        "action": "EDIT",
        "edited_value": 5
    })
    assert r.status_code == 200, f"Review decision EDIT failed: {r.text}"
    print("[11] /review/decision (EDIT -> 5): OK")

    # 12. Review replay audit
    r = client.post("/review/replay")
    assert r.status_code == 200, f"Review replay failed: {r.text}"
    replay_data = r.json()
    assert replay_data["ok"] is True
    assert replay_data["matches"] is True
    print("[12] /review/replay: OK -> matches:", replay_data["matches"])

    # 13. Review decision: KEEP_BASELINE (Reject)
    r = client.post("/review/decision", json={
        "observation_id": target_obs_id,
        "action": "KEEP_BASELINE"
    })
    assert r.status_code == 200, f"Review decision KEEP_BASELINE failed: {r.text}"
    print("[13] /review/decision (KEEP_BASELINE): OK")

    # 14. Export ZIP
    # Make sure metrics.json exists for packaging
    metrics_file = ROOT / "projects" / "benchmark" / "metrics.json"
    if metrics_file.exists():
        active_metrics = ROOT / "projects" / "active" / "metrics.json"
        import shutil
        shutil.copy(metrics_file, active_metrics)

    r = client.post("/export/zip")
    assert r.status_code == 200, f"Export zip failed: {r.text}"
    zip_data = r.json()
    assert zip_data["ok"] is True
    assert Path(zip_data["zip_path"]).exists()
    print(f"[14] /export/zip: OK ({zip_data['size_kb']} KB -> {zip_data['zip_path']})")

    print("\n" + "=" * 70)
    print("ALL 14 ENDPOINTS & CORE WORKFLOWS PASSED (100% GREEN)")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_comprehensive_check())
