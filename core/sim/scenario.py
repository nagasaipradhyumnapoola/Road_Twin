"""Lane-closure scenario generation.

ADR-006: a closure is a rerouter additional-file, NOT a network edit.

Why this matters. If you rebuild the network to close a lane you change edge
ids, lane ids and possibly routes, and then baseline-vs-closure is no longer a
controlled comparison. With a rerouter, both runs load the identical network
and the identical routes; the only difference is the closure. The delta is
therefore causal, which is exactly what a judge will probe.

    <rerouter id="rr" edges="UPSTREAM CLOSED">
      <interval begin="300" end="3600">
        <closingLaneReroute id="CLOSED_1" allow="authority"/>
      </interval>
    </rerouter>

HONEST LIMITATION (read this before you promise "150 m of lane 2"):
closingLaneReroute closes a lane for the WHOLE edge. SUMO has no partial-length
lane closure. So the real closure length is the length of that edge. Two
options:
  (a) report the actual edge length in the UI and say so  <-- do this
  (b) split the edge in plain XML to get exactly 150 m    <-- only if time allows
Option (a) is honest and costs nothing. Fabricating "150 m" when you closed a
340 m edge is the kind of detail that unravels a demo under questioning.
"""
from __future__ import annotations

from pathlib import Path

from lxml import etree


# ---------------------------------------------------------------------------
# network introspection (plain lxml -- no sumolib dependency needed)
# ---------------------------------------------------------------------------
def read_net_edges(net_file: str | Path) -> dict[str, dict]:
    """Return {edge_id: {lanes: [{id, index, length, speed}], function, from, to}}.

    Internal junction edges (function="internal", id starts with ':') are skipped.
    """
    tree = etree.parse(str(net_file))
    edges: dict[str, dict] = {}
    for e in tree.getroot().iter("edge"):
        eid = e.get("id")
        if not eid or eid.startswith(":") or e.get("function") == "internal":
            continue
        lanes = []
        for ln in e.iter("lane"):
            lanes.append(
                {
                    "id": ln.get("id"),
                    "index": int(ln.get("index", 0)),
                    "length": float(ln.get("length", 0.0)),
                    "speed": float(ln.get("speed", 0.0)),
                }
            )
        lanes.sort(key=lambda d: d["index"])
        edges[eid] = {
            "from": e.get("from"),
            "to": e.get("to"),
            "priority": e.get("priority"),
            "lanes": lanes,
            "num_lanes": len(lanes),
            "length_m": lanes[0]["length"] if lanes else 0.0,
        }
    return edges


def upstream_edges(net_file: str | Path, edge_id: str) -> list[str]:
    """Edges that feed into `edge_id`. Put the rerouter on these too.

    A rerouter only affects vehicles that pass over one of its `edges`. Placing
    it on the closed edge alone means vehicles learn about the closure too late
    to divert; including the upstream edges gives them somewhere to go.
    """
    tree = etree.parse(str(net_file))
    ups = set()
    for c in tree.getroot().iter("connection"):
        if c.get("to") == edge_id:
            frm = c.get("from")
            if frm and not frm.startswith(":"):
                ups.add(frm)
    return sorted(ups)


def downstream_edges(net_file: str | Path, edge_id: str) -> list[str]:
    """Edges that `edge_id` feeds into. The mirror of upstream_edges().

    Used to reject fringe edges when picking a closure candidate: an edge with
    no downstream is where traffic LEAVES the network, and closing a lane there
    cannot propagate congestion anywhere.
    """
    tree = etree.parse(str(net_file))
    dns = set()
    for c in tree.getroot().iter("connection"):
        if c.get("from") == edge_id:
            to = c.get("to")
            if to and not to.startswith(":"):
                dns.add(to)
    return sorted(dns)


