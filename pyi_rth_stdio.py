"""PyInstaller runtime hook: guarantee sys.stdout / sys.stderr exist.

A windowed build (console=False) has no console attached, so CPython sets
sys.stdout and sys.stderr to None whenever the parent did not hand us real
pipes. uvicorn's default logging config then does the equivalent of
StreamHandler(sys.stderr) and dies before the server ever binds -- the sidecar
exits 1 with no output at all, which is precisely the failure that is hardest
to diagnose in a shipped installer.

Reproduced during the P1 repair:
    Start-Process dist\\api.exe                      -> exit code 1
    Start-Process dist\\api.exe -RedirectStandard*   -> serves /health 200

Tauri's shell plugin does create pipes, so the primary sidecar path is fine;
the bare std::process::Command fallback in src-tauri/src/lib.rs does not, and
neither does a user double-clicking the exe. Binding the missing handles to
os.devnull costs nothing and removes the whole failure class.

Real pipes are left untouched, so logs still reach Tauri when it supplies them.
"""
import os
import sys

for _name in ("stdout", "stderr"):
    if getattr(sys, _name, None) is None:
        try:
            setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))
        except OSError:
            pass
