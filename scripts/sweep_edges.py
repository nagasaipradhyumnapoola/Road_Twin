import sys
from pathlib import Path
sys.path.insert(0, ".")

import config as C
from scripts.calibrate_demand import build_network, calibrate_period
from core.sim.scenario import read_net_edges

_, net_file = build_network()
edges = read_net_edges(net_file)

candidates = [
    ("568057022#0", 3),  # 682m, 4 lanes
    ("95222417#0", 3),   # 476m, 4 lanes
    ("47572742#3", 3),   # 363m, 4 lanes
    ("95222417#1", 3),   # 296m, 4 lanes
]

periods = [2.5, 2.0, 1.5, 1.2, 1.0, 0.8]

print(f"{'EDGE':<16} {'PERIOD':>7} {'VEH':>5} {'BASE_TT':>8} {'CLOS_TT':>8} {'DELTA%':>8} {'QUEUE_BASE':>10} {'QUEUE_CLOS':>10} {'TELEPORT':>8}", flush=True)
print("-" * 95, flush=True)

for eid, lane in candidates:
    if eid not in edges:
        continue
    for p in periods:
        try:
            r = calibrate_period(net_file, eid, lane, p, seed=42)
            base_tt = f"{r['base_tt_s']:.1f}s" if r['base_tt_s'] else "-"
            clos_tt = f"{r['clos_tt_s']:.1f}s" if r['clos_tt_s'] else "-"
            delta = f"{r['delta_pct']:+.1f}%" if r['delta_pct'] is not None else "-"
            tele = "YES" if r['has_teleports'] else "no"
            
            # Queue metrics
            cmp_rows = {row['metric']: row for row in r.get('desc', {}).get('table', '')} if isinstance(r.get('table'), dict) else {}
            
            print(f"{eid:<16} {p:7.1f} {r['veh_count']:5d} {base_tt:>8} {clos_tt:>8} {delta:>8} {tele:>8}", flush=True)
            
            if r['delta_pct'] is not None and 15.0 <= r['delta_pct'] <= 70.0 and not r['has_teleports']:
                print(f"===> MATCH FOUND: {eid} @ period={p} -> delta={delta}, teleports={tele}", flush=True)
                print(r['table'], flush=True)
        except Exception as e:
            print(f"{eid:<16} {p:7.1f} ERROR: {e}", flush=True)
