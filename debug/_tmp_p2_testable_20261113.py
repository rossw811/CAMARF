# How many P2 family pair-years are testable (both legs on >= MIN_BARS_SHARE of the year's days, >= 30 bars) -- coverage
# only, no test statistic computed. Kept (same-claim) family and full ungated family.
import os, sys, numpy as np, pandas as pd
os.chdir(r"C:\Users\RossW\Projects\CAMARF"); sys.path.insert(0, "."); sys.path.insert(0, "research")
from p2_share_class_family import family_by_year, apply_classification, CLASSIFICATION_CSV
from yearly_family_test import MIN_BARS_SHARE
from placebo_discovery_e1 import _log_price
import parquet_io
n = pd.read_parquet("output/cache/wrds/crsp_stocknames_all.parquet")
lm = pd.read_parquet("output/cache/wrds/full_us_market_label_map.parquet").dropna(subset=["permno"])
p2l = dict(zip(lm["permno"].astype(int), lm["label"]))
have = set(p for p, l in p2l.items() if os.path.exists(f"output/cache/wrds/{l}_1D.parquet"))
fam = family_by_year(n, have, range(1990, 2025))
kept, _ = apply_classification(fam, pd.read_csv(CLASSIFICATION_CSV))
legs = {x for v in fam.values() for pr in v for x in pr}
LP = {p: _log_price(parquet_io.read_parquet(f"output/cache/wrds/{p2l[p]}_1D.parquet")) for p in legs}
alld = pd.DatetimeIndex(sorted(set().union(*[s.index for s in LP.values()])))
def testable(F):
    out = {}
    for y, prs in F.items():
        cy = (alld.year == y).sum(); k = 0
        for a, b in prs:
            j = pd.concat([LP[a][LP[a].index.year == y], LP[b][LP[b].index.year == y]], axis=1, join="inner").dropna()
            k += len(j) >= MIN_BARS_SHARE * cy and len(j) >= 30
        out[y] = (len(prs), k)
    return pd.DataFrame(out, index=["family", "testable"]).T
for nm, F in (("ungated", fam), ("kept", kept)):
    T = testable(F); T["decade"] = (T.index // 10) * 10
    print(nm, "total", T[["family", "testable"]].sum().to_dict())
    print(T.groupby("decade")[["family", "testable"]].sum().to_string())
    print("per-year testable min/median/max", int(T.testable.min()), float(T.testable.median()), int(T.testable.max()))
print("legs with no usable price at all:", sum(len(s) == 0 for s in LP.values()), "of", len(LP))