# ---------------------------------------------------------------------------
# scenario writing
# ---------------------------------------------------------------------------
def build_lane_closure(
    net_file: str | Path,
    out_file: str | Path,
    *,
    edge_id: str,
    lane_index: int,
    begin: int = 300,
    end: int = 3600,
    include_upstream: bool = True,
) -> dict:
    """Write the closure additional-file. Returns a description of what was closed."""
    net_file, out_file = Path(net_file), Path(out_file)
    edges = read_net_edges(net_file)

    if edge_id not in edges:
        raise ValueError(
            f"Edge '{edge_id}' is not in the network. "
            f"Available (first 10): {list(edges)[:10]}"
        )
    info = edges[edge_id]

    if info["num_lanes"] < 2:
        raise ValueError(
            f"Edge '{edge_id}' has {info['num_lanes']} lane(s). Closing the only "
            "lane of an edge severs the network rather than constraining it. "
            "Pick a multi-lane edge, or model this as a full edge closure."
        )
    if not (0 <= lane_index < info["num_lanes"]):
        raise ValueError(
            f"lane_index {lane_index} out of range for '{edge_id}' "
            f"(0..{info['num_lanes'] - 1}; 0 is the rightmost lane)"
        )

    lane_id = f"{edge_id}_{lane_index}"
    trigger = [edge_id] + (upstream_edges(net_file, edge_id) if include_upstream else [])

    root = etree.Element("additional")
    rr = etree.SubElement(root, "rerouter", id=f"rr_closure_{edge_id}_{lane_index}",
                          edges=" ".join(trigger))
    iv = etree.SubElement(rr, "interval", begin=str(begin), end=str(end))
    # allow="authority" is the documented way to close a lane to normal traffic
    etree.SubElement(iv, "closingLaneReroute", id=lane_id, allow="authority")

    out_file.parent.mkdir(parents=True, exist_ok=True)
    etree.ElementTree(root).write(
        str(out_file), pretty_print=True, xml_declaration=True, encoding="UTF-8"
    )

    desc = {
        "edge_id": edge_id,
        "lane_id": lane_id,
        "lane_index": lane_index,
        "lanes_on_edge": info["num_lanes"],
        "actual_closed_length_m": round(info["length_m"], 1),
        "begin": begin,
        "end": end,
        "trigger_edges": trigger,
        "additional_file": str(out_file),
        "note": (
            "SUMO closes the lane for the full edge length; "
            f"the effective closure is {info['length_m']:.0f} m."
        ),
    }
    print(f"[scenario] closing {lane_id} ({info['length_m']:.0f} m) from {begin}s to {end}s")
    return desc


def pick_closure_candidate(net_file: str | Path, min_lanes: int = 2, min_length: float = 100.0):
    """Suggest a good edge to close: multi-lane, long, high priority.

    Useful for the demo -- you want a closure that visibly hurts, on a road the
    audience can see on the map.
    """
    edges = read_net_edges(net_file)
    cands = [
        (eid, d) for eid, d in edges.items()
        if d["num_lanes"] >= min_lanes and d["length_m"] >= min_length
    ]
    # Reject fringe edges. An edge with no upstream is where traffic ENTERS the
    # network and one with no downstream is where it LEAVES; closing a lane on
    # either meters flow instead of obstructing it, which makes the network
    # *faster* and the experiment meaningless. The P2 benchmark picked a 682 m
    # entry edge purely because it was the longest, and reported a -1.6 %
    # travel time -- a closure that helped. Require both directions.
    connected = [
        (eid, d) for eid, d in cands
        if upstream_edges(net_file, eid) and downstream_edges(net_file, eid)
    ]
    if connected:
        cands = connected
    else:
        print("[scenario] WARNING: no multi-lane edge has both upstream and "
              "downstream connectivity; falling back to fringe candidates. The "
              "closure may not produce a physically meaningful delta.")
    if not cands:
        return None
    cands.sort(key=lambda kv: (kv[1]["num_lanes"], kv[1]["length_m"]), reverse=True)
    eid, d = cands[0]
    return {"edge_id": eid, "num_lanes": d["num_lanes"], "length_m": round(d["length_m"], 1)}
