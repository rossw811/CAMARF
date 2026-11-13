# E1 V6 open item 2 (2026-11-11): is the large seed-to-seed variation of the v2 placebo's far tail explained by how often
# each seed's shared day paths draw the extreme market days? Replays build()'s sampling (pinned v2c file list; the v2
# builds also had 46,218 files -- mean block checked against v2's recorded 3.50 / 3.75 / 3.55). Extreme day = top 1% /
# top 0.2% of calendar days by the cross-sectional median |return| of the 800-file sample. Also v2c (stress bin once).
# Run on CachyOS from the repo root.
import sys, numpy as np, pandas as pd
sys.path.insert(0, "."); sys.path.insert(0, "research")
import placebo_discovery_e1 as m
from p2_placebo_power import manifest_files
files = manifest_files("output/cache/wrds")
TAIL = {20261024: 0.00059, 20261025: 0.00064, 20261026: 0.00012}   # v2 US placebo p<1e-4 rate (Development.md V1)
rows = []
for version in ("v2", "v2c"):
    for seed in (20261024, 20261025, 20261026):
        rng = np.random.default_rng(seed)
        sample = rng.choice(files, size=800, replace=False)
        rng = np.random.default_rng(seed)
        cal, L, lam, vol_lam, paths, src = m.sample_paths(files, rng, seed, version)
        rets = pd.concat({f: m._log_price(pd.read_parquet(f)).diff() for f in sample}, axis=1).reindex(cal)
        move = rets.abs().median(axis=1, skipna=True).to_numpy()
        r = {"version": version, "seed": seed, "mean_block": round(L, 4)}
        for q, nm in ((0.99, "top1pct"), (0.998, "top02pct")):
            top = np.flatnonzero(move >= np.nanquantile(move, q))
            cnt = np.bincount(src, minlength=len(cal))[top]
            r[f"{nm}_draws_per_day"] = round(float(cnt.mean()), 3)        # 1.0 = drawn as often as in history
            r[f"{nm}_never_drawn"] = round(float((cnt == 0).mean()), 3)
            r[f"{nm}_max"] = int(cnt.max())
        r["us_tail_1e-4"] = TAIL.get(seed) if version == "v2" else None
        rows.append(r); print(r, flush=True)
print(pd.DataFrame(rows).to_string(index=False))
