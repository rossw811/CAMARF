# Which P2 family pair-years have a (near-)constant real log spread? Data diagnostic only (no test statistic).
import os, sys, numpy as np, pandas as pd
sys.path.insert(0, "."); sys.path.insert(0, "research")
import parquet_io
from p2_placebo_power import families
from placebo_discovery_e1 import _log_price
from yearly_family_test import MIN_BARS_SHARE
src = "output/cache/wrds"
fams, labels = families(src)
LP = {p: _log_price(parquet_io.read_parquet(os.path.join(src, f"{l}_1D.parquet"))) for p, l in labels.items()}
alld = pd.DatetimeIndex(sorted(set().union(*[s.index for s in LP.values()])))
kept = {(y, pr) for y, v in fams["kept"].items() for pr in v}
rows = []
for y, prs in fams["ungated"].items():
    cy = (alld.year == y).sum()
    for a, b in prs:
        j = pd.concat([LP[a][LP[a].index.year == y], LP[b][LP[b].index.year == y]], axis=1, join="inner").dropna()
        if len(j) < MIN_BARS_SHARE * cy or len(j) < 30:
            continue
        s = (j.iloc[:, 0] - j.iloc[:, 1]).to_numpy()
        ds = np.diff(s)
        rows.append({"year": y, "a": labels[a], "b": labels[b], "kept": (y, (a, b)) in kept, "n": len(s),
                     "sd": float(np.std(s)), "share_days_spread_unchanged": float(np.mean(np.abs(ds) < 1e-12))})
D = pd.DataFrame(rows)
print("pair-years tested:", len(D))
print("constant spread (sd < 1e-10):"); print(D[D.sd < 1e-10].to_string(index=False))
print("spread unchanged on >= 50% of days:"); print(D[D.share_days_spread_unchanged >= 0.5].sort_values("share_days_spread_unchanged", ascending=False).to_string(index=False))
print(D.share_days_spread_unchanged.describe().round(3).to_string())
