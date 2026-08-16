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


def _lane_provenance(edge_el: Any) -> LaneProvenance:
    """Return provenance for lane count — records honestly whether OSM said it."""
    # SUMO propagates the original OSM `lanes` param tag as `numLanes`
    # We detect a genuine OSM tag vs a netconvert-inferred one by checking
    # whether the edge has a `param` child with key="lanes"
    for param in edge_el.findall("param"):
        if param.get("key") == "lanes":
            return LaneProvenance(source=LaneSource.osm_tag, confidence=1.0)

    # No OSM tag — infer from highway type
    road_type = edge_el.get("type", "unclassified").split(".")[-1]  # strip prefix
    n_lanes, conf = _LANE_DEFAULTS.get(road_type, (1, 0.25))
    return LaneProvenance(
        source=LaneSource.inferred_default,
        rule=f"highway={road_type} -> {n_lanes} lanes",
        confidence=conf,
    )


def build_from_net(
    net_file: Path,
    location: Location,
    project_dir: Path,
    osm_sha256: str | None = None,
) -> RoadTwinModel:
    """Parse `net_file`, build and persist the canonical model.

    Writes:
        <project_dir>/roadtwin.json
        <project_dir>/roads.geojson
        <project_dir>/junctions.geojson
    """
    project_dir.mkdir(parents=True, exist_ok=True)

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
        prov = _lane_provenance(edge_el)
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
