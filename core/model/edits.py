"""The edit layer — where human decisions become engineering changes.

An accepted review item ends up here. We rewrite the plain .edg.xml, then
call netconvert once, and the SUMO network, the OpenDRIVE export and the
simulation all follow. That single funnel is the reason the twin stays
consistent.

Every edit is recorded so that  baseline + validation_report -> final model
is exactly reproducible. That replayability is the strongest engineering
claim in the project; do not let it rot.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lxml import etree


@dataclass
class Edit:
    """One human-authoritative change to the road model."""

    edge_id: str
    attribute: str                 # "numLanes" | "speed" | "priority"
    old_value: str | None
    new_value: str
    source: str = "human"          # human | accepted_vision
    observation_id: str | None = None   # the evidence this decision responds to
    confidence: float = 1.0
    user_action: str = "accept"    # accept | reject | edit
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------
def read_edges(edg_file: str | Path) -> dict[str, dict[str, str]]:
    """Return {edge_id: {attribute: value}} from a plain .edg.xml."""
    tree = etree.parse(str(edg_file))
    out: dict[str, dict[str, str]] = {}
    for edge in tree.getroot().iter("edge"):
        eid = edge.get("id")
        if eid:
            out[eid] = dict(edge.attrib)
    return out


def lane_ids_for_edge(edg_file: str | Path, edge_id: str, num_lanes: int | None = None) -> list[str]:
    """SUMO lane ids are '<edge_id>_<index>', index 0 = rightmost."""
    if num_lanes is None:
        edges = read_edges(edg_file)
        if edge_id not in edges:
            raise KeyError(f"edge '{edge_id}' not in {edg_file}")
        num_lanes = int(edges[edge_id].get("numLanes", 1))
    return [f"{edge_id}_{i}" for i in range(num_lanes)]


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------
def apply_edits(
    edg_file: str | Path,
    edits: list[Edit],
    out_file: str | Path | None = None,
) -> Path:
    """Apply edits to a plain .edg.xml and write the result.

    Returns the path written. Call netconvert.plain_to_net() afterwards to
    regenerate network.net.xml and road_network.xodr.
    """
    edg_file = Path(edg_file)
    out_file = Path(out_file) if out_file else edg_file

    parser = etree.XMLParser(remove_blank_text=False)
    tree = etree.parse(str(edg_file), parser)
    root = tree.getroot()

    index = {e.get("id"): e for e in root.iter("edge") if e.get("id")}
    applied, skipped = 0, []

    for ed in edits:
        node = index.get(ed.edge_id)
        if node is None:
            skipped.append(ed.edge_id)
            continue
        ed.old_value = node.get(ed.attribute)
        node.set(ed.attribute, str(ed.new_value))
        applied += 1

        # A numLanes reduction must also drop any explicit <lane index="N">
        # children with N >= the new count. netconvert emits these per-lane
        # elements (they hold origId etc.), and leaving a lane index that the
        # edge no longer has makes it abort: "Lane index is larger than number
        # of lanes". Increasing lanes keeps every existing child (all indices
        # stay < numLanes), so this is a no-op there.
        if ed.attribute == "numLanes" and str(ed.new_value).isdigit():
            n = int(ed.new_value)
            for lane in list(node.findall("lane")):
                li = lane.get("index")
                if li is not None and li.isdigit() and int(li) >= n:
                    node.remove(lane)

    if skipped:
        print(f"[edits] WARNING: {len(skipped)} edge(s) not found: {skipped[:5]}")

    out_file.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(out_file), pretty_print=True, xml_declaration=True, encoding="UTF-8")
    print(f"[edits] applied {applied}/{len(edits)} edit(s) -> {out_file.name}")
    return out_file


def prune_stale_connections(
    con_file: str | Path,
    edg_file: str | Path,
    out_file: str | Path | None = None,
) -> tuple[Path, int]:
    """Drop connections that reference lane indices an edge no longer has.

    Reducing an edge's ``numLanes`` (e.g. an accepted vision correction of a
    4-lane road down to 3) leaves the plain ``.con.xml`` referencing the removed
    lane (``fromLane``/``toLane`` >= the new count). netconvert rejects that with
    "Lane index is larger than number of lanes". This is the connection-cleanup
    step the edit pipeline runs after a lane reduction and before netconvert, so
    the editable plain network stays the single source of truth.

    A connection is stale when its ``fromLane`` exceeds the lane count of its
    ``from`` edge, or its ``toLane`` exceeds the lane count of its ``to`` edge.
    Lanes are 0-indexed, so a valid index is ``0 .. numLanes-1``. Returns the
    written path and the number of connections removed.
    """
    con_file = Path(con_file)
    out_file = Path(out_file) if out_file else con_file

    lane_counts = {
        eid: int(attrs.get("numLanes", "1"))
        for eid, attrs in read_edges(edg_file).items()
        if str(attrs.get("numLanes", "")).isdigit()
    }

    parser = etree.XMLParser(remove_blank_text=False)
    tree = etree.parse(str(con_file), parser)
    root = tree.getroot()

    def _stale(edge_id: str | None, lane_attr: str | None) -> bool:
        if edge_id is None or lane_attr is None or edge_id not in lane_counts:
            return False
        try:
            return int(lane_attr) >= lane_counts[edge_id]
        except ValueError:
            return False

    removed = 0
    for conn in list(root.iter("connection")):
        if _stale(conn.get("from"), conn.get("fromLane")) or \
           _stale(conn.get("to"), conn.get("toLane")):
            conn.getparent().remove(conn)
            removed += 1

    out_file.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(out_file), pretty_print=True, xml_declaration=True, encoding="UTF-8")
    if removed:
        print(f"[edits] pruned {removed} stale connection(s) -> {out_file.name}")
    return out_file, removed


def write_validation_report(
    edits: list[Edit],
    observations: list[dict[str, Any]],
    out_path: str | Path,
) -> Path:
    """The audit trail: every observation, every decision, replayable.

    Rule: observations are IMMUTABLE. A rejected observation stays in the file
    with status REJECTED; it is never deleted. The final model must be
    derivable from (baseline plain XML + this report) and nothing else.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "0.1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "observations": observations,
        "decisions": [asdict(e) for e in edits],
        "replay_note": (
            "Apply `decisions` in order to the baseline plain/*.edg.xml, then run "
            "netconvert, to reproduce the final model byte-for-byte."
        ),
    }
    out_path.write_text(json.dumps(payload, indent=2))
    return out_path


def replay(baseline_edg: str | Path, report_path: str | Path, out_edg: str | Path) -> Path:
    """Reproduce the final model from the baseline + the report. Proves the claim."""
    report = json.loads(Path(report_path).read_text())
    edits = [
        Edit(
            edge_id=d["edge_id"],
            attribute=d["attribute"],
            old_value=d.get("old_value"),
            new_value=d["new_value"],
            source=d.get("source", "human"),
            observation_id=d.get("observation_id"),
            user_action=d.get("user_action", "accept"),
        )
        for d in report["decisions"]
        if d.get("user_action") != "reject"
    ]
    return apply_edits(baseline_edg, edits, out_edg)
