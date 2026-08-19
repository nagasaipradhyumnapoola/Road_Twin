# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the RoadTwin core sidecar (ADR-007, ADR-011).

Produces a SINGLE file:  dist/api.exe

That executable is what Tauri ships as an `externalBin`. The Tauri side expects
a target-triple suffix, so the build step copies it to:

    apps/desktop/src-tauri/binaries/api-x86_64-pc-windows-msvc.exe

Build with:

    .venv\\Scripts\\activate
    pyinstaller --clean -y api_onefile.spec

Why this file is TRACKED in git: it is the only description of how the shipping
binary is produced. Without it `npm run tauri build` fails at
`resource path 'binaries\\api-x86_64-pc-windows-msvc.exe' doesn't exist`, which
is exactly how the P1 shipping path was lost. The generated .exe stays ignored.

Deliberately NOT bundled (ADR-007): torch, torchvision, transformers. Those
belong to the optional vision sidecar in .venv-vision, which is never frozen.
Bundling them turns a ~40 MB installer into a multi-GB one.
"""
from PyInstaller.utils.hooks import collect_submodules

# Every core.* module is imported lazily inside route handlers in core/main.py
# (e.g. `from core.build.netconvert import sumo_home` inside _sumo_ok). Collect
# the package wholesale rather than trying to keep a hand-written list in sync.
hidden = collect_submodules("core")

hidden += [
    # config.py lives at the repo root and is imported as a top-level module.
    "config",
    # /review/queue does `from vision.evidence import build_review_items`.
    # evidence.py is pure math -- it does NOT import torch, so this pulls in
    # nothing heavy. vision.segment / vision.detect are intentionally omitted.
    "vision",
    "vision.evidence",
    # uvicorn resolves these by string at runtime, so static analysis misses them.
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
]

# The frozen exe doubles as a Python runner for SUMO's own tools (see the
# re-exec guard in core/main.py __main__): demand generation launches
# randomTrips.py, which imports sumolib, which imports stdlib `xml.etree`.
# RoadTwin's own code uses lxml, so PyInstaller never collects stdlib xml on
# its own -- pull the whole xml package in so the tool can run inside api.exe.
hidden += collect_submodules("xml")

# Packaged P9 demo evidence (ADR-007: no live SAM in the frozen build). The
# review queue falls back to `_base/assets/benchmark/observations.json` when the
# active project has no vision output, so ship the verified P7 aerial+SAM result
# as STATIC evidence. This is what lets a judge run REVIEW -> ACCEPT on a clean
# install without the multi-GB vision environment. The 5.5 MB mosaic is left in
# the repo (not the exe) -- no endpoint serves it; only these three are read.
_demo = [
    ("assets/benchmark/observations.json", "assets/benchmark"),
    ("assets/benchmark/road_mask.geojson", "assets/benchmark"),
    ("assets/benchmark/source_manifest.json", "assets/benchmark"),
]

a = Analysis(
    ["core/main.py"],
    pathex=[SPECPATH],          # so `config` and `core.*` resolve at build time
    binaries=[],
    datas=_demo,                # + lxml and pyproj data come from their own hooks
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    # console=False leaves sys.stdout/sys.stderr as None unless the parent hands
    # us pipes, and uvicorn's logger writes to sys.stderr -- so the sidecar died
    # with exit 1 and no output when spawned without redirection. See the hook.
    runtime_hooks=["pyi_rth_stdio.py"],
    excludes=[
        # vision sidecar only -- see ADR-007
        "torch", "torchvision", "transformers",
        # dev-only tooling that must never reach the installer
        "pytest", "ruff", "PyInstaller",
        # notebook / plotting stacks pulled in transitively by nothing we ship
        "matplotlib", "IPython", "notebook", "tkinter",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="api",                 # -> dist/api.exe
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # No console window: this process is spawned by the Tauri shell, and a
    # black terminal flashing up behind the app looks broken to a user.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
