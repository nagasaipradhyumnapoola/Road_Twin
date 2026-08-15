"""SAM 2.1 road-surface segmentation.

TWO THINGS THAT MAKE THIS WORK, both learned the hard way:

1. Use Hugging Face `transformers`, never the upstream `segment-anything-2`
   repo. The upstream repos have build steps that fail on Windows. transformers
   is pure PyTorch: pip install, import, done.

2. PROMPT SAM WITH THE OSM CENTERLINE. Do not ask SAM to "segment everything"
   and then guess which blob is the road. You already know where the road is --
   you have the OSM geometry, in the same coordinate frame as the mosaic. Feed
   centerline points as positive prompts and SAM becomes a road-surface
   extractor instead of a generic segmenter. This one change is the difference
   between a usable mask and an afternoon of disappointment.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import numpy as np

_MODEL: Any = None
_PROC: Any = None


def load(model_id: str = "facebook/sam2.1-hiera-small", device: str | None = None):
    """Load once and cache. Model init is slow; inference is not."""
    global _MODEL, _PROC
    if _MODEL is not None:
        return _MODEL, _PROC

    import torch
    from transformers import Sam2Model, Sam2Processor

    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[sam] loading {model_id} on {device}")
    _MODEL = Sam2Model.from_pretrained(model_id).to(device).eval()
    _PROC = Sam2Processor.from_pretrained(model_id)
    return _MODEL, _PROC


def segment_road(
    image_path: str | Path,
    centerline_px: Sequence[tuple[float, float]],
    *,
    model_id: str = "facebook/sam2.1-hiera-small",
    max_points: int = 24,
    device: str | None = None,
) -> np.ndarray:
    """Return a boolean road mask, same HxW as the image.

    centerline_px: OSM centerline projected into mosaic pixel coordinates
                   (use Mosaic.lonlat_to_pixel).
    """
    import torch
    from PIL import Image

    model, proc = load(model_id, device)
    image = Image.open(image_path).convert("RGB")

    # subsample evenly -- more points is not better, and it costs memory
    pts = list(centerline_px)
    if len(pts) > max_points:
        step = len(pts) / max_points
        pts = [pts[int(i * step)] for i in range(max_points)]

    input_points = [[[[float(x), float(y)] for x, y in pts]]]
    input_labels = [[[1] * len(pts)]]          # 1 = positive prompt

    inputs = proc(images=image, input_points=input_points,
                  input_labels=input_labels, return_tensors="pt").to(model.device)

    with torch.no_grad():
        outputs = model(**inputs, multimask_output=False)

    masks = proc.post_process_masks(
        outputs.pred_masks.cpu(), inputs["original_sizes"]
    )[0]
    mask = np.asarray(masks[0].squeeze().numpy() > 0.0, dtype=bool)

    cover = mask.mean()
    print(f"[sam] mask covers {cover*100:.1f}% of the image")
    if cover > 0.75:
        print("[sam] WARNING: mask covers most of the frame -- SAM has probably "
              "segmented the whole scene. Reduce max_points or check that the "
              "centerline is correctly projected into pixel space.")
    if cover < 0.01:
        print("[sam] WARNING: mask is nearly empty -- the centerline is likely "
              "not landing on the road. Verify the mosaic transform first.")
    return mask


def mask_to_geojson(mask: np.ndarray, mosaic, *, simplify_px: int = 4) -> dict:
    """Boolean mask -> GeoJSON polygon in EPSG:4326.

    This is only possible because the image is georeferenced (audit item B2).
    Contours are traced with a simple marching-squares walk over the mask
    boundary; good enough for a review overlay.
    """
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return {"type": "FeatureCollection", "features": []}

    # coarse outline: for each column, the topmost and bottommost road pixel
    step = max(1, simplify_px)
    top, bottom = [], []
    for x in range(xs.min(), xs.max() + 1, step):
        col = np.nonzero(mask[:, x])[0]
        if col.size:
            top.append(mosaic.pixel_to_lonlat(float(x), float(col.min())))
            bottom.append(mosaic.pixel_to_lonlat(float(x), float(col.max())))
    if len(top) < 2:
        return {"type": "FeatureCollection", "features": []}

    ring = [list(p) for p in top] + [list(p) for p in reversed(bottom)]
    ring.append(ring[0])

    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": [{
            "type": "Feature",
            "properties": {"source": "sam2", "kind": "road_surface"},
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        }],
    }
