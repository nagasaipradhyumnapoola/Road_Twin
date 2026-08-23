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
# HTTP identity for public APIs (Nominatim, Overpass)
# ---------------------------------------------------------------------------
# Nominatim's usage policy REQUIRES an identifying User-Agent and returns 403
# for obvious placeholders -- the old "contact: you@example.com" value was
# blocked outright, which killed address geocoding. This identifies the app by
# its public repository (legitimate identification, not a fabricated personal
# contact) and is overridable so an operator can supply their own contact
# without editing source. ROADTWIN_NOMINATIM_USER_AGENT wins for geocoding
# specifically; ROADTWIN_USER_AGENT is the general fallback.
_DEFAULT_USER_AGENT = (
    "RoadTwin/0.1 (+https://github.com/nagasaipradhyumnapoola/Road_Twin)"
)
USER_AGENT = os.environ.get("ROADTWIN_USER_AGENT", _DEFAULT_USER_AGENT)
NOMINATIM_USER_AGENT = os.environ.get(
    "ROADTWIN_NOMINATIM_USER_AGENT", USER_AGENT
)

# ---------------------------------------------------------------------------
# BENCHMARK LOCATION
# ---------------------------------------------------------------------------
# !! Day 0 task: VERIFY these coordinates before you build anything on them.
#    Run  python scripts/run_benchmark.py --skip-sim
#    then open  projects/benchmark/sumo/network.net.xml  in netedit and LOOK.
#    (There is no --check-benchmark flag; verification is this run + netedit.
#     See prompts/day-00-setup.md §2.)
#    Requirements (see EXECUTION_PLAN.md, Day 0):
#      - the main road carries a `lanes` tag in OSM
#      - at least one real junction inside the AOI
#      - lane markings visible in satellite imagery at zoom 19
# ---------------------------------------------------------------------------
# Verified 2026-08-18 against the cached extract (assets/benchmark/osm_*.osm).
# The previous centre (12.8231, 80.0442) sat 462 m from the nearest point of
# GST Road -- the corridor this benchmark is named for only clipped the AOI
# corner (334 m of trunk inside 500 m), and the AOI was centred on a
# residential colony. This centre is the nearest real GST Road junction
# (OSM node 792253820, trunk x residential), 466 m away, so it is the smallest
# move that puts the corridor and its junctions inside the AOI:
#
#                        OLD (12.8231,80.0442)   NEW (12.8261,80.0413)
#   trunk metres in AOI          334 m                  1038 m
#   trunk edges kept                 4                      6
#   junctions in AOI                85                     52
#   closure candidate            117 m                   498 m
#
# (Figures are post-AOI-clip predictions measured from the cached OSM; the
#  clip itself is applied by netconvert -- see core/build/netconvert.py.)
BENCHMARK = {
    "name": "GST Road, Chennai",
    "lat": 12.8261,
    "lon": 80.0413,
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
    "period": 3.0,
    "fringe_factor": 10,          # bias trips to enter/leave at network edges
    # 20 seeds, not 5. The closure response on this network is BIMODAL: about
    # a quarter of seeds tip into network-wide breakdown and the rest absorb
    # the closure. Five seeds cannot resolve that -- the expected number of
    # breakdowns in five draws is ~1.25, so a 5-seed run lands anywhere from
    # 0 to 3 and the mean swings (5 seeds gave +24.5%, 20 seeds gave +19.0%).
    # The paired test also needs degrees of freedom: t_crit falls from 2.776
    # at n=5 to 2.093 at n=20. Costs ~80 s.
    "seeds": list(range(42, 62)),
}

CLOSURE = {
    "begin": 300,                 # let the network fill before closing
    "end": 3600,
}

