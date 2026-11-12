# Exploratory count: share-class pairs (same CRSP permco, both common shares shrcd 10/11, both with a WRDS 1D file),
# point-in-time at each year-end T using CRSP name-date ranges; each leg listed >= 2 years before T.
import os, itertools, pandas as pd
os.chdir(r"C:\Users\RossW\Projects\CAMARF")
n = pd.read_parquet("output/cache/wrds/crsp_stocknames_all.parquet")
m = pd.read_parquet("output/cache/wrds/full_us_market_label_map.parquet")
n["namedt"] = pd.to_datetime(n["namedt"]); n["nameenddt"] = pd.to_datetime(n["nameenddt"])
c = n[n["shrcd"].isin([10, 11])]
first = n.groupby("permno")["namedt"].min()
have = set(m["permno"].astype("Int64")[[os.path.exists(f"output/cache/wrds/{l}_1D.parquet") for l in m["label"]]])
print("permnos with a 1D file:", len(have))
rows = []
for y in range(1990, 2026):
    T = pd.Timestamp(f"{y}-12-31")
    a = c[(c.namedt <= T) & (c.nameenddt >= T)].drop_duplicates("permno")
    a = a[a.permno.isin(have) & (a.permno.map(first) <= T - pd.DateOffset(years=2))]
    g = a.groupby("permco")["permno"].apply(list)
    g = g[g.map(len) >= 2]
    pairs = sum(len(v) * (len(v) - 1) // 2 for v in g)
    rows.append((y, len(g), pairs))
r = pd.DataFrame(rows, columns=["year", "companies", "pairs"]); print(r.to_string(index=False))
T = pd.Timestamp("2024-12-31")
a = c[(c.namedt <= T) & (c.nameenddt >= T)].drop_duplicates("permno"); a = a[a.permno.isin(have)]
g = a.groupby("permco").filter(lambda d: len(d) >= 2).sort_values("permco")
print(g[["permco", "permno", "ticker", "comnam", "shrcd"]].head(40).to_string(index=False))
