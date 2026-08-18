"""SUMO execution.

Baseline and scenario differ by exactly one thing: the additional-file.
Same network, same routes, same seed set.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from core.build.netconvert import sumo_bin
from core.sim import metrics as M


def run_once(
    net_file: str | Path,
    routes_file: str | Path,
    out_dir: str | Path,
    *,
    seed: int = 42,
    begin: int = 0,
    end: int = 3600,
    additional: str | Path | None = None,
    step_length: float = 1.0,
) -> Path:
    """One SUMO run. Writes tripinfo/queue/summary into out_dir."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sumo_bin("sumo"),
        "-n", str(net_file),
        "-r", str(routes_file),
        "--begin", str(begin),
        "--end", str(end),
        "--step-length", str(step_length),
        "--seed", str(seed),
        "--tripinfo-output", str(out_dir / "tripinfo.xml"),
        "--queue-output", str(out_dir / "queue.xml"),
        "--summary-output", str(out_dir / "summary.xml"),
        # Without a rerouting device vehicles cannot respond to the closure at
        # all -- they just queue. This flag is what makes the scenario meaningful.
        "--device.rerouting.probability", "1",
        "--device.rerouting.period", "60",
        "--no-step-log", "true",
        "--duration-log.statistics", "true",
        "--time-to-teleport", "300",
        "--ignore-route-errors", "true",
    ]
    if additional:
        cmd += ["-a", str(additional)]

    tag = "closure" if additional else "baseline"
    print(f"[sumo] {tag} seed={seed}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"sumo failed (exit {proc.returncode})\n"
            f"{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}"
        )
    return out_dir


def run_scenario(
    net_file: str | Path,
    routes_file: str | Path,
    work_dir: str | Path,
    *,
    seeds: list[int],
    begin: int = 0,
    end: int = 3600,
    additional: str | Path | None = None,
    label: str = "baseline",
    edge_filter: str | None = None,
) -> dict[str, Any]:
    """Run one scenario across every seed and aggregate."""
    work_dir = Path(work_dir)
    runs = []
    for s in seeds:
        d = work_dir / label / f"seed_{s}"
        run_once(net_file, routes_file, d, seed=s, begin=begin, end=end,
                 additional=additional)
        runs.append(M.collect_run(d, edge_filter=edge_filter))
    # Pass seeds so the per-seed values survive aggregation -- compare() pairs
    # baseline and closure by seed, and cannot do that from means alone.
    agg = M.aggregate(runs, seeds=seeds)
    agg["label"] = label
    warnings = [r["_warning"] for r in runs if r.get("_warning")]
    if warnings:
        agg["warnings"] = warnings[:3]
    return agg


def run_experiment(
    net_file: str | Path,
    routes_file: str | Path,
    work_dir: str | Path,
    closure_additional: str | Path,
    *,
    seeds: list[int],
    begin: int = 0,
    end: int = 3600,
    closed_edge: str | None = None,
) -> dict[str, Any]:
    """The full baseline-vs-closure experiment. This is the money shot."""
    base = run_scenario(net_file, routes_file, work_dir, seeds=seeds, begin=begin,
                        end=end, additional=None, label="baseline",
                        edge_filter=closed_edge)
    clos = run_scenario(net_file, routes_file, work_dir, seeds=seeds, begin=begin,
                        end=end, additional=closure_additional, label="closure",
                        edge_filter=closed_edge)
    cmp = M.compare(base, clos)
    return {"baseline": base, "closure": clos, "comparison": cmp,
            "table": M.format_table(cmp)}
