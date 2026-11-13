# Redo of debug/_tmp_p2_adv_gate_20261112.py with the BUG-D117 verified PERMNO -> file map (permno_labels / leg_label).
# Share-class family per year-end before / after the discovery ADV gate ($25M adv_at Dec 31, BOTH legs), then classified.
# Run from the repo root on CachyOS (authoritative cache).
import os, sys, pandas as pd
sys.path.insert(0, "."); sys.path.insert(0, "research")
import parquet_io
from config import Config
from p2_share_class_family import family_by_year, apply_classification, permno_labels, leg_label, CLASSIFICATION_CSV
from rolling_adv_comparison import rolling_adv, adv_at
src = "output/cache/wrds"
n = parquet_io.read_parquet(f"{src}/crsp_stocknames_all.parquet")
by_p = permno_labels(src)
F = family_by_year(n, set(by_p), range(1990, 2025))
need = sorted({p for v in F.values() for pr in v for p in pr})
lab = {p: leg_label(src, by_p[p]) for p in need}
ADV = {p: rolling_adv(parquet_io.read_parquet(f"{src}/{lab[p]}_1D.parquet")) for p in need}
thr = Config.STATS.ADV_FILTER_USD
G = {y: [pr for pr in prs if all(adv_at(ADV[p], pd.Timestamp(f"{y}-12-31")) >= thr for p in pr)] for y, prs in F.items()}
print("family per year:", " ".join(f"{y}:{len(F[y])}" for y in sorted(F)))
print("after ADV gate :", " ".join(f"{y}:{len(G[y])}" for y in sorted(G)), "| total", sum(map(len, G.values())))
K, UN = apply_classification(G, pd.read_csv(CLASSIFICATION_CSV))
print("gated + classified kept:", " ".join(f"{y}:{len(K[y])}" for y in sorted(K)))
print("pair-years kept", sum(map(len, K.values())), "unclassified", sum(map(len, UN.values())),
      "distinct kept pairs", len({p for v in K.values() for p in v}))
print("kept pairs:", sorted({(lab[a], lab[b]) for v in K.values() for a, b in v}))
