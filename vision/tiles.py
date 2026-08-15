"""Georeferenced tile mosaic — the fix for audit item B2.

THE PROBLEM THIS SOLVES
SAM returns a mask in pixels. Grounding DINO returns boxes in pixels.
road_mask.geojson needs degrees. If your "benchmark image" is a screenshot or
a photograph, no function from pixels to degrees exists, and the entire fusion
phase has nothing to fuse. You discover this on day 4 with one day left.

THE FIX
Build the image yourself out of XYZ tiles. Then you know the exact bounding box
of the mosaic, and pixel -> lon/lat is a two-line affine transform.

Everything in this module except `fetch_mosaic` is pure arithmetic with no
network and no dependencies, which is why it is fully unit-tested.

LICENSING: set ROADTWIN_TILE_URL yourself and check the provider's terms.
Send a real User-Agent. Do not commit an API key.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

TILE_SIZE = 256


# ---------------------------------------------------------------------------
# slippy-map arithmetic
# ---------------------------------------------------------------------------
def deg2num(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    """lat/lon -> tile x,y at `zoom` (Web Mercator, EPSG:3857)."""
    lat = max(min(lat, 85.05112878), -85.05112878)
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def num2deg(x: float, y: float, zoom: int) -> tuple[float, float]:
    """Tile x,y (may be fractional) -> lat/lon of its NW corner."""
    n = 2.0 ** zoom
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))
    return lat, lon


def ground_resolution(lat: float, zoom: int) -> float:
    """Metres per pixel at this latitude and zoom.

    This is what converts a pixel width into a lane count, so it is load-bearing.
    """
    return 156543.03392804097 * math.cos(math.radians(lat)) / (2.0 ** zoom)


# ---------------------------------------------------------------------------
# the mosaic + its transform
# ---------------------------------------------------------------------------
@dataclass
class Mosaic:
    """A stitched tile image plus the exact transform that georeferences it."""

    zoom: int
    x0: int
    y0: int
    x1: int          # inclusive
    y1: int          # inclusive
    width_px: int
    height_px: int
    west: float
    south: float
    east: float
    north: float

    # -- pixel <-> world -------------------------------------------------
    def pixel_to_lonlat(self, px: float, py: float) -> tuple[float, float]:
        """Exact, because we built the mosaic and know its corners."""
        lon = self.west + (px / self.width_px) * (self.east - self.west)
        # y is linear in Mercator, not in latitude -- go through tile space
        ty = self.y0 + (py / TILE_SIZE)
        lat, _ = num2deg(self.x0, ty, self.zoom)
        return lon, lat

    def lonlat_to_pixel(self, lon: float, lat: float) -> tuple[float, float]:
        n = 2.0 ** self.zoom
        tx = (lon + 180.0) / 360.0 * n
        lat_c = max(min(lat, 85.05112878), -85.05112878)
        ty = (1.0 - math.asinh(math.tan(math.radians(lat_c))) / math.pi) / 2.0 * n
        return (tx - self.x0) * TILE_SIZE, (ty - self.y0) * TILE_SIZE

    def meters_per_pixel(self) -> float:
        return ground_resolution((self.north + self.south) / 2.0, self.zoom)

    def to_dict(self) -> dict:
        """Persist this. Without it the mosaic is just an image again."""
        return {
            "provider": "xyz-tiles",
            "zoom": self.zoom,
            "tile_range": {"x": [self.x0, self.x1], "y": [self.y0, self.y1]},
            "bbox_wgs84": [self.west, self.south, self.east, self.north],
            "size_px": [self.width_px, self.height_px],
            "meters_per_pixel": round(self.meters_per_pixel(), 4),
            "crs": "EPSG:4326",
        }


def plan_mosaic(bbox: tuple[float, float, float, float], zoom: int) -> Mosaic:
    """Work out which tiles cover `bbox` = (south, west, north, east)."""
    south, west, north, east = bbox
    x0, y0 = deg2num(north, west, zoom)      # NW corner
    x1, y1 = deg2num(south, east, zoom)      # SE corner
    x0, x1 = min(x0, x1), max(x0, x1)
    y0, y1 = min(y0, y1), max(y0, y1)

    nw_lat, nw_lon = num2deg(x0, y0, zoom)
    se_lat, se_lon = num2deg(x1 + 1, y1 + 1, zoom)

    return Mosaic(
        zoom=zoom, x0=x0, y0=y0, x1=x1, y1=y1,
        width_px=(x1 - x0 + 1) * TILE_SIZE,
        height_px=(y1 - y0 + 1) * TILE_SIZE,
        west=nw_lon, north=nw_lat, east=se_lon, south=se_lat,
    )


def fetch_mosaic(
    bbox: tuple[float, float, float, float],
    zoom: int,
    tile_url: str,
    out_png: str | Path,
    *,
    user_agent: str,
    max_tiles: int = 64,
    cache_dir: str | Path | None = None,
) -> Mosaic:
    """Download + stitch tiles. `tile_url` uses {z}/{x}/{y} placeholders.

    Cache the result and commit it. Venue wifi is not your friend.
    """
    import requests
    from PIL import Image

    m = plan_mosaic(bbox, zoom)
    n_tiles = (m.x1 - m.x0 + 1) * (m.y1 - m.y0 + 1)
    if n_tiles > max_tiles:
        raise ValueError(
            f"{n_tiles} tiles needed at zoom {zoom} (limit {max_tiles}). "
            "Shrink aoi_radius_m or drop the zoom by one."
        )
    if not tile_url:
        raise ValueError(
            "No tile URL configured. Set ROADTWIN_TILE_URL to a provider whose "
            "terms permit this use, then re-run."
        )

    canvas = Image.new("RGB", (m.width_px, m.height_px))
    sess = requests.Session()
    sess.headers["User-Agent"] = user_agent

    for xi, x in enumerate(range(m.x0, m.x1 + 1)):
        for yi, y in enumerate(range(m.y0, m.y1 + 1)):
            cached = Path(cache_dir) / f"t_{zoom}_{x}_{y}.png" if cache_dir else None
            if cached and cached.exists():
                img = Image.open(cached).convert("RGB")
            else:
                url = tile_url.format(z=zoom, x=x, y=y)
                r = sess.get(url, timeout=30)
                r.raise_for_status()
                if cached:
                    cached.parent.mkdir(parents=True, exist_ok=True)
                    cached.write_bytes(r.content)
                import io
                img = Image.open(io.BytesIO(r.content)).convert("RGB")
            canvas.paste(img, (xi * TILE_SIZE, yi * TILE_SIZE))

    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_png)
    print(f"[tiles] {n_tiles} tiles -> {out_png.name} "
          f"({m.width_px}x{m.height_px}px, {m.meters_per_pixel():.3f} m/px)")
    return m