# ---------------------------------------------------------------------------
# IMPACT ATTRIBUTION (P12)
# ---------------------------------------------------------------------------
# Deterministic, reproducible thresholds for turning per-edge baseline-vs-
# scenario deltas into an impact class and an attribution. NOTHING here is
# hardcoded in the UI or the analysis code — change a number, re-run, get a
# different (still deterministic) classification. All inputs are real SUMO
# edgeData/queue values; no metric is synthesized.
IMPACT = {
    # MATERIALITY — an edge is "affected" (not UNCHANGED) only when its scenario
    # change clears one of these floors. Travel time is judged as a percentage
    # of the edge's own baseline; queue as an absolute increase in metres.
    "material_travel_time_pct": 10.0,   # |Δ edge travel time| ≥ 10 %
    "material_queue_delta_m": 5.0,      # OR queue grows ≥ 5 m

    # SEVERITY BANDS — class is the worse of the travel-time and queue bands.
    # Read [a, b, c] as:  LOW: worsening < a · MODERATE: a ≤ w < b ·
    # HIGH: b ≤ w < c · SEVERE: w ≥ c.  Only worsening (positive) counts.
    "travel_time_pct_bands": [10.0, 25.0, 50.0],
    "queue_delta_m_bands": [5.0, 15.0, 40.0],

    # CRITICAL JUNCTIONS — rank incident-edge worsening; keep the top N that
    # clear a minimum positive score (metres of queue + seconds of waiting).
    "junction_top_n": 5,
    "junction_min_score": 0.1,
}

# ---------------------------------------------------------------------------
# INTERVENTION ENGINE (P13)
# ---------------------------------------------------------------------------
# Candidate generation is deterministic and derived from real network/scenario
# state; these bound the search so a scenario spawns a small, testable set — the
# engine reports the "best tested option", never an "optimal" one.
INTERVENTION = {
    "lane_config_delta": 1,      # candidate adds this many lanes to a bottleneck
    "lane_config_max": 6,        # never propose more lanes than this on one edge
    "diversion_upstream_hops": 2,  # how far upstream the diversion rerouter reaches
    "max_candidates": 4,         # hard cap on candidates per scenario
}

# ---------------------------------------------------------------------------
# ENGINEER GOAL -> DECISION (P14)
# ---------------------------------------------------------------------------
# The goal search reuses the P13 tested candidates; it never runs a second
# search space. It only measures each already-tested option against the
# engineer's goal and reports whether the target was met — "best tested option",
# never "optimal", and an honest "not achieved" when nothing clears the target.
DECISION = {
    "default_target_pct": 20.0,   # improvement the goal form starts on
    "default_max_interventions": 1,  # V1 tests single-lever options only
    # V1 candidates are single interventions, so a max above this is recorded
    # but cannot be satisfied by a combination (none are tested). Kept explicit
    # so the limitation is visible rather than silently ignored.
    "supported_max_interventions": 1,
}

# ---------------------------------------------------------------------------
# IMAGERY  (Track A: georeferenced overhead tiles -> real GeoJSON)
# ---------------------------------------------------------------------------
# Pick a tile provider whose terms permit your use and set a real User-Agent.
# Do NOT ship an API key in the repo. Read TILE_URL from the environment.
IMAGERY = {
    "zoom": 19,
    "tile_url": os.environ.get("ROADTWIN_TILE_URL", ""),
    "user_agent": USER_AGENT,
    "max_tiles": 64,              # guard against accidental huge fetches
    # Lane WIDTH cannot be measured from an OSM cartographic raster -- roads are
    # drawn there as fixed-width casings, not real carriageways. The lane-evidence
    # path therefore only runs on genuine overhead/aerial imagery, and only when
    # the operator explicitly declares the configured tile source aerial. Unset,
    # false, or a cartographic host -> the pipeline refuses (insufficient evidence)
    # rather than inventing a lane count. Never silently substitute street tiles.
    "aerial": os.environ.get("ROADTWIN_TILE_AERIAL", "").strip().lower()
    in ("1", "true", "yes", "on"),
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
    # Physical plausibility ceiling for a single directional road edge. A SUMO
    # edge is one direction; more than this many lanes on one carriageway edge
    # means the mask has bled off the road, so the measurement is refused rather
    # than reported. Derived bound = nominal_lane_width_m * max_plausible_lanes
    # (=> 28 m). The 51.53 m / 15-lane benchmark false positive is rejected by it.
    "max_plausible_lanes": 8,
}

# ---------------------------------------------------------------------------
# OVERPASS
# ---------------------------------------------------------------------------
OVERPASS = {
    "endpoint": "https://lz4.overpass-api.de/api/interpreter",
    "user_agent": USER_AGENT,
    "timeout_s": 90,
}
