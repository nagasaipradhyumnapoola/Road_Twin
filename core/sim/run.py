"""SUMO execution.

Baseline and scenario differ by exactly one thing: the additional-file.
Same network, same routes, same seed set.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from lxml import etree

from core.build.netconvert import sumo_bin
from core.sim import metrics as M


def _write_edgedata_additional(add_path: Path, out_path: Path,
                               begin: int, end: int) -> None:
    """Write a SUMO additional that tells SUMO to emit per-edge metrics.

    One aggregation interval over the whole run, so the output has a single
    per-edge row. ``excludeEmpty`` drops edges no vehicle used (their metrics
    would be degenerate); the impact analysis treats a missing edge as
    unchanged rather than inventing a value. The output path is absolute so it
    lands in out_dir regardless of SUMO's working directory.
    """
    root = etree.Element("additional")
    etree.SubElement(
        root, "edgeData", id="ed", file=str(out_path.resolve()),
        begin=str(begin), end=str(end), excludeEmpty="true",
    )
    etree.ElementTree(root).write(
        str(add_path), pretty_print=True, xml_declaration=True, encoding="UTF-8"
    )


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
    edgedata: bool = True,
) -> Path:
    """One SUMO run. Writes tripinfo/queue/summary into out_dir.

    When ``edgedata`` is set (default), also emits per-edge metrics
    (edgedata.xml) via an extra additional-file — real SUMO output used by the
    P12 impact analysis. It is measurement-only and does not change the
    simulation, so baseline vs scenario stays a controlled comparison.
    """
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

    # Additional-files: the per-edge collector (optional) plus the scenario's
    # closure additional (optional). SUMO takes them as one comma-separated list.
    adds: list[str] = []
    if edgedata:
        ed_add = out_dir / "edgedata.add.xml"
        _write_edgedata_additional(ed_add, out_dir / "edgedata.xml", begin, end)
        adds.append(str(ed_add))
    if additional:
        adds.append(str(additional))
    if adds:
        cmd += ["-a", ",".join(adds)]

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
    collect_edges: bool = True,
) -> dict[str, Any]:
    """Run one scenario across every seed and aggregate.

    With ``collect_edges`` (default) the aggregate also carries per-edge means
    across seeds under ``agg["edges"]`` — the raw material the P12 impact
    analysis compares baseline against scenario. It is additive: the existing
    network-level keys are unchanged.
    """
    work_dir = Path(work_dir)
    runs = []
    edge_runs: list[dict[str, Any]] = []
    for s in seeds:
        d = work_dir / label / f"seed_{s}"
        run_once(net_file, routes_file, d, seed=s, begin=begin, end=end,
                 additional=additional, edgedata=collect_edges)
        runs.append(M.collect_run(d, edge_filter=edge_filter))
        if collect_edges:
            edge_runs.append(M.collect_edges(d))
    # Pass seeds so the per-seed values survive aggregation -- compare() pairs
    # baseline and closure by seed, and cannot do that from means alone.
    agg = M.aggregate(runs, seeds=seeds)
    agg["label"] = label
    if collect_edges and edge_runs:
        agg["edges"] = M.aggregate_edges(edge_runs)
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
