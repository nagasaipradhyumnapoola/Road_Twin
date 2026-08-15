"""RoadTwin — central configuration.

Every tunable lives here. Nothing else in the codebase hardcodes a
coordinate, a seed, or a path.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
BENCHMARK_DIR = ASSETS / "benchmark"
PROJECTS_DIR = ROOT / "projects"

# ---------------------------------------------------------------------------
# BENCHMARK LOCATION
# ---------------------------------------------------------------------------
# !! Day 0 task: VERIFY these coordinates before you build anything on them.
#    Run  python scripts/verify_environment.py --check-benchmark
#    Requirements (see EXECUTION_PLAN.md, Day 0):
#      - the main road carries a `lanes` tag in OSM
#      - at least one real junction inside the AOI
#      - lane markings visible in satellite imagery at zoom 19
# ---------------------------------------------------------------------------
BENCHMARK = {
    "name": "GST Road, Chennai",
    "lat": 12.8231,
    "lon": 80.0442,
    "aoi_radius_m": 500,          # keep small: build time scales with area
}

# ---------------------------------------------------------------------------
# SIMULATION
# ---------------------------------------------------------------------------
SIM = {
    "begin": 0,
    "end": 3600,                  # 1 simulated hour
    # randomTrips --period. LOWER = MORE traffic.
    # Day 3 task: tune this until the corridor sits at ~75-85% of capacity.
    # If you skip this, the lane closure will change nothing and the demo dies.
    "period": 0.8,
    "fringe_factor": 10,          # bias trips to enter/leave at network edges
    "seeds": [42, 43, 44, 45, 46],
}

CLOSURE = {
    "begin": 300,                 # let the network fill before closing
    "end": 3600,
}

# ---------------------------------------------------------------------------
# IMAGERY  (Track A: georeferenced overhead tiles -> real GeoJSON)
# ---------------------------------------------------------------------------
# Pick a tile provider whose terms permit your use and set a real User-Agent.
# Do NOT ship an API key in the repo. Read TILE_URL from the environment.
IMAGERY = {
    "zoom": 19,
    "tile_url": os.environ.get("ROADTWIN_TILE_URL", ""),
    "user_agent": "RoadTwin/0.1 (SIH95; contact: you@example.com)",
    "max_tiles": 64,              # guard against accidental huge fetches
}

VISION = {
    "sam_model": "facebook/sam2.1-hiera-small",
    "dino_model": "IDEA-Research/grounding-dino-tiny",
    # lowercase, period-separated -- this format matters a lot for Grounding DINO
    "dino_prompt_street": (
        "a traffic light. a traffic sign. a road barrier. "
        "a construction barrier. a median."
    ),
    "dino_prompt_overhead": "a car. a truck. a bus.",
    "box_threshold": 0.35,
    "text_threshold": 0.25,
    "nominal_lane_width_m": 3.5,
}

# ---------------------------------------------------------------------------
# OVERPASS
# ---------------------------------------------------------------------------
OVERPASS = {
    "endpoint": "https://overpass-api.de/api/interpreter",
    "user_agent": "RoadTwin/0.1 (SIH95; contact: you@example.com)",
    "timeout_s": 90,
}
