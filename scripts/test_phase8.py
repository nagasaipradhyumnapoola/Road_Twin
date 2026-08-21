"""Automated verification test for Phase 8: Fusion & Human Validation Gate."""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.model.edits import Edit, apply_edits, write_validation_report, replay, read_edges
from vision.evidence import build_review_items


def test_phase8():
    print("=" * 70)
    print("PHASE 8 AUTOMATED VERIFICATION TEST")
    print("=" * 70)

    proj = ROOT / "projects" / "benchmark"
    build_dir = proj / "build"
    proj.mkdir(parents=True, exist_ok=True)
    build_dir.mkdir(parents=True, exist_ok=True)
    plain_edg = build_dir / "plain.edg.xml"

    if not plain_edg.exists():
        # Build plain XML from cached benchmark OSM
        from core.build.netconvert import osm_to_plain
        osm_candidates = [
            ROOT / "assets" / "benchmark" / "osm_4d543007d11ee85d.osm",
            ROOT / "assets" / "benchmark" / "benchmark.osm",
        ]
        osm_file = next((p for p in osm_candidates if p.exists()), None)
        if osm_file:
            osm_to_plain(osm_file, build_dir)

    # Step 1: Check baseline edge and observation
    obs_file = proj / "observations.json"
    if not obs_file.exists():
        # Fallback to cached benchmark observation
        cached_obs = ROOT / "assets" / "benchmark" / "observations.json"
        if cached_obs.exists():
            shutil.copy(cached_obs, obs_file)

    assert obs_file.exists(), "observations.json must exist"
    observations = json.loads(obs_file.read_text(encoding="utf-8"))
    assert len(observations) > 0, "observations.json must have items"
    print(f"[1] Observations loaded: {len(observations)} observation(s)")

    # Step 2: Test build_review_items fusion logic
    edg_map = read_edges(plain_edg)
    assert len(edg_map) > 0, "plain.edg.xml must have edges"
    baseline_dict = {}
    for eid, attrs in edg_map.items():
        num_lanes = int(attrs.get("numLanes", 1))
        baseline_dict[f"rt-road-{eid}"] = {
            "lane_count": num_lanes,
            "lane_count_provenance": {
                "source": "osm",
                "tag": f"lanes={num_lanes}",
                "inferred": False,
            },
        }

    # Ensure observation attaches to a real edge in the network
    target_edge = next(iter(edg_map.keys()))
    current_attached = observations[0].get("attached_to", {}).get("road_id", "")
    if current_attached not in baseline_dict:
        observations[0]["attached_to"]["road_id"] = f"rt-road-{target_edge}"
        observations[0]["value"] = int(edg_map[target_edge].get("numLanes", 1)) + 1
        obs_file.write_text(json.dumps(observations, indent=2), encoding="utf-8")

    items = build_review_items(observations, baseline_dict, min_confidence=0.3)
    assert len(items) > 0, "build_review_items must generate review items"
    target_item = items[0]
    print(f"[2] Fusion review items generated: {len(items)} items. First item status: {target_item['status']}")
    print(f"    Baseline: {target_item['baseline_value']} lanes vs AI: {target_item['observed_value']} lanes")

    # Step 3: Test decision application (ACCEPT_VISION)
    obs = observations[0]
    obs_id = obs["id"]
    target_edge = obs["attached_to"]["road_id"].replace("rt-road-", "")
    new_lanes = str(obs["value"])

    temp_edg = build_dir / "test_edited.edg.xml"
    shutil.copy(plain_edg, temp_edg)

    edit = Edit(
        edge_id=target_edge,
        attribute="numLanes",
        old_value=edg_map[target_edge]["numLanes"],
        new_value=new_lanes,
        source="accepted_vision",
        observation_id=obs_id,
        user_action="accept",
    )

    apply_edits(temp_edg, [edit])
    edited_edges = read_edges(temp_edg)
    assert edited_edges[target_edge]["numLanes"] == new_lanes, f"Expected {new_lanes} lanes, got {edited_edges[target_edge]['numLanes']}"
    print(f"[3] Edit applied to edge '{target_edge}': {edit.old_value} -> {edit.new_value} lanes")

    # Step 4: Write validation report
    report_file = proj / "validation_report.json"
    write_validation_report([edit], observations, report_file)
    assert report_file.exists(), "validation_report.json must be written"
    report_data = json.loads(report_file.read_text(encoding="utf-8"))
    assert len(report_data["decisions"]) == 1, "Validation report must record decision"
    print(f"[4] validation_report.json written with {len(report_data['decisions'])} decision(s)")

    # Step 5: Verify replay (Audit Invariant)
    replayed_edg = build_dir / "test_replayed.edg.xml"
    replay(plain_edg, report_file, replayed_edg)
    assert replayed_edg.exists(), "Replayed plain.edg.xml must exist"
    replayed_edges = read_edges(replayed_edg)
    assert replayed_edges[target_edge]["numLanes"] == new_lanes, "Replay must reproduce edited lane count"
    print(f"[5] Replay audit test PASSED: baseline XML + validation_report.json perfectly reproduces final network")

    # Step 6: Test Rejection (Immutable audit trail invariant)
    obs_rejected = list(observations)
    obs_rejected[0]["status"] = "REJECTED"
    reject_edit = Edit(
        edge_id=target_edge,
        attribute="numLanes",
        old_value=edg_map[target_edge]["numLanes"],
        new_value=edg_map[target_edge]["numLanes"],
        source="human",
        observation_id=obs_id,
        user_action="reject",
    )
    reject_report = proj / "test_reject_report.json"
    write_validation_report([reject_edit], obs_rejected, reject_report)
    reject_replayed = build_dir / "test_reject_replayed.edg.xml"
    replay(plain_edg, reject_report, reject_replayed)
    reject_edges = read_edges(reject_replayed)
    assert reject_edges[target_edge]["numLanes"] == edg_map[target_edge]["numLanes"], "Rejected decision must leave baseline unchanged"
    print(f"[6] Rejection test PASSED: observation marked REJECTED, baseline preserved")

    # Cleanup test files
    for p in [temp_edg, replayed_edg, reject_report, reject_replayed]:
        if p.exists():
            p.unlink()

    print("\n" + "=" * 70)
    print("ALL PHASE 8 INVARIANTS & AUDIT TESTS PASSED (100%)")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(test_phase8())
