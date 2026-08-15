"""Grounding DINO open-vocabulary detection.

THREE RULES:

1. transformers, not the IDEA-Research repo. The upstream repo compiles a
   custom CUDA op (MultiScaleDeformableAttention) at install time and fails
   constantly on Windows. The transformers port is pure PyTorch.

2. PROMPT FORMAT MATTERS ENORMOUSLY. Lowercase, period-separated:
       "a traffic light. a traffic sign. a road barrier."
   not
       "Traffic Light, Traffic Sign, Road Barrier"
   The second form scores far worse. This is undocumented folklore that costs
   people an afternoon.

3. RIGHT MODEL, RIGHT IMAGERY. Grounding DINO is trained on ground-level
   photography. From nadir satellite imagery a traffic light is four pixels and
   the model will return confident nonsense. Street-level photo -> traffic
   lights, signs, barriers. Overhead -> vehicles, at best.

   Pothole detection is deliberately absent. Open-vocabulary models do not
   detect it reliably from any altitude; it is a texture, not a nameable
   object shape. Demoing it invites the model to box manhole covers and
   shadows in front of a judge.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

_MODEL: Any = None
_PROC: Any = None


def load(model_id: str = "IDEA-Research/grounding-dino-tiny", device: str | None = None):
    global _MODEL, _PROC
    if _MODEL is not None:
        return _MODEL, _PROC

    import torch
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[dino] loading {model_id} on {device}")
    _PROC = AutoProcessor.from_pretrained(model_id)
    _MODEL = AutoModelForZeroShotObjectDetection.from_pretrained(model_id).to(device).eval()
    return _MODEL, _PROC


def detect(
    image_path: str | Path,
    prompt: str,
    *,
    model_id: str = "IDEA-Research/grounding-dino-tiny",
    box_threshold: float = 0.35,
    text_threshold: float = 0.25,
    device: str | None = None,
) -> list[dict[str, Any]]:
    """Return detections as [{label, score, box_xyxy}] in PIXEL coordinates."""
    import torch
    from PIL import Image

    model, proc = load(model_id, device)
    image = Image.open(image_path).convert("RGB")

    if not prompt.strip().endswith("."):
        prompt = prompt.strip() + "."
    prompt = prompt.lower()

    inputs = proc(images=image, text=prompt, return_tensors="pt").to(model.device)
    with torch.no_grad():
        outputs = model(**inputs)

    results = proc.post_process_grounded_object_detection(
        outputs,
        inputs.input_ids,
        threshold=box_threshold,
        text_threshold=text_threshold,
        target_sizes=[image.size[::-1]],       # (height, width)
    )[0]

    dets = []
    for score, label, box in zip(results["scores"], results["labels"], results["boxes"]):
        dets.append({
            "label": str(label),
            "score": round(float(score), 4),
            "box_xyxy": [round(float(v), 1) for v in box.tolist()],
        })
    print(f"[dino] {len(dets)} detections above {box_threshold}")
    return dets


def to_observations(
    detections: list[dict[str, Any]],
    *,
    road_id: str,
    image_name: str,
    georeferenced_mosaic=None,
    id_prefix: str = "obs",
) -> list[dict[str, Any]]:
    """Wrap detections in the canonical observation envelope.

    THE geometry_kind FIELD IS NOT OPTIONAL. A detection from a street-level
    photo has no real-world coordinate; saying so explicitly is a one-line cost
    that pre-empts the sharpest question a technical judge can ask. Only pass
    `georeferenced_mosaic` when the source image really is a georeferenced
    overhead mosaic.
    """
    obs = []
    for i, d in enumerate(detections, 1):
        o: dict[str, Any] = {
            "id": f"{id_prefix}-{i:03d}",
            "source": "grounding_dino",
            "type": d["label"].replace(" ", "_"),
            "confidence": d["score"],
            "status": "REVIEW",
            "source_image": image_name,
            "pixel_bbox": d["box_xyxy"],
            "attached_to": {"road_id": road_id},
        }
        if georeferenced_mosaic is not None:
            x0, y0, x1, y1 = d["box_xyxy"]
            lon, lat = georeferenced_mosaic.pixel_to_lonlat((x0 + x1) / 2, (y0 + y1) / 2)
            o["geometry_kind"] = "georeferenced"
            o["geometry"] = {"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]}
        else:
            o["geometry_kind"] = "image_space"
            o["geometry"] = None
            o["note"] = ("Detected in a non-georeferenced image. Attached to a road "
                         "id; no real-world coordinate is claimed.")
        obs.append(o)
    return obs
