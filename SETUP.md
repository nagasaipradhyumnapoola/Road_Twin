# SETUP — Team Installation & Reproduction Guide

Complete step-by-step setup guide. Every dependency, toolchain, and command used across Phases 0 through 9 is documented here so any team member on a fresh Windows 10/11 machine can reproduce the build.

---

## 1. Automated Toolchain Installation (Winget)

Run in an Administrator PowerShell prompt:

```powershell
# 1. SUMO Traffic Simulation Suite
winget install Eclipse.SUMO --accept-source-agreements --accept-package-agreements

# 2. Rust & Cargo Toolchain
winget install Rustlang.Rustup --accept-source-agreements --accept-package-agreements

# 3. Node.js 20+ LTS
winget install OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements

# 4. Microsoft Visual C++ 2022 Build Tools (Required for Tauri native compilation)
winget install Microsoft.VisualStudio.2022.BuildTools --accept-source-agreements --accept-package-agreements --override "--passive --config vs.config --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
```

---

## 2. Environment Variables Configuration

Set `SUMO_HOME` and update system `PATH` permanently:

```powershell
# Set SUMO_HOME
setx SUMO_HOME "C:\Program Files (x86)\Eclipse\Sumo"

# Add SUMO bin and tools to PATH (User level)
$oldPath = [Environment]::GetEnvironmentVariable("Path", "User")
$sumoBin = "C:\Program Files (x86)\Eclipse\Sumo\bin"
if ($oldPath -notlike "*$sumoBin*") {
    [Environment]::SetEnvironmentVariable("Path", "$oldPath;$sumoBin", "User")
}
```

**Restart your PowerShell terminal** and verify:
```powershell
echo $env:SUMO_HOME
netconvert --version
sumo --version
python "$env:SUMO_HOME\tools\randomTrips.py" --help
```

---

## 3. Python Virtual Environments Setup

We use **two isolated virtual environments** (ADR-007):

### A. Core Engine Environment (`.venv`)
Contains FastAPI, netconvert wrappers, simulation, and export utilities. Kept lightweight (~30 MB) for PyInstaller bundling:

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements-core.txt
pip install pyinstaller
```

### B. Vision AI Environment (`.venv-vision`)
Contains PyTorch, torchvision, HuggingFace transformers for SAM 2.1 zero-shot segmentation:

```powershell
python -m venv .venv-vision
.venv-vision\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements-vision.txt
```

---

## 4. Frontend & Tauri Desktop Setup

Install Node dependencies in `apps/desktop`:

```powershell
cd apps\desktop
npm install
npm run build
cd ..\..
```

---

## 5. Verification & Testing Commands

Run all verification suites in order:

```powershell
# 1. Environment Health Check (checks SUMO, tools, cache)
python scripts/verify_environment.py

# 2. 112 Mathematical & Logic Unit Tests (No SUMO/network needed, ~2s)
python scripts/selftest.py

# 3. 14 API Endpoints & Replay Invariants Integration Test
python scripts/test_all_endpoints.py

# 4. Phase 8 Replay Audit Invariant Test
python scripts/test_phase8.py

# 5. Full Headless Benchmark (Overpass -> netconvert -> SUMO -> ZIP)
python scripts/run_benchmark.py

# 5b. SMOKE TEST ONLY -- one seed, ~10 s. Proves the pipeline runs end to end.
#     It is NOT a benchmark: a single run has no spread, so run_benchmark
#     refuses any significance claim and exits non-zero by design. Never quote
#     its numbers.
python scripts/run_benchmark.py --seeds 1 --offline

