"""Build a RoadTwin canonical model from a SUMO net.xml + OSM metadata.

Called from the API after netconvert has produced network.net.xml.
Emits:
  - roadtwin.json
  - roads.geojson    (MapLibre overlay)
  - junctions.geojson
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from lxml import etree

from core.model.roadtwin import (
    GeoJSONGeometry, Junction, Lane, LaneProvenance, LaneSource,
    Location, ProvenanceEntry, Road, RoadTwinModel,
)
from core.model.geometry import edges_to_geojson, junctions_to_geojson


# highway → (default_lanes, confidence)
_LANE_DEFAULTS: dict[str, tuple[int, float]] = {
    "motorway": (3, 0.5),
    "motorway_link": (1, 0.4),
    "trunk": (2, 0.4),
    "trunk_link": (1, 0.4),
    "primary": (2, 0.4),
    "primary_link": (1, 0.4),
    "secondary": (2, 0.35),
    "secondary_link": (1, 0.35),
    "tertiary": (1, 0.3),
    "unclassified": (1, 0.3),
    "residential": (1, 0.3),
    "service": (1, 0.3),
}


def _load_osm_lane_ways(osm_file: Path | str | None) -> dict[int, int]:
    """Map OSM way id -> explicit `lanes` value, for the ways that declare one.

    This is the ground truth for provenance: netconvert does NOT round-trip the
    OSM `lanes` tag onto the net.xml edge (it keeps only `origId`, the way id).
    So "did OSM state the lane count?" is answerable only from the raw OSM,
    joined back to the edge through that way id.
    """
    if not osm_file or not Path(osm_file).exists():
        return {}
    out: dict[int, int] = {}
    root = etree.parse(str(osm_file)).getroot()
    for way in root.findall("way"):
        wid = way.get("id")
        if not wid:
            continue
        for tag in way.findall("tag"):
            if tag.get("k") == "lanes":
                # OSM `lanes` is normally "4"; occasionally "2;3" (per-direction).
                raw = (tag.get("v") or "").split(";")[0].strip()
                try:
                    out[int(wid)] = int(raw)
                except ValueError:
                    pass
                break
    return out


def _edge_osm_way_ids(edge_el: Any) -> list[int]:
    """OSM way id(s) this SUMO edge derives from.

    netconvert records the original way id in a `param key="origId"` (on the
    lane, sometimes space-separated when edges were joined). The edge id itself
    encodes it too ("568057022#0", "-1046062574"), used as a fallback.
    """
    ids: list[int] = []
    for p in edge_el.iterfind(".//param"):
        if p.get("key") == "origId":
            for tok in (p.get("value") or "").split():
                t = tok.lstrip("-")
                if t.isdigit():
                    ids.append(int(t))
    if not ids:
        core = edge_el.get("id", "").lstrip("-").split("#")[0]
        if core.isdigit():
            ids.append(int(core))
    seen: set[int] = set()
    uniq: list[int] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            uniq.append(i)
    return uniq


def _lane_provenance(
    edge_el: Any, osm_lanes: dict[int, int]
) -> tuple[LaneProvenance, int | None]:
    """Return (provenance, osm_way_id) for an edge's lane count.

    Honestly records whether OSM stated the lane count. `osm_lanes` maps OSM
    way id -> explicit `lanes` value; if any of this edge's source ways is in
    it, the count is OSM-provided (never inferred). Returns the matched way id
    so the Road can preserve the OSM reference.
    """
    way_ids = _edge_osm_way_ids(edge_el)
    for wid in way_ids:
        if wid in osm_lanes:
            return (
                LaneProvenance(
                    source=LaneSource.osm_tag,
                    rule=f"OSM way {wid} lanes={osm_lanes[wid]}",
                    confidence=1.0,
                ),
                wid,
            )

    # No OSM lanes tag on any source way — infer from highway type
    road_type = edge_el.get("type", "unclassified").split(".")[-1]  # strip prefix
    n_lanes, conf = _LANE_DEFAULTS.get(road_type, (1, 0.25))
    return (
        LaneProvenance(
            source=LaneSource.inferred_default,
            rule=f"highway={road_type} -> {n_lanes} lanes",
            confidence=conf,
        ),
        way_ids[0] if way_ids else None,
    )


def build_from_net(
    net_file: Path,
    location: Location,
    project_dir: Path,
    osm_sha256: str | None = None,
    osm_file: Path | str | None = None,
) -> RoadTwinModel:
    """Parse `net_file`, build and persist the canonical model.

    `osm_file` is the raw OSM extract the net was built from. It is the source
    of truth for lane-count provenance: netconvert drops the OSM `lanes` tag, so
    without it every road is (wrongly) labelled inferred. When omitted,
    provenance degrades safely to inferred_default.

    Writes:
        <project_dir>/roadtwin.json
        <project_dir>/roads.geojson
        <project_dir>/junctions.geojson
    """
    project_dir.mkdir(parents=True, exist_ok=True)

    # --- OSM lane-tag ground truth (for provenance) ---
    osm_lanes = _load_osm_lane_ways(osm_file)

    # --- parse net.xml ---
    tree = etree.parse(str(net_file))
    root = tree.getroot()

    roads: list[Road] = []
    lanes: list[Lane] = []
    junctions: list[Junction] = []
    road_idx = 0
    lane_idx = 0

    for edge_el in root.findall("edge"):
        if edge_el.get("function") == "internal":
            continue                            # skip internal junction edges
        edge_id = edge_el.get("id", "")
        road_id = f"rt-road-{road_idx:04d}"
        road_idx += 1

        lane_els = edge_el.findall("lane")
        prov, osm_way_id = _lane_provenance(edge_el, osm_lanes)
        # infer road_type from SUMO `type` attr (format "highway.trunk" etc.)
        sumo_type = edge_el.get("type", "")
        road_type = sumo_type.split(".")[-1] if "." in sumo_type else "unclassified"

        # speed from first lane (all same on an edge)
        speed_ms = float(lane_els[0].get("speed", "13.89")) if lane_els else 13.89

        # length from first lane
        length_m = float(lane_els[0].get("length", "0")) if lane_els else 0.0

        roads.append(Road(
            id=road_id,
            sumo_edge_id=edge_id,
            osm_way_id=osm_way_id,
            direction="forward",
            road_type=road_type,
            speed_kph=round(speed_ms * 3.6, 1),
            length_m=round(length_m, 2),
            lane_count=len(lane_els),
            lane_count_provenance=prov,
        ))

        for lane_el in lane_els:
            lane_sumo_id = lane_el.get("id", "")
            idx_str = lane_sumo_id.rsplit("_", 1)[-1]
            idx = int(idx_str) if idx_str.isdigit() else lane_idx
            lanes.append(Lane(
                id=f"rt-lane-{road_idx-1:04d}-{idx}",
                road_id=road_id,
                sumo_lane_id=lane_sumo_id,
                index=idx,
                width_m=float(lane_el.get("width", "3.2")),
                speed_kph=round(speed_ms * 3.6, 1),
            ))
            lane_idx += 1

    junc_idx = 0
    for junc_el in root.findall("junction"):
        j_type = junc_el.get("type", "")
        if j_type in ("internal", "dead_end"):
            continue
        junc_id_str = f"rt-junction-{junc_idx:04d}"
        junc_idx += 1
        has_sig = j_type in ("traffic_light", "traffic_light_unregulated",
                              "traffic_light_right_on_red")
        junctions.append(Junction(
            id=junc_id_str,
            sumo_node_id=junc_el.get("id", ""),
            has_signal=has_sig,
        ))

    # --- GeoJSON layers for MapLibre ---
    roads_gj_path = project_dir / "roads.geojson"
    juncs_gj_path = project_dir / "junctions.geojson"
    try:
        roads_gj = edges_to_geojson(net_file)
        juncs_gj = junctions_to_geojson(net_file)
        roads_gj_path.write_text(json.dumps(roads_gj), encoding="utf-8")
        juncs_gj_path.write_text(json.dumps(juncs_gj), encoding="utf-8")
    except Exception as exc:
        print(f"[builder] geojson export warning: {exc}")

    # --- provenance ---
    prov_entries = [ProvenanceEntry(
        source="netconvert",
        tool="netconvert",
        created_at=datetime.utcnow(),
        inputs=[{"path": str(net_file), "sha256": osm_sha256 or ""}],
        outputs=[{"path": str(project_dir / "roadtwin.json")}],
    )]

    model = RoadTwinModel(
        project_id=project_dir.name,
        location=location,
        roads=roads,
        lanes=lanes,
        junctions=junctions,
        provenance=prov_entries,
    )

    (project_dir / "roadtwin.json").write_text(
        model.model_dump_json(indent=2), encoding="utf-8"
    )
    return model
