"""Persist scenarios and their results, per project.

Layout under <project>/scenarios/:
    scn-baseline.json          the always-present reference scenario
    scn-001.json               a created scenario definition (immutable)
    scn-001.result.json        its last run's real metrics (overwritten on rerun)

The definition and the result are separate files: the definition is what makes a
run reproducible; the result is the outcome of one run. Rerunning overwrites only
the result.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.scenario.models import BASELINE, Scenario

_SUBDIR = "scenarios"
BASELINE_ID = "scn-baseline"


def _dir(project_dir: str | Path) -> Path:
    d = Path(project_dir) / _SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _def_path(project_dir: str | Path, sid: str) -> Path:
    return _dir(project_dir) / f"{sid}.json"


def _result_path(project_dir: str | Path, sid: str) -> Path:
    return _dir(project_dir) / f"{sid}.result.json"


def _is_definition(p: Path) -> bool:
    return p.suffix == ".json" and not p.name.endswith(".result.json")


def next_id(project_dir: str | Path) -> str:
    """Next scn-NNN id, ignoring the named baseline and any result files."""
    nums = []
    for p in _dir(project_dir).glob("scn-*.json"):
        if not _is_definition(p):
            continue
        tail = p.stem.split("-", 1)[1] if "-" in p.stem else ""
        if tail.isdigit():
            nums.append(int(tail))
    n = (max(nums) + 1) if nums else 1
    return f"scn-{n:03d}"


def save(project_dir: str | Path, scenario: Scenario) -> Scenario:
    _def_path(project_dir, scenario.scenario_id).write_text(
        json.dumps(scenario.to_dict(), indent=2), encoding="utf-8"
    )
    return scenario


def load(project_dir: str | Path, sid: str) -> Scenario | None:
    p = _def_path(project_dir, sid)
    if not p.exists():
        return None
    return Scenario.from_dict(json.loads(p.read_text(encoding="utf-8")))


def list_scenarios(project_dir: str | Path) -> list[Scenario]:
    """All scenario definitions, baseline first, then by id."""
    out = []
    for p in sorted(_dir(project_dir).glob("*.json")):
        if _is_definition(p):
            out.append(Scenario.from_dict(json.loads(p.read_text(encoding="utf-8"))))
    out.sort(key=lambda s: (s.scenario_id != BASELINE_ID, s.scenario_id))
    return out


def save_result(project_dir: str | Path, sid: str, result: dict[str, Any]) -> Path:
    p = _result_path(project_dir, sid)
    p.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return p


def load_result(project_dir: str | Path, sid: str) -> dict[str, Any] | None:
    p = _result_path(project_dir, sid)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def ensure_baseline(project_dir: str | Path, seeds: list[int]) -> Scenario:
    """Guarantee a baseline scenario exists so the list is never empty."""
    existing = load(project_dir, BASELINE_ID)
    if existing:
        return existing
    return save(project_dir, Scenario(
        scenario_id=BASELINE_ID, name="Baseline", type=BASELINE, seeds=list(seeds),
    ))
