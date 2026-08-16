"""Pydantic canonical model — per context/DATA_CONTRACT.md.

Schema version 0.2. Keep field names exactly as specified in DATA_CONTRACT.
Every entity has a stable prefixed id. lane_count_provenance is mandatory
on every Road — this is the key engineering story.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────────────────

class LaneSource(str, Enum):
    osm_tag         = "osm_tag"
    inferred_default = "inferred_default"
    accepted_vision = "accepted_vision"
    human           = "human"


class ObsStatus(str, Enum):
    REVIEW   = "REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EDITED   = "EDITED"


class GeomKind(str, Enum):
    georeferenced = "georeferenced"
    image_space   = "image_space"


# ── Sub-models ─────────────────────────────────────────────────────────────────

class LaneProvenance(BaseModel):
    source:     LaneSource
    rule:       str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class GeoJSONGeometry(BaseModel):
    type:        str
    coordinates: Any


class Location(BaseModel):
    name:                str
    lat:                 float
    lon:                 float
    aoi_radius_m:        float = 500.0
    crs:                 str   = "EPSG:4326"
    confirmed:           bool  = False
    confirmation_method: Literal["user", "manual_coords", "benchmark_config"] = "user"


# ── Road entities ───────────────────────────────────────────────────────────────

class Road(BaseModel):
    id:                   str                 # "rt-road-NNN"
    sumo_edge_id:         str
    osm_way_id:           int | None = None
    geometry:             GeoJSONGeometry | None = None
    direction:            Literal["forward", "backward", "both"] = "forward"
    road_type:            str = "unclassified"
    speed_kph:            float = 50.0
    length_m:             float = 0.0
    lane_count:           int   = 1
    lane_count_provenance: LaneProvenance


class Lane(BaseModel):
    id:          str          # "rt-lane-NNN-K"
    road_id:     str
    sumo_lane_id: str         # "<edge_id>_<index>"
    index:       int          # 0 = rightmost
    direction:   Literal["forward", "backward"] = "forward"
    width_m:     float = 3.5
    speed_kph:   float = 50.0


class Junction(BaseModel):
    id:             str        # "rt-junction-NNN"
    sumo_node_id:   str
    geometry:       GeoJSONGeometry | None = None
    incoming_roads: list[str] = Field(default_factory=list)
    outgoing_roads: list[str] = Field(default_factory=list)
    has_signal:     bool = False
    connections:    list[dict[str, str]] = Field(default_factory=list)


class RoadObject(BaseModel):
    id:        str
    road_id:   str
    type:      str
    geometry:  GeoJSONGeometry | None = None
    note:      str | None = None


# ── Observation (AI evidence) ──────────────────────────────────────────────────

class Observation(BaseModel):
    id:            str
    source:        str
    model:         str
    type:          str
    feature:       str | None = None
    value:         Any = None
    geometry_kind: GeomKind
    attached_to:   dict[str, str] = Field(default_factory=dict)
    confidence:    float = Field(ge=0.0, le=1.0)
    status:        ObsStatus = ObsStatus.REVIEW
    evidence:      dict[str, Any] | None = None
    # image-space only
    pixel_bbox:    list[int] | None = None
    source_image:  str | None = None
    geometry:      GeoJSONGeometry | None = None
    note:          str | None = None


# ── Provenance entry ───────────────────────────────────────────────────────────

class ProvenanceEntry(BaseModel):
    source:       str
    tool:         str
    tool_version: str | None = None
    created_at:   datetime = Field(default_factory=datetime.utcnow)
    inputs:       list[dict[str, str]] = Field(default_factory=list)
    outputs:      list[dict[str, str]] = Field(default_factory=list)


# ── Root model ─────────────────────────────────────────────────────────────────

class RoadTwinModel(BaseModel):
    schema_version: str = "0.2"
    project_id:     str = "benchmark"
    location:       Location
    roads:          list[Road]        = Field(default_factory=list)
    lanes:          list[Lane]        = Field(default_factory=list)
    junctions:      list[Junction]    = Field(default_factory=list)
    objects:        list[RoadObject]  = Field(default_factory=list)
    observations:   list[Observation] = Field(default_factory=list)
    validation:     list[dict]        = Field(default_factory=list)
    provenance:     list[ProvenanceEntry] = Field(default_factory=list)
