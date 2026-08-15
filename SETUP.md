# SETUP — Day 0 environment

Every failure here costs minutes now and hours later. Do it the evening before
Day 1.

---

## 1. Python 3.11 or 3.12

Not 3.13 — wheel coverage for some dependencies is still patchy.

```powershell
python --version
python -m venv .venv
.venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements-core.txt
```

## 2. SUMO — the one prerequisite you cannot skip

Download the Windows installer from
<https://sumo.dlr.de/docs/Downloads.php> and install it.

Then set `SUMO_HOME` **permanently**:

```powershell
setx SUMO_HOME "C:\Program Files (x86)\Eclipse\Sumo"
```

**Open a new terminal** (setx does not affect the current one) and verify:

```powershell
echo $env:SUMO_HOME
netconvert --version
sumo --version
python "$env:SUMO_HOME\tools\randomTrips.py" --help
```

All four must work. If `netconvert` is not found, add `%SUMO_HOME%\bin` to PATH.

Confirm the OSM typemap exists — without it netconvert applies weak lane and
speed defaults to Indian road classes and your baseline is junk:

```powershell
dir "$env:SUMO_HOME\data\typemap\osmNetconvert.typ.xml"
```

## 3. Node.js 20 LTS

```powershell
node --version
npm --version
```

## 4. Rust

```powershell
# https://rustup.rs
rustup default stable
cargo --version
```

## 5. Tauri prerequisites (Windows)

- **Microsoft C++ Build Tools 2022** — install the "Desktop development with
  C++" workload
- **WebView2 Runtime** — usually already present on Windows 11

```powershell
npm create tauri-app@latest
```

## 6. Vision environment — SEPARATE venv (ADR-007)

Keep `torch` out of the frozen core binary. This is what keeps the installer at
~300 MB instead of 3–5 GB.

```powershell
python -m venv .venv-vision
.venv-vision\Scripts\activate
pip install -r requirements-vision.txt
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

For a CUDA build, install torch from the PyTorch index for your CUDA version
before installing the rest.

Pre-download the model weights on the demo machine so the first run at the
venue is not a 900 MB download:

```python
from transformers import Sam2Model, Sam2Processor, AutoProcessor, AutoModelForZeroShotObjectDetection
Sam2Model.from_pretrained("facebook/sam2.1-hiera-small")
Sam2Processor.from_pretrained("facebook/sam2.1-hiera-small")
AutoProcessor.from_pretrained("IDEA-Research/grounding-dino-tiny")
AutoModelForZeroShotObjectDetection.from_pretrained("IDEA-Research/grounding-dino-tiny")
```

## 7. Tile provider

MapLibre ships no map data. Pick a provider whose terms permit your use, and
set the URL from the environment — never commit a key.

```powershell
$env:ROADTWIN_TILE_URL = "https://.../{z}/{x}/{y}.png"
```

Also update the `User-Agent` strings in `config.py` with a real contact address.

## 8. Verify

```powershell
python scripts/verify_environment.py    # must show 0 FAIL
python scripts/selftest.py              # must show 0 failed
```

## 9. PyInstaller (Day 1)

```powershell
pip install pyinstaller
pyinstaller --onedir --name api --collect-all lxml core\main.py
```

If a frozen import fails, add `--hidden-import <module>`. Resolve this on Day 1,
not Day 5.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `SUMO_HOME is not set` | `setx` needs a new shell | open a new terminal |
| `netconvert not found` | not on PATH | add `%SUMO_HOME%\bin` |
| netconvert produces an empty network | AOI has no drivable roads | widen `aoi_radius_m` or move the benchmark |
| junctions disconnected in netedit | bad source data | change the benchmark location |
| `shell.open is not a function` | Tauri v1 tutorial | use `tauri-plugin-opener` |
| Grounding DINO install compiles CUDA ops | using the IDEA-Research repo | use `transformers` instead |
| PyInstaller binary flagged by antivirus | unsigned heuristic | whitelist on the demo machine, days early |
| Overpass 429 | rate limited | use the cached extract in `assets/benchmark/` |
| Map is a grey rectangle | no tile source configured | set a style/tile URL |
