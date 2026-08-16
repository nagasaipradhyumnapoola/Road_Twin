import sys; sys.path.insert(0, '.')
from core.sim.scenario import read_net_edges
from pathlib import Path

net = Path('projects/benchmark/build/network.net.xml')
edges = read_net_edges(net)

cands = [(eid, d) for eid, d in edges.items() if d['num_lanes'] >= 2]
cands.sort(key=lambda x: (x[1]['num_lanes'], x[1]['length_m']), reverse=True)
print(f'Total multi-lane edges: {len(cands)}')
print('--- Top 20 candidates ---')
for eid, d in cands[:20]:
    lanes = d['num_lanes']
    length = d['length_m']
    print(f'  {eid:<30}  lanes={lanes}  len={length:8.1f}m')

print()
print('--- 2-lane edges 100-600m (demo sweet spot) ---')
sweet = [(eid, d) for eid, d in edges.items() if d['num_lanes'] >= 2 and 100 <= d['length_m'] <= 600]
sweet.sort(key=lambda x: -x[1]['length_m'])
for eid, d in sweet[:15]:
    print(f'  {eid:<30}  lanes={d["num_lanes"]}  len={d["length_m"]:8.1f}m')
