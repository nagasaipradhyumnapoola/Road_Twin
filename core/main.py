"""Core FastAPI sidecar — the only Python process the Tauri app talks to.

GET /health  → {"status": "ok", "version": "0.1.0", "sumo": <bool>}

Nothing else lives here. Routes for later phases (acquire, build, sim, etc.)
are added as routers in separate modules — this file stays thin.

Frozen binary path-resolution note:
  When frozen by PyInstaller, __file__ is inside a temp _MEIPASS directory.
  config.py reads ROOT from its own __file__, which works correctly in both
  the live and frozen environments because we add the repo root to sys.path
  before importing anything from core/.
"""
from __future__ import annotations

import sys
import os
from pathlib import Path

# ── path setup ────────────────────────────────────────────────────────────────
# When frozen, sys._MEIPASS is set to the extraction directory.
# We add both it and its parent so that `import config` always resolves.
if getattr(sys, "frozen", False):
    _base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
else:
    _base = Path(__file__).resolve().parent.parent

if str(_base) not in sys.path:
    sys.path.insert(0, str(_base))

# ── imports ───────────────────────────────────────────────────────────────────
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── version ───────────────────────────────────────────────────────────────────
__version__ = "0.1.0"

# ── app ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="RoadTwin Core API",
    version=__version__,
    description="Headless backend for the RoadTwin desktop application.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # Tauri WebView origin is app://localhost
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── models ────────────────────────────────────────────────────────────────────
class HealthResponse(BaseModel):
    status: str
    version: str
    sumo: bool
    sumo_home: str | None


# ── helpers ───────────────────────────────────────────────────────────────────
def _sumo_ok() -> tuple[bool, str | None]:
    """Return (True, path) if SUMO is locatable, else (False, None)."""
    try:
        from core.build.netconvert import sumo_home
        p = str(sumo_home())
        return True, p
    except Exception:
        return False, None


# ── routes ────────────────────────────────────────────────────────────────────
@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness + capability probe.

    Tauri polls this until it returns 200 before showing the main UI.
    The `sumo` field lets the frontend warn the user if SUMO is missing
    without crashing the whole app.
    """
    ok, path = _sumo_ok()
    return HealthResponse(status="ok", version=__version__, sumo=ok, sumo_home=path)


# ── entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("ROADTWIN_PORT", "8765"))
    uvicorn.run(
        "core.main:app",
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
