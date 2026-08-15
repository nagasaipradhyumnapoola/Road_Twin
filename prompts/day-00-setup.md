# DAY 0 — Environment and benchmark verification

(Paste `prompts/master.md` first.)

---

Day 0 is mostly manual — follow `SETUP.md` and `EXECUTION_PLAN.md` Day 0. Use
Claude Code only for the parts below.

## 1. Verify the environment

```
python scripts/verify_environment.py
python scripts/selftest.py
```

Both must report zero failures. If `verify_environment.py` reports a FAIL, fix
the underlying install — do not patch the checker to make it pass.

## 2. ★ Verify the benchmark location

This is the highest-leverage 45 minutes in the project. It protects Days 2, 3,
4 and 5 simultaneously.

Set the candidate coordinates in `config.py` `BENCHMARK`, then:

```
python scripts/run_benchmark.py --skip-sim
netedit projects/benchmark/sumo/network.net.xml
```

Confirm all of:

- [ ] the main road carries an OSM `lanes` tag
- [ ] at least one real junction sits inside the AOI
- [ ] junctions are **connected** in netedit (look, do not assume)
- [ ] at least one multi-lane edge ≥ 100 m for the closure experiment
- [ ] lane markings visible in satellite imagery at zoom 19

> **If any fail, change the location, not the plan.** Ten minutes of relocating
> beats two days of fighting bad source data.

## 3. If the location needs work

Ask Claude Code to help evaluate candidates:

```
Read config.py and core/acquire/overpass.py. For each of these candidate
coordinates, fetch the OSM extract, run netconvert, and report:
  - number of drivable edges and junctions
  - how many edges carry an explicit OSM `lanes` tag vs inferred
  - the longest multi-lane edge (id, lane count, length in metres)
  - any netconvert warnings suggesting disconnected geometry

Candidates:
  <lat1>, <lon1>
  <lat2>, <lon2>
  <lat3>, <lon3>

Do not modify any module. Report a table and recommend one.
```

## 4. Commit the demo insurance

```
git add assets/benchmark/osm_*.osm
git commit -m "cache benchmark OSM extract"
```

Overpass rate-limits and venue wifi fails. This file is the difference between
a demo and an apology.

## 5. Record the result

Fill in the verification block in `context/DEMO_SPEC.md` and the NEXT section
of `context/CURRENT_STATE.md`.

---

## Gate 0

```
✓ verify_environment.py    0 FAIL
✓ selftest.py              0 failed
✓ run_benchmark.py --skip-sim produces network.net.xml + road_network.xodr
✓ network looks correct in netedit
✓ benchmark OSM extract committed
```
