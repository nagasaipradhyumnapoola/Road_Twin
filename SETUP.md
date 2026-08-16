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

# 2. 78 Mathematical & Logic Unit Tests (No SUMO/network needed, ~2s)
python scripts/selftest.py

# 3. 14 API Endpoints & Replay Invariants Integration Test
python scripts/test_all_endpoints.py

# 4. Phase 8 Replay Audit Invariant Test
python scripts/test_phase8.py

# 5. Full Headless Benchmark Pipeline (Overpass -> netconvert -> SUMO simulation -> ZIP)
python scripts/run_benchmark.py --seeds 1 --offline

# 6. Vision Pipeline (Overhead Mosaic -> SAM 2.1 Segment -> Width Measurement)
.venv-vision\Scripts\python scripts/run_vision.py
```

---

## 6. Building Production Binary & Windows Installers

### Step A: Build Single-File Sidecar Binary (`dist/api.exe`)
```powershell
.venv\Scripts\activate
pyinstaller --clean -y api_onefile.spec
Copy-Item -Force dist\api.exe apps\desktop\src-tauri\binaries\api-x86_64-pc-windows-msvc.exe
```

### Step B: Build Tauri Desktop Installer (.msi + .exe)
```powershell
cd apps\desktop
npm run tauri build
```

Generated installer files:
- MSI: `apps\desktop\src-tauri\target\release\bundle\msi\RoadTwin_0.1.0_x64_en-US.msi`
- EXE: `apps\desktop\src-tauri\target\release\bundle\nsis\RoadTwin_0.1.0_x64-setup.exe`

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
| `SmartScreen Warning` | Unsigned binary heuristic | Click "More info" → "Run anyway" (expected for unsigned hackathon builds) |
