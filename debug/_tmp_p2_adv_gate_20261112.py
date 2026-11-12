# Share-class family per year-end, before and after the discovery ADV gate ($25M, adv_at on Dec 31 for BOTH legs).
import os, sys, pandas as pd, numpy as np
os.chdir(r"C:\Users\RossW\Projects\CAMARF"); sys.path.insert(0, "."); sys.path.insert(0, "research")
import parquet_io
from config import Config
from p2_share_class_family import family_by_year
from rolling_adv_comparison import rolling_adv, adv_at
n = parquet_io.read_parquet("output/cache/wrds/crsp_stocknames_all.parquet")
m = parquet_io.read_parquet("output/cache/wrds/full_us_market_label_map.parquet")
m = m[[os.path.exists(f"output/cache/wrds/{l}_1D.parquet") for l in m["label"]]]
lab = dict(zip(m["permno"].astype(int), m["label"]))
F = family_by_year(n, lab.keys(), range(1990, 2025))
need = sorted({p for v in F.values() for pr in v for p in pr}); print("securities", len(need))
ADV = {p: rolling_adv(parquet_io.read_parquet(f"output/cache/wrds/{lab[p]}_1D.parquet")) for p in need}
thr = Config.STATS.ADV_FILTER_USD
rows = []
for y, prs in F.items():
    T = pd.Timestamp(f"{y}-12-31")
    ok = [pr for pr in prs if all(adv_at(ADV[p], T) >= thr for p in pr)]
    rows.append((y, len(prs), len(ok), ", ".join(f"{lab[a]}/{lab[b]}" for a, b in ok[:6])))
R = pd.DataFrame(rows, columns=["year", "family", "after_adv_gate", "examples"])
print(R.to_string(index=False)); print("total pair-years after gate:", R.after_adv_gate.sum())
nm = n.sort_values("nameenddt").groupby("permno").last()
D = {}
for y, prs in F.items():
    T = pd.Timestamp(f"{y}-12-31")
    for a, b in prs:
        if all(adv_at(ADV[p], T) >= thr for p in (a, b)):
            D.setdefault((a, b), []).append(y)
rows = []
for (a, b), ys in sorted(D.items(), key=lambda kv: kv[1][0]):
    rows.append({"permno_a": a, "permno_b": b, "label_a": lab[a], "label_b": lab[b],
                 "ticker_a": nm.loc[a, "ticker"], "ticker_b": nm.loc[b, "ticker"], "comnam": nm.loc[a, "comnam"],
                 "ncusip_a": nm.loc[a, "ncusip"], "ncusip_b": nm.loc[b, "ncusip"], "years": f"{ys[0]}-{ys[-1]}", "n_years": len(ys)})
U = pd.DataFrame(rows); U.to_csv(r"research\p2_gated_pairs_20261112.csv", index=False)
print(len(U), "distinct gated pairs"); print(U.drop(columns=["label_a","label_b"]).to_string(index=False))
from p2_share_class_family import apply_classification, CLASSIFICATION_CSV
G = {y: [pr for pr in prs if all(adv_at(ADV[p], pd.Timestamp(f"{y}-12-31")) >= thr for p in pr)] for y, prs in F.items()}
K, UN = apply_classification(G, pd.read_csv(CLASSIFICATION_CSV))
print("FINAL year: kept (unclassified)")
print(" ".join(f"{y}:{len(K[y])}" + (f"({len(UN[y])})" if UN[y] else "") for y in sorted(K)))
print("pair-years kept", sum(map(len, K.values())), "unclassified", sum(map(len, UN.values())))
