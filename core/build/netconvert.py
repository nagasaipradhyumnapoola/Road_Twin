"""netconvert orchestration.

ADR-003: netconvert is the compiler backend for BOTH the SUMO network and the
OpenDRIVE export. We do not hand-write OpenDRIVE. See the audit (B1) for why:
a homegrown .xodr emitter is 2-3 days of work whose failure mode is a silently
disconnected network.

ADR-004: the plain XML files netconvert emits (.nod / .edg / .con / .tll / .typ)
are the EDITABLE SUBSTRATE. Everything downstream is regenerated from them.

    benchmark.osm --[netconvert]--> plain XML  <-- edits land here
                                        |
                                   [netconvert]
                                    /        \\
                          network.net.xml   road_network.xodr
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


# --------------------------------------------------------------------------
# binary + tool discovery
# --------------------------------------------------------------------------
def sumo_home() -> Path:
    """Locate the SUMO installation. SUMO is an external prerequisite (ADR-008)."""
    env = os.environ.get("SUMO_HOME")
    if env and Path(env).exists():
        return Path(env)
    # fall back to standard Windows install locations
    for standard_path in (
        Path("C:/Program Files (x86)/Eclipse/Sumo"),
        Path("C:/Program Files/Eclipse/Sumo"),
        Path(os.path.expanduser("~")) / "AppData/Local/Programs/Eclipse/Sumo",
    ):
        if standard_path.exists():
            return standard_path
    # fall back to inferring from a binary on PATH
    exe = shutil.which("netconvert")
    if exe:
        guess = Path(exe).resolve().parent.parent
        if (guess / "data").exists():
            return guess
    raise RuntimeError(
        "SUMO_HOME is not set and netconvert is not on PATH. "
        "Install SUMO (https://sumo.dlr.de/docs/Downloads.php) and set SUMO_HOME, e.g. "
        'setx SUMO_HOME "C:\\Program Files (x86)\\Eclipse\\Sumo" '
        "-- then open a NEW terminal."
    )


def sumo_bin(name: str) -> str:
    """Absolute path to a SUMO binary (netconvert, sumo, duarouter, ...)."""
    exe = shutil.which(name)
    if exe:
        return exe
    for cand in (sumo_home() / "bin" / name, sumo_home() / "bin" / f"{name}.exe"):
        if cand.exists():
            return str(cand)
    raise RuntimeError(f"SUMO binary '{name}' not found. Check SUMO_HOME / PATH.")


def sumo_tool(relpath: str) -> Path:
    """Path to a script under $SUMO_HOME/tools, e.g. 'randomTrips.py'."""
    p = sumo_home() / "tools" / relpath
    if not p.exists():
        raise RuntimeError(f"SUMO tool not found: {p}")
    return p


def _run(cmd: list[str], label: str) -> str:
    print(f"[{label}] {' '.join(str(c) for c in cmd[:3])} ...")
    proc = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"{label} failed (exit {proc.returncode})\n"
            f"--- stdout ---\n{proc.stdout[-4000:]}\n"
            f"--- stderr ---\n{proc.stderr[-4000:]}"
        )
    # netconvert reports real problems on stderr even when exiting 0
    warn = [l for l in proc.stderr.splitlines() if l.strip().startswith(("Warning", "Error"))]
    if warn:
        print(f"[{label}] {len(warn)} warnings, first 5:")
        for l in warn[:5]:
            print("   ", l)
    return proc.stdout + proc.stderr


# --------------------------------------------------------------------------
# stage 1: OSM -> plain XML (+ a first network so you can eyeball it)
# --------------------------------------------------------------------------
def osm_to_plain(osm_file: str | Path, build_dir: str | Path) -> dict[str, Path]:
    """Import OSM and emit the plain-XML substrate.

    The typemap is not optional: without it netconvert applies weak defaults for
    lane counts and speeds on Indian road classes, and your baseline is junk.
    """
    osm_file = Path(osm_file)
    build_dir = Path(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)
    prefix = build_dir / "plain"
    net = build_dir / "network.net.xml"

    typemap = sumo_home() / "data" / "typemap" / "osmNetconvert.typ.xml"

    cmd = [
        sumo_bin("netconvert"),
        "--osm-files", osm_file,
        "-o", net,
        "--plain-output-prefix", prefix,
        # --- geometry / topology cleanup: these turn raw OSM into a drivable net
        "--geometry.remove",              # collapse redundant shape nodes
        "--ramps.guess",
        "--junctions.join",               # merge multi-node intersections into one
        "--roundabouts.guess",
        # --- traffic lights
        "--tls.guess-signals",
        "--tls.discard-simple",
        "--tls.join",
        # --- keep only what a car can drive on
        "--keep-edges.by-vclass", "passenger",
        "--remove-edges.isolated",
        # --- traceability: keeps the OSM way id on the edge as a param
        "--output.original-names",
        "--no-warnings", "false",
    ]
    if typemap.exists():
        cmd[1:1] = ["--type-files", str(typemap)]
    else:
        print(f"[netconvert] WARNING: typemap not found at {typemap}")

    _run(cmd, "netconvert:osm")

    out = {
        "net": net,
        "nod": Path(f"{prefix}.nod.xml"),
        "edg": Path(f"{prefix}.edg.xml"),
        "con": Path(f"{prefix}.con.xml"),
        "tll": Path(f"{prefix}.tll.xml"),
        "typ": Path(f"{prefix}.typ.xml"),
    }
    missing = [k for k, v in out.items() if k in ("net", "nod", "edg") and not v.exists()]
    if missing:
        raise RuntimeError(f"netconvert produced no {missing}. The AOI may be empty.")
    return out


# --------------------------------------------------------------------------
# stage 2: plain XML -> network + OpenDRIVE   (run after every edit)
# --------------------------------------------------------------------------
def plain_to_net(
    plain: dict[str, Path],
    out_net: str | Path,
    xodr_out: str | Path | None = None,
) -> dict[str, Path]:
    """Recompile the network (and optionally the .xodr) from plain XML.

    This is the function the human-validation layer calls after an edit is
    accepted. One invocation regenerates every downstream consumer, which is
    why there is exactly one source of truth in this project.
    """
    out_net = Path(out_net)
    out_net.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sumo_bin("netconvert"),
        "--node-files", plain["nod"],
        "--edge-files", plain["edg"],
        "-o", out_net,
        "--output.original-names",
    ]
    if plain.get("con") and Path(plain["con"]).exists():
        cmd += ["--connection-files", plain["con"]]
    if plain.get("tll") and Path(plain["tll"]).exists():
        cmd += ["--tllogic-files", plain["tll"]]
    if plain.get("typ") and Path(plain["typ"]).exists():
        cmd += ["--type-files", plain["typ"]]

    if xodr_out:
        xodr_out = Path(xodr_out)
        cmd += [
            "--opendrive-output", xodr_out,
            # smoother junction geometry in the exported OpenDRIVE
            "--junctions.scurve-stretch", "1.0",
        ]

    _run(cmd, "netconvert:plain")

    result = {"net": out_net}
    if xodr_out:
        if not Path(xodr_out).exists():
            raise RuntimeError("netconvert did not produce the OpenDRIVE output.")
        result["xodr"] = Path(xodr_out)
    return result


def verify_xodr_roundtrip(xodr: str | Path, tmp_net: str | Path) -> bool:
    """Re-import our own .xodr to prove it is a valid OpenDRIVE file.

    This is a two-line test that answers the judge question "is your OpenDRIVE
    actually valid?" with evidence instead of assertion. Run it in Day 3's gate.
    """
    try:
        _run(
            [sumo_bin("netconvert"), "--opendrive-files", str(xodr), "-o", str(tmp_net)],
            "netconvert:xodr-roundtrip",
        )
        return Path(tmp_net).exists()
    except RuntimeError as e:
        print(f"[roundtrip] FAILED: {e}")
        return False
