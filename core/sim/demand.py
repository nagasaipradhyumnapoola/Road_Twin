"""Traffic demand generation.

The single most important number in this file is `period`.

A lane closure on an empty road changes nothing. If you demo "42s baseline vs
42s closure" the whole project looks pointless, and that is a demand-calibration
failure, not a modelling failure. Day 3 task: tune `period` until the corridor
runs at ~75-85% of capacity, then WRITE THE VALUE DOWN in DEMO_SPEC.md.

Routes are generated ONCE and reused by both the baseline and the closure run.
Same net, same routes, same seeds -> the only variable is the closure, so the
difference is causal. This is what makes the experiment defensible.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from core.build.netconvert import sumo_tool


def generate_routes(
    net_file: str | Path,
    out_dir: str | Path,
    *,
    begin: int = 0,
    end: int = 3600,
    period: float = 1.0,
    fringe_factor: float = 10.0,
    seed: int = 42,
    prefix: str = "veh",
) -> dict[str, Path]:
    """Run randomTrips.py to build trips + validated routes.

    period: seconds between vehicle insertions. LOWER = MORE traffic.
            period=1.0 -> ~3600 veh/h offered demand across the network.
    fringe_factor: >1 biases trips to start/end at the network boundary,
            which is what you want for a corridor study (through traffic
            rather than vehicles materialising mid-link).
    """
    net_file = Path(net_file)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    trips = out_dir / "trips.trips.xml"
    routes = out_dir / "routes.rou.xml"

    cmd = [
        sys.executable,
        str(sumo_tool("randomTrips.py")),
        "-n", str(net_file),
        "-o", str(trips),
        "-r", str(routes),          # implies duarouter -> validated routes
        "-b", str(begin),
        "-e", str(end),
        "-p", str(period),
        "--fringe-factor", str(fringe_factor),
        "--seed", str(seed),
        "--prefix", prefix,
        "--validate",
        "--trip-attributes", 'departLane="best" departSpeed="max"',
    ]
    print(f"[demand] randomTrips period={period} ({begin}-{end}s)")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not routes.exists():
        raise RuntimeError(
            f"randomTrips failed (exit {proc.returncode})\n"
            f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
        )

    n = routes.read_text(errors="ignore").count("<vehicle ")
    print(f"[demand] generated {n} vehicles -> {routes.name}")
    if n < 50:
        print(
            "[demand] WARNING: very low demand. A lane closure will not change the\n"
            "         metrics. Lower `period` in config.py and regenerate."
        )
    return {"trips": trips, "routes": routes, "count": n}


def suggest_period(current_period: float, veh_count: int, target: int = 1500) -> float:
    """Crude calibration helper for the Day 3 tuning loop.

    Run the baseline, look at how many vehicles completed, and step toward the
    target. Two or three iterations is normally enough.
    """
    if veh_count <= 0:
        return max(current_period / 4, 0.1)
    ratio = veh_count / target
    return round(max(current_period * ratio, 0.1), 3)