# 6. Vision Pipeline (Overhead Mosaic -> SAM 2.1 Segment -> Width Measurement)
.venv-vision\Scripts\python scripts/run_vision.py
```

---

## 6. Building Production Binary & Windows Installers

Works from a clean checkout. Every command below was run end-to-end on
2026-08-18; nothing here is untested.

### Step 0: Put Rust on PATH for this shell

`rustup` installs to `%USERPROFILE%\.cargo\bin`, which is **not** always on PATH
in a fresh terminal. Both `scripts/build_sidecar.py` (it reads the target triple
from `rustc`) and `npm run tauri build` need it:

```powershell
$env:PATH = "$env:USERPROFILE\.cargo\bin;$env:PATH"
rustc --version    # expect 1.97.x
```

### Step A: Build the single-file sidecar and stage it for Tauri

```powershell
.venv\Scripts\activate
python scripts\build_sidecar.py
```

That one command does both halves of what used to be a manual, undocumented
copy:

1. `pyinstaller --clean -y api_onefile.spec`  →  `dist\api.exe` (~37 MB)
2. copies it to `apps\desktop\src-tauri\binaries\api-<target-triple>.exe`

The triple suffix is **mandatory** — `tauri.conf.json` declares
`externalBin: ["binaries/api"]`, and Tauri resolves that to
`binaries\api-x86_64-pc-windows-msvc.exe`. Skip this step and the Tauri build
fails with:

```
resource path `binaries\api-x86_64-pc-windows-msvc.exe` doesn't exist
```

`api_onefile.spec` is tracked in git; the generated `.exe` is not, because it is
reproducible from the spec.

To re-stage an already-built exe without re-freezing:
`python scripts\build_sidecar.py --skip-build`

### Step B: Build Tauri Desktop Installer (.msi + .exe)
```powershell
cd apps\desktop
npm run tauri build
```

Expect ~165 s on a cold Rust build. First run also downloads the WiX and NSIS
toolchains automatically.

Generated files (verified):
- App:  `apps\desktop\src-tauri\target\release\app.exe` (12.6 MB, with `api.exe` staged beside it)
- MSI:  `apps\desktop\src-tauri\target\release\bundle\msi\RoadTwin_0.1.0_x64_en-US.msi` (41.1 MB)
- NSIS: `apps\desktop\src-tauri\target\release\bundle\nsis\RoadTwin_0.1.0_x64-setup.exe` (39.7 MB)

### Verifying the sidecar on its own

The frozen sidecar can be exercised without Tauri:

```powershell
$env:ROADTWIN_PORT = "8765"
.\dist\api.exe
# then, in another terminal:
curl http://127.0.0.1:8765/health
```

Expected:
```json
{"status":"ok","version":"0.2.0","sumo":true,"sumo_home":"C:\\Program Files (x86)\\Eclipse\\Sumo"}
```

---

## 7. Running Development Desktop App

```powershell
cd apps\desktop
npm run tauri dev
```

---

## 8. Troubleshooting Common Issues

| Problem | Cause | Solution |
|---|---|---|
| `SUMO_HOME is not set` | Environment variable not refreshed | Restart terminal or run `$env:SUMO_HOME = "C:\Program Files (x86)\Eclipse\Sumo"` |
| `netconvert not found` | SUMO bin directory not in PATH | Run `netconvert` via absolute path or add to PATH |
| `opener:default capability missing` | Tauri 2 permissions mismatch | Verify `capabilities/default.json` contains `"opener:default"` in `permissions` |
| `Overpass HTTP 429` | Public Overpass rate limit | Use `--offline` flag; cached extract in `assets/benchmark/` is used |
| ``resource path `binaries\api-...exe` doesn't exist`` | Sidecar not built/staged | Run `python scripts\build_sidecar.py` before `npm run tauri build` |
| `rustc not found on PATH` from `build_sidecar.py` | rustup dir not on PATH | `$env:PATH = "$env:USERPROFILE\.cargo\bin;$env:PATH"` |
| `dist\api.exe` exits with code 1 and no output | Windowed build had no stdout/stderr | Fixed by `pyi_rth_stdio.py` runtime hook; rebuild via `build_sidecar.py` |
| `SmartScreen Warning` | Unsigned binary heuristic | Click "More info" → "Run anyway" (expected for unsigned hackathon builds) |
