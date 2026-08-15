"""Network geometry <-> WGS84.

THE GAP THIS FILLS
A SUMO network stores coordinates in PROJECTED METRES, offset by `netOffset`.
Nothing downstream can use that directly:

  - the MapLibre map needs lon/lat GeoJSON               (Phase 4)
  - SAM must be prompted with the road centerline in
    mosaic PIXELS, which requires lon/lat first          (Phase 7)

Without this module you reach Phase 7, try to project a centerline into the
tile mosaic, and discover there is no centerline to project. It is the one
connective piece between the deterministic half of the pipeline and the
vision half.

HOW THE CONVERSION WORKS
netconvert writes a <location> element carrying everything needed:

  <location netOffset="-368000.00,-1418000.00"
            convBoundary="0.00,0.00,500.00,400.00"
            origBoundary="80.0398,12.8194,80.0487,12.8268"
            projParameter="+proj=utm +zone=44 +ellps=WGS84 +datum=WGS84 +units=m +no_defs"/>

  projected_xy = net_xy - netOffset
  lon/lat      = inverse_project(projected_xy, projParameter)

Exact when pyproj is installed. When it is not, we fall back to interpolating
between convBoundary and origBoundary -- accurate to well under a metre over a
500 m AOI, which is fine for map display and for SAM prompts, and the module
tells you which mode it is in rather than hiding it.
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any, Sequence

from lxml import etree

try:                                    # optional, exact path
    from pyproj import Transformer      # type: ignore
    _HAVE_PYPROJ = True
except ImportError:                     # pragma: no cover
    _HAVE_PYPROJ = False


# ---------------------------------------------------------------------------
# <location>
# ---------------------------------------------------------------------------
def read_location(net_file: str | Path) -> dict[str, Any]:
    """Parse the <location> element from a SUMO net.xml."""
    tree = etree.parse(str(net_file))
    loc = tree.getroot().find("location")
    if loc is None:
        raise ValueError(f"{net_file} has no <location> element -- not a SUMO network?")

    def pair(name):
        v = loc.get(name)
        return tuple(float(t) for t in v.split(",")) if v else None

    return {
        "net_offset": pair("netOffset"),
        "conv_boundary": pair("convBoundary"),
        "orig_boundary": pair("origBoundary"),
        "proj_parameter": loc.get("projParameter", ""),
    }


class NetGeo:
    """Converts between SUMO network XY and WGS84 lon/lat."""

    def __init__(self, net_file: str | Path):
        self.net_file = Path(net_file)
        loc = read_location(net_file)
        self.net_offset = loc["net_offset"] or (0.0, 0.0)
        self.conv = loc["conv_boundary"]
        self.orig = loc["orig_boundary"]
        self.proj = loc["proj_parameter"] or ""

        self.exact = False
        self._fwd = self._inv = None

        if _HAVE_PYPROJ and self.proj and "+proj" in self.proj:
            try:
                self._inv = Transformer.from_crs(self.proj, "EPSG:4326", always_xy=True)
                self._fwd = Transformer.from_crs("EPSG:4326", self.proj, always_xy=True)
                self.exact = True
            except Exception as e:                      # pragma: no cover
                warnings.warn(f"pyproj could not use projParameter ({e}); "
                              "falling back to boundary interpolation")

        if not self.exact:
            if not (self.conv and self.orig):
                raise ValueError(
                    "Cannot georeference this network: no usable projParameter and "
                    "no convBoundary/origBoundary. Install pyproj, or rebuild the "
                    "network from OSM so netconvert records a projection."
                )
            warnings.warn(
                "NetGeo is using boundary interpolation (sub-metre accurate over a "
                "small AOI). `pip install pyproj` for the exact transform.",
                stacklevel=2,
            )

    # -- net XY -> lon/lat ------------------------------------------------
    def xy_to_lonlat(self, x: float, y: float) -> tuple[float, float]:
        if self.exact:
            px = x - self.net_offset[0]
            py = y - self.net_offset[1]
            lon, lat = self._inv.transform(px, py)
            return lon, lat
        x0, y0, x1, y1 = self.conv
        w, s, e, n = self.orig
        fx = (x - x0) / (x1 - x0) if x1 != x0 else 0.0
        fy = (y - y0) / (y1 - y0) if y1 != y0 else 0.0
        return w + fx * (e - w), s + fy * (n - s)

    # -- lon/lat -> net XY ------------------------------------------------
    def lonlat_to_xy(self, lon: float, lat: float) -> tuple[float, float]:
        if self.exact:
            px, py = self._fwd.transform(lon, lat)
            return px + self.net_offset[0], py + self.net_offset[1]
        x0, y0, x1, y1 = self.conv
        w, s, e, n = self.orig
        fx = (lon - w) / (e - w) if e != w else 0.0
        fy = (lat - s) / (n - s) if n != s else 0.0
        return x0 + fx * (x1 - x0), y0 + fy * (y1 - y0)

    def path_to_lonlat(self, pts: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
        return [self.xy_to_lonlat(x, y) for x, y in pts]


# ---------------------------------------------------------------------------
# shapes
# ---------------------------------------------------------------------------
def _parse_shape(s: str | None) -> list[tuple[float, float]]:
    if not s:
        return []
    out = []
    for tok in s.split():
        parts = tok.split(",")
        if len(parts) >= 2:
            out.append((float(parts[0]), float(parts[1])))
    return out


def read_edge_shapes(net_file: str | Path) -> dict[str, list[tuple[float, float]]]:
    """{edge_id: centerline in net XY}, taking the median lane of each edge.

    The median lane is used rather than the edge's own shape because the edge
    shape is often absent, and the median lane is guaranteed to lie ON the road
    surface -- which is exactly what SAM needs as a positive prompt.
    """
    tree = etree.parse(str(net_file))
    shapes: dict[str, list[tuple[float, float]]] = {}

    for e in tree.getroot().iter("edge"):
        eid = e.get("id")
        if not eid or eid.startswith(":") or e.get("function") == "internal":
            continue
        lanes = sorted(
            ((int(ln.get("index", 0)), _parse_shape(ln.get("shape"))) for ln in e.iter("lane")),
            key=lambda t: t[0],
        )
        lanes = [(i, s) for i, s in lanes if s]
        if not lanes:
            shape = _parse_shape(e.get("shape"))
            if shape:
                shapes[eid] = shape
            continue
        shapes[eid] = lanes[len(lanes) // 2][1]
    return shapes


def edge_centerline_lonlat(
    net_file: str | Path,
    edge_id: str,
    *,
    geo: NetGeo | None = None,
    max_points: int | None = None,
) -> list[tuple[float, float]]:
    """Centerline of one edge as [(lon, lat), ...].

    This is the function Phase 7 needs:

        geo    = NetGeo(net)
        line   = edge_centerline_lonlat(net, edge_id, geo=geo, max_points=24)
        px     = [mosaic.lonlat_to_pixel(lon, lat) for lon, lat in line]
        mask   = segment_road("mosaic.png", px)
    """
    shapes = read_edge_shapes(net_file)
    if edge_id not in shapes:
        raise KeyError(f"edge '{edge_id}' has no shape in {net_file}")
    geo = geo or NetGeo(net_file)
    pts = geo.path_to_lonlat(shapes[edge_id])

    if max_points and len(pts) > max_points:
        step = (len(pts) - 1) / (max_points - 1)
        pts = [pts[round(i * step)] for i in range(max_points)]
    return pts


def densify_lonlat(
    pts: Sequence[tuple[float, float]], every_m: float = 10.0
) -> list[tuple[float, float]]:
    """Insert intermediate points so SAM gets prompts along the whole road.

    netconvert's --geometry.remove collapses straight runs to two points, which
    would give SAM two prompts for a 300 m road. Densifying gives it coverage.
    """
    import math

    if len(pts) < 2:
        return list(pts)
    out: list[tuple[float, float]] = [tuple(pts[0])]
    for (lon1, lat1), (lon2, lat2) in zip(pts, pts[1:]):
        mlat = math.radians((lat1 + lat2) / 2)
        dx = (lon2 - lon1) * 111_320.0 * math.cos(mlat)
        dy = (lat2 - lat1) * 111_320.0
        dist = math.hypot(dx, dy)
        n = max(1, int(dist // every_m))
        for i in range(1, n):
            f = i / n
            out.append((lon1 + f * (lon2 - lon1), lat1 + f * (lat2 - lat1)))
        out.append((lon2, lat2))
    return out


# ---------------------------------------------------------------------------
# GeoJSON for the map (Phase 4)
# ---------------------------------------------------------------------------
def edges_to_geojson(net_file: str | Path, properties: dict[str, dict] | None = None) -> dict:
    """All drivable edges as a WGS84 LineString FeatureCollection."""
    geo = NetGeo(net_file)
    shapes = read_edge_shapes(net_file)
    feats = []
    for eid, pts in shapes.items():
        if len(pts) < 2:
            continue
        props = {"edge_id": eid}
        if properties and eid in properties:
            props.update(properties[eid])
        feats.append({
            "type": "Feature",
            "properties": props,
            "geometry": {
                "type": "LineString",
                "coordinates": [[round(lon, 7), round(lat, 7)]
                                for lon, lat in geo.path_to_lonlat(pts)],
            },
        })
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": feats,
        "_georeferencing": "exact (pyproj)" if geo.exact else "boundary interpolation",
    }


def junctions_to_geojson(net_file: str | Path) -> dict:
    """Real junctions (skips internal/dead-end nodes) as WGS84 Points."""
    geo = NetGeo(net_file)
    tree = etree.parse(str(net_file))
    feats = []
    for j in tree.getroot().iter("junction"):
        jid, jtype = j.get("id"), j.get("type")
        if not jid or jid.startswith(":") or jtype in ("internal", "dead_end"):
            continue
        try:
            lon, lat = geo.xy_to_lonlat(float(j.get("x")), float(j.get("y")))
        except (TypeError, ValueError):
            continue
        feats.append({
            "type": "Feature",
            "properties": {"junction_id": jid, "type": jtype,
                           "has_signal": jtype == "traffic_light"},
            "geometry": {"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]},
        })
    return {"type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
            "features": feats}
