import os, sys, pandas as pd
os.chdir(r"C:\Users\RossW\Projects\CAMARF"); sys.path.insert(0, ".")
from research.p2_share_class_family import family_by_year, CLASSIFICATION_CSV
n = pd.read_parquet("output/cache/wrds/crsp_stocknames_all.parquet")
m = pd.read_parquet("output/cache/wrds/full_us_market_label_map.parquet")
have = set(int(p) for p, l in zip(m["permno"], m["label"]) if pd.notna(p) and os.path.exists(f"output/cache/wrds/{l}_1D.parquet"))
fam = family_by_year(n, have, range(1990, 2025))
cls = pd.read_csv(CLASSIFICATION_CSV)
done = {(min(a, b), max(a, b)) for a, b in zip(cls.permno_a, cls.permno_b)}
yrs = {}
for y, prs in fam.items():
    for p in prs:
        yrs.setdefault(p, []).append(y)
print("pair-years ungated:", sum(len(v) for v in fam.values()), "unique pairs:", len(yrs), "already classified:", len(set(yrs) & done))
last = n.sort_values("nameenddt").groupby("permno").last()
rows = []
for (a, b), ys in sorted(yrs.items()):
    if (a, b) in done: continue
    rows.append(dict(permno_a=a, permno_b=b, ticker_a=last.ticker.get(a), ticker_b=last.ticker.get(b),
                     comnam=last.comnam.get(a), permco=last.permco.get(a), first_year=min(ys), last_year=max(ys), n_years=len(ys)))
r = pd.DataFrame(rows)
out = r"C:\Users\RossW\AppData\Local\Temp\claude\C--Users-RossW-Projects-CAMARF\4fa262c1-c604-4a14-a6a2-4fe2cfc8bf0e\scratchpad\p2_unclassified_pairs.csv"
r.to_csv(out, index=False)
print(len(r), "to classify;", r.n_years.sum(), "pair-years"); print(r.to_string(index=False))
