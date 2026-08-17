#!/usr/bin/env python3
"""Day 0 gate. Run this BEFORE writing any application code.

    python scripts/verify_environment.py

Every failure here costs minutes now and hours later. The benchmark check in
particular protects Phases 2, 4, 5, 6 and 7 simultaneously -- it is the highest
leverage five minutes in the entire project.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK, BAD, WARN = "  OK  ", " FAIL ", " WARN "
results: list[tuple[str, str, str]] = []


def check(name: str, fn) -> None:
    try:
        status, detail = fn()
    except Exception as e:
        status, detail = BAD, f"{type(e).__name__}: {e}"
    results.append((status, name, detail))
    # keep the table readable; multi-line messages are wrapped, not dumped
    first, *rest = str(detail).splitlines() or [""]
    print(f"[{status}] {name:<34} {first}")
    for line in rest:
        print(f"{'':<44}{line}")


def c_python():
    v = sys.version_info
    ok = (3, 10) <= (v.major, v.minor) < (3, 14)
    return (OK if ok else WARN), f"{v.major}.{v.minor}.{v.micro}"


def c_packages():
    missing = []
    for m in ("requests", "lxml", "numpy", "PIL", "pydantic"):
        try:
            __import__(m)
        except ImportError:
            missing.append(m)
    if missing:
        return BAD, f"missing: {', '.join(missing)}  ->  pip install -r requirements-core.txt"
    return OK, "requests lxml numpy pillow pydantic"


def c_sumo_home():
    import os
    h = os.environ.get("SUMO_HOME")
    if not h:
        for standard_path in (
            "C:/Program Files (x86)/Eclipse/Sumo",
            "C:/Program Files/Eclipse/Sumo",
        ):
            if Path(standard_path).exists():
                h = standard_path
                break
    if not h:
        return BAD, "SUMO_HOME not set. See SETUP.md."
    if not Path(h).exists():
        return BAD, f"SUMO_HOME points at a missing path: {h}"
    return OK, h


def _ver(binary: str):
    exe = shutil.which(binary)
    if not exe:
        import os
        h = os.environ.get("SUMO_HOME", "")
        for base in [h, "C:/Program Files (x86)/Eclipse/Sumo", "C:/Program Files/Eclipse/Sumo"]:
            if base:
                for cand in (Path(base) / "bin" / binary, Path(base) / "bin" / f"{binary}.exe"):
                    if cand.exists():
                        exe = str(cand)
                        break
                if exe:
                    break
    if not exe:
        return BAD, f"{binary} not found on PATH or in SUMO_HOME/bin"
    out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20)
    line = (out.stdout or out.stderr).strip().splitlines()[0]
    return OK, line


def c_netconvert():
    return _ver("netconvert")


def c_sumo():
    return _ver("sumo")


def c_typemap():
    from core.build.netconvert import sumo_home
    p = sumo_home() / "data" / "typemap" / "osmNetconvert.typ.xml"
    if not p.exists():
        return WARN, f"typemap missing at {p} (lane defaults will be weak)"
    return OK, str(p)


def c_randomtrips():
    from core.build.netconvert import sumo_home
    p = sumo_home() / "tools" / "randomTrips.py"
    return (OK, str(p)) if p.exists() else (BAD, f"not found: {p}")


def c_network():
    import requests
    try:
        r = requests.get("https://overpass-api.de/api/status", timeout=15,
                         headers={"User-Agent": "RoadTwin/0.1 verify"})
        return (OK if r.status_code == 200 else WARN), f"overpass HTTP {r.status_code}"
    except Exception as e:
        return WARN, f"no Overpass access ({type(e).__name__}); use --offline + cache"


def c_cached_osm():
    import config as C
    hits = list(C.BENCHMARK_DIR.glob("osm_*.osm"))
    if not hits:
        return WARN, "no cached OSM yet -- run run_benchmark.py once online, then commit it"
    return OK, f"{len(hits)} cached extract(s) -- demo insurance in place"


def c_torch():
    try:
        import torch
    except ImportError:
        return WARN, "torch absent (vision sidecar only; core does not need it)"
    return OK, f"torch {torch.__version__}, cuda={torch.cuda.is_available()}"


def c_node():
    exe = shutil.which("npm")
    if not exe:
        return WARN, "npm not found (needed for the Tauri frontend)"
    out = subprocess.run([exe, "--version"], capture_output=True, text=True, shell=False)
    return OK, f"npm {out.stdout.strip()}"


def c_rust():
    # PATH first, then the rustup default home for the CURRENT user.
    # (This used to also probe a hardcoded C:/Users/yashk/... path -- another
    #  developer's machine. It could never help anyone else and made the check
    #  look machine-specific. CARGO_HOME is rustup's own override.)
    import os
    exe = shutil.which("cargo")
    if not exe:
        cargo_home = os.environ.get("CARGO_HOME") or (Path.home() / ".cargo")
        for cand in (Path(cargo_home) / "bin" / "cargo.exe",
                     Path(cargo_home) / "bin" / "cargo"):
            if cand.exists():
                exe = str(cand)
                break
    if not exe:
        return WARN, "cargo not found (needed to build the Tauri shell)"
    out = subprocess.run([exe, "--version"], capture_output=True, text=True)
    return OK, out.stdout.strip()


def main() -> int:
    print("\nRoadTwin environment check\n" + "-" * 72)
    for name, fn in [
        ("python version", c_python),
        ("core python packages", c_packages),
        ("SUMO_HOME", c_sumo_home),
        ("netconvert", c_netconvert),
        ("sumo", c_sumo),
        ("osm typemap", c_typemap),
        ("randomTrips.py", c_randomtrips),
        ("overpass reachable", c_network),
        ("cached benchmark OSM", c_cached_osm),
        ("torch / cuda (vision)", c_torch),
        ("npm (frontend)", c_node),
        ("cargo (tauri)", c_rust),
    ]:
        check(name, fn)

    fails = [r for r in results if r[0] == BAD]
    warns = [r for r in results if r[0] == WARN]
    print("-" * 72)
    print(f"{len(results)-len(fails)-len(warns)} ok, {len(warns)} warn, {len(fails)} fail")
    if fails:
        print("\nFix the failures before starting Day 1. See SETUP.md.")
        return 1
    print("\nEnvironment is ready. Next: the benchmark-location check in "
          "EXECUTION_PLAN.md (Day 0, step 4).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
