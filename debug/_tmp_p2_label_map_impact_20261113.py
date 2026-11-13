# P2 family under the BUG-D117 content-verified map (data_wrds.label_permno_map) vs the old full_us_market_label_map, on
# the cache this runs against (run on CachyOS: the authoritative cache). Data diagnostic only, no test statistic.
import os, sys, numpy as np, pandas as pd
sys.path.insert(0, "."); sys.path.insert(0, "research")
import parquet_io
from data_wrds import label_permno_map
from p2_share_class_family import family_by_year, apply_classification, CLASSIFICATION_CSV
from placebo_discovery_e1 import _log_price
src = "output/cache/wrds"
n = parquet_io.read_parquet(os.path.join(src, "crsp_stocknames_all.parquet"))
cls = pd.read_csv(CLASSIFICATION_CSV)
new = label_permno_map()
by_p = {}
for l, p in new.items():
    if os.path.exists(os.path.join(src, f"{l}_1D.parquet")):
        by_p.setdefault(p, []).append(l)
multi = {p: ls for p, ls in by_p.items() if len(ls) > 1}
print(f"final map: {len(new)} labels; permnos with a 1D file {len(by_p)}; permnos with >1 file label {len(multi)}")
old = parquet_io.read_parquet(os.path.join(src, "full_us_market_label_map.parquet")).dropna(subset=["permno"])
old_p2l = dict(zip(old["permno"].astype(int), old["label"]))
have_old = {p for p, l in old_p2l.items() if os.path.exists(os.path.join(src, f"{l}_1D.parquet"))}
have_new = set(by_p)
Y = range(1990, 2025)
fo, fn = family_by_year(n, have_old, Y), family_by_year(n, have_new, Y)
po = {pr for v in fo.values() for pr in v}; pn = {pr for v in fn.values() for pr in v}
print(f"pairs old {len(po)}, new {len(pn)}; only old {len(po - pn)}, only new {len(pn - po)}")
print(f"pair-years old {sum(map(len, fo.values()))}, new {sum(map(len, fn.values()))}")
known = set(zip(cls.permno_a, cls.permno_b))
print("new-map pairs not in the classification file:", sorted(pn - known))
print("classified pairs absent under the new map:", sorted(po - pn))
legs = {x for pr in pn for x in pr}
print("family legs with >1 file label:", {p: by_p[p] for p in legs if p in multi})
moved = {p: (old_p2l.get(p), by_p[p]) for p in legs if old_p2l.get(p) not in by_p[p]}
print(f"family legs whose file label differs old -> new: {len(moved)}"); print(moved)
# duplicate-content legs under the new map: identical close series within a pair
kept, unc = apply_classification(fn, cls[cls.set_index(["permno_a", "permno_b"]).index.isin(list(pn))])
dups = []
for a, b in sorted(pn):
    la, lb = by_p[a][0], by_p[b][0]
    A, B = _log_price(parquet_io.read_parquet(f"{src}/{la}_1D.parquet")), _log_price(parquet_io.read_parquet(f"{src}/{lb}_1D.parquet"))
    j = pd.concat([A, B], axis=1, join="inner").dropna()
    if len(j) > 30 and float((j.iloc[:, 0] - j.iloc[:, 1]).diff().abs().max()) < 1e-12:
        dups.append((a, b, la, lb, len(j)))
print("pairs with identical returns on every common day (new map):", dups)
