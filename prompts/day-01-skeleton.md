# DAY 1 — Walking skeleton + packaging proven

(Paste `prompts/master.md` first.)

---

Build the RoadTwin walking skeleton. **Vertical slice only — no product
features.** The goal today is an installed `.exe` that runs and a headless
script that produces real SUMO numbers.

Do these in order. Packaging comes first, deliberately: a packaging break found
on Day 5 ends the project.

## 1. Monorepo

```
roadtwin/
├── apps/desktop/          Tauri 2 + React + TypeScript + Vite
│   └── src-tauri/
├── core/                  (already present — do not rewrite)
├── vision/                (already present — do not rewrite)
├── scripts/               (already present)
├── context/               (already present)
├── assets/benchmark/
├── projects/
└── config.py              (already present)
```

`core/`, `vision/`, `scripts/` and `context/` already exist and are unit-tested.
**Read them before writing anything.** Your job is to build the app shell and
the FastAPI surface around them, not to reimplement them.

## 2. Core sidecar

Create `core/main.py`: a FastAPI app exposing `GET /health` returning
`{"status": "ok", "version": "...", "sumo": <bool>}` where `sumo` reports
whether `SUMO_HOME` resolves.

Runtime dependencies are **exactly**: `fastapi uvicorn pydantic requests lxml
numpy pillow`. Do not add anything else (ADR-011).

## 3. Freeze with PyInstaller

```
pyinstaller --onedir --name api --collect-all lxml core/main.py
```

Resolve hidden-import and data-file problems now, not later. Verify the frozen
binary runs standalone and serves `/health` before continuing.

## 4. Wire as a Tauri sidecar

Tauri requires the target-triple suffix:

```
apps/desktop/src-tauri/binaries/api-x86_64-pc-windows-msvc.exe
```

`tauri.conf.json`: `"bundle": { "externalBin": ["binaries/api"] }`

The frontend should start the sidecar, poll `/health`, and display the result.
That single round trip is today's UI.

## 5. Build AND INSTALL the installer

```
cd apps/desktop && npm run tauri build
```

Then **run the installer, install the app, launch the installed binary, and
confirm `/health` responds.** Building is not the same as installing — path
resolution differs between `python main.py`, the frozen binary and the
installed binary, and today is when you want to find that out.

## 6. Verify the headless spine

`scripts/run_benchmark.py` already implements the full pipeline. Run it:

```
python scripts/run_benchmark.py
```

It must complete and print real travel-time numbers. If it fails, fix the
cause — do not work around it.

## 7. Provenance

`core/provenance.py` already implements sha256 artifact tracking. Confirm
`projects/benchmark/provenance.json` is populated after the run.

---

## Verify before you claim completion

1. `python scripts/selftest.py` → 0 failed
2. `python scripts/verify_environment.py` → 0 FAIL
3. The **installed** `.exe` launches and `/health` responds
4. `python scripts/run_benchmark.py` prints real numbers and writes the ZIP

Then update `context/CURRENT_STATE.md`: mark the Day 1 items, record the exact
command that worked, and note anything broken.

## Do not

- add any product feature (no map, no location UI, no AI)
- add dependencies beyond the seven listed
- write an OpenDRIVE emitter
- claim completion without having installed and launched the installer
