#!/usr/bin/env python3
"""Build the frozen core sidecar and place it where Tauri expects it.

    python scripts/build_sidecar.py

Two steps, both of which used to live only in SETUP.md prose:

    1. pyinstaller --clean -y api_onefile.spec      ->  dist/api.exe
    2. copy to  apps/desktop/src-tauri/binaries/api-<target-triple>.exe

Step 2 is why `npm run tauri build` failed before this script existed.
`tauri.conf.json` declares `externalBin: ["binaries/api"]`, and Tauri resolves
that to `binaries/api-<target-triple>.exe`. Get the triple wrong -- or skip the
copy -- and the build dies with:

    resource path `binaries\\api-x86_64-pc-windows-msvc.exe` doesn't exist

The triple is read from `rustc -vV` rather than hardcoded, so this keeps working
on a different host triple.

Run this BEFORE `npm run tauri build`.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "api_onefile.spec"
BUILT = ROOT / "dist" / "api.exe"
BIN_DIR = ROOT / "apps" / "desktop" / "src-tauri" / "binaries"


def target_triple() -> str:
    """Ask rustc for the host triple. Tauri names sidecars after it."""
    exe = shutil.which("rustc")
    if not exe:
        cargo_bin = Path.home() / ".cargo" / "bin" / "rustc.exe"
        if cargo_bin.exists():
            exe = str(cargo_bin)
    if not exe:
        raise RuntimeError(
            "rustc not found on PATH. Install the Rust toolchain (rustup) and "
            "make sure ~/.cargo/bin is on PATH -- `npm run tauri build` needs "
            "it too."
        )
    out = subprocess.run([exe, "-vV"], capture_output=True, text=True, check=True)
    for line in out.stdout.splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError(f"could not read host triple from `rustc -vV`:\n{out.stdout}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-build", action="store_true",
                    help="only copy an existing dist/api.exe into place")
    args = ap.parse_args()

    if not args.skip_build:
        if not SPEC.exists():
            print(f"FATAL: {SPEC.name} is missing. It is tracked in git -- "
                  "restore it before building.")
            return 2
        print(f"[sidecar] pyinstaller --clean -y {SPEC.name}")
        proc = subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--clean", "-y", str(SPEC)],
            cwd=ROOT,
        )
        if proc.returncode != 0:
            print(f"FATAL: PyInstaller failed (exit {proc.returncode})")
            return proc.returncode

    if not BUILT.exists():
        print(f"FATAL: {BUILT} was not produced.")
        return 2

    triple = target_triple()
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    dest = BIN_DIR / f"api-{triple}.exe"
    shutil.copy2(BUILT, dest)

    print(f"[sidecar] {BUILT.relative_to(ROOT)}  ->  {dest.relative_to(ROOT)}")
    print(f"[sidecar] {dest.stat().st_size / 1_048_576:.1f} MB")
    print("[sidecar] ready. Next:  cd apps/desktop && npm run tauri build")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
