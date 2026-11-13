# Gated (headline) family results from the 3-arm placebo run's outputs (review finding 1): the gated pair-years are a
# subset of the ungated ones already tested on the same draws, so only BH is recomputed on the gated family per
# (seed, year, test). Run on CachyOS from the repo root after research/p2_placebo_power.py finished.
import os, sys, numpy as np, pandas as pd
sys.path.insert(0, "."); sys.path.insert(0, "research")
from p2_placebo_power import bh_bounds, families, summarize, OUT
from yearly_family_test import bh_reject
fams, _ = families("output/cache/wrds")
G = {(y, a, b) for y, v in fams["gated"].items() for a, b in v}
print("gated pair-years", len(G), "distinct pairs", len({(a, b) for _, a, b in G}))
N = pd.read_parquet(os.path.join(OUT, "p2_placebo_power_null.parquet"))
N = N[N.family == "ungated"].copy()
N = N[[(y, a, b) in G for y, a, b in zip(N.year, N.symbol_a, N.symbol_b)]].copy()
N["family"] = "gated"
N["rejected"] = False
for _, idx in N.groupby(["seed", "year", "test"]).groups.items():
    N.loc[idx, "rejected"] = bh_reject(N.loc[idx, "pvalue"].to_numpy(), 0.05)
P = pd.read_parquet(os.path.join(OUT, "p2_placebo_power_planted.parquet"))
P = P[P.family == "ungated"][["symbol_a", "symbol_b", "year", "seed", "half_life", "variant", "test", "pvalue"]]
B = bh_bounds(N, P)
S = summarize(N, B)
pd.set_option("display.width", 200)
print("testable gated pair-years per seed:", int(np.isfinite(N.pvalue).sum() / N.seed.nunique() / N.test.nunique()))
print(S["size"].round(4).to_string())
print(S["power"].xs("full", level="variant").round(3).to_string())
se = np.sqrt(0.05 * 0.95 / S["size"]["tests"])
print("within 3 SE of 0.05 at p<0.05:", ((S["size"]["p<0.05"] - 0.05).abs() <= 3 * se).to_dict())
N.to_parquet(os.path.join(OUT, "p2_placebo_power_null_gated.parquet")); B.to_parquet(os.path.join(OUT, "p2_placebo_power_planted_gated.parquet"))
