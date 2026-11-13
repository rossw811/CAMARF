# Does replaying build()'s sampling reproduce the live E1 v2c placebo files exactly? Seed 20261025 (seed 2, files still on
# disk in ~/CAMARF_e1/output/cache/wrds). Legs: 40 random US share-class family legs + 10 random other US labels.
import os, glob, sys, numpy as np, pandas as pd, warnings; warnings.filterwarnings("ignore")
sys.path.insert(0, "."); sys.path.insert(0, "research")
import parquet_io, placebo_discovery_e1 as m
SEED, VERSION = 20261025, "v2c"
src = "output/cache/wrds"; live = os.path.expanduser("~/CAMARF_e1/output/cache/wrds")
files = sorted(glob.glob(os.path.join(src, "*_1D.parquet")))
rng = np.random.default_rng(SEED)
sample = rng.choice(files, size=min(800, len(files)), replace=False)
rets = pd.concat({os.path.basename(f): m._log_price(parquet_io.read_parquet(f)).diff() for f in sample}, axis=1)
cal = pd.DatetimeIndex(rets.index).sort_values(); cal = cal[cal.dayofweek < 5]
L = m.choose_block_length({c: rets[c] for c in rets.columns}); lam = m.choose_ewma_lambda({c: rets[c] for c in rets.columns})
paths = m.vol_matched_paths(cal, m.market_vol_state(rets.reindex(cal), lam), L, m.VOL_BINS, SEED, stress_once=True)
sp = m.source_positions(cal, paths)
print(f"block {L:.6f} lambda {lam:.6f} calendar {len(cal)}")
legs = [l.strip() for l in open("debug/_tmp_p2_placebo_repro_legs_20261113.txt") if l.strip()]  # run 2026-11-13 from /tmp copy
r_ = np.random.default_rng(7)
others = [os.path.basename(f)[:-11] for f in r_.choice(files, 10, replace=False)]
worst, n = 0.0, 0
for lab in legs + others:
    f = os.path.join(src, f"{lab}_1D.parquet"); g = os.path.join(live, f"{lab}_1D.parquet")
    if not (os.path.exists(f) and os.path.exists(g)):
        print("missing", lab); continue
    mine = m.placebo_series(m._log_price(parquet_io.read_parquet(f)), cal, paths, src_pos=sp)
    theirs = m._log_price(parquet_io.read_parquet(g))
    a, b = mine.align(theirs, join="outer")
    if not a.index.equals(mine.index) or a.isna().ne(b.isna()).any():
        print("INDEX MISMATCH", lab, len(mine), len(theirs)); worst = np.inf; continue
    d = float(np.nanmax(np.abs(a - b))); worst = max(worst, d); n += 1
print(f"compared {n} series; max |log price diff| {worst:.3e}")
