import os, sys, io, subprocess, pandas as pd
os.chdir(r"C:\Users\RossW\Projects\CAMARF"); sys.path.insert(0, ".")
from research.p2_share_class_family import family_by_year, apply_classification, CLASSIFICATION_CSV
old = pd.read_csv(io.StringIO(subprocess.run(["git", "show", f"HEAD:{CLASSIFICATION_CSV}"], capture_output=True, text=True, encoding="utf-8").stdout))
new = pd.read_csv(CLASSIFICATION_CSV)
m = old.merge(new, on=["permno_a", "permno_b"], suffixes=("_o", "_n"))
same = all((m[c + "_o"].astype(str) == m[c + "_n"].astype(str)).all() for c in old.columns if c not in ("permno_a", "permno_b"))
print("original 22 rows unchanged:", len(m) == len(old) == 22 and same)
n = pd.read_parquet("output/cache/wrds/crsp_stocknames_all.parquet")
lm = pd.read_parquet("output/cache/wrds/full_us_market_label_map.parquet")
have = set(int(p) for p, l in zip(lm["permno"], lm["label"]) if pd.notna(p) and os.path.exists(f"output/cache/wrds/{l}_1D.parquet"))
fam = family_by_year(n, have, range(1990, 2025))
kept, unc = apply_classification(fam, new)
tot = sum(map(len, fam.values())); k = sum(map(len, kept.values())); u = sum(map(len, unc.values()))
print(f"ungated pair-years {tot}; kept (same claim) {k}; unclassified {u}")
r = pd.DataFrame({"family": {y: len(v) for y, v in fam.items()}, "kept": {y: len(v) for y, v in kept.items()}})
r["decade"] = (r.index // 10) * 10
print(r.groupby("decade").sum().to_string())
print("unique kept pairs:", len({p for v in kept.values() for p in v}))
