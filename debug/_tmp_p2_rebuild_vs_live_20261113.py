# Real-data check (CachyOS, while E1 v2c seed 2's placebo cache exists): research/p2_placebo_power.rebuild_legs = the files
# build() wrote, for EVERY share-class family leg. Run from ~/CAMARF.
import os, sys, numpy as np
sys.path.insert(0, "."); sys.path.insert(0, "research")
import parquet_io
from p2_placebo_power import families, rebuild_legs
from placebo_discovery_e1 import _log_price
SEED = 20261025
live = os.path.expanduser("~/CAMARF_e1/output/cache/wrds")
fams, labels = families("output/cache/wrds")
LP = rebuild_legs("output/cache/wrds", labels, SEED)
worst, n, nofile = 0.0, 0, []
for p, lab in labels.items():
    g = os.path.join(live, f"{lab}_1D.parquet")
    if not os.path.exists(g):
        nofile.append((lab, len(LP[p]))); continue
    theirs = _log_price(parquet_io.read_parquet(g)); mine = LP[p]
    if not mine.index.equals(theirs.index):
        print("INDEX MISMATCH", lab); worst = np.inf; continue
    worst = max(worst, float(np.max(np.abs(mine.to_numpy() - theirs.to_numpy())))); n += 1
print(f"legs {len(labels)}; compared {n}; max |log price diff| {worst:.3e}; no live file {nofile}")
