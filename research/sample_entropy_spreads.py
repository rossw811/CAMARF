"""
CAMARF sample_entropy_spreads.py — research/comparison script, NOT part
of the production pipeline.

Computes Sample Entropy (SampEn) for each confirmed pair's spread series.
SampEn measures the regularity/complexity of a time series:
  - Low SampEn → more regular, predictable, favorable for stat-arb
  - High SampEn → more random/complex, unfavorable

Algorithm (Richman & Moorman 2000):
  For embedding dimension m=2 and tolerance r=0.2*std(u):
    B = count of m-length template pairs within Chebyshev distance r
    A = count of (m+1)-length template pairs within Chebyshev distance r
    SampEn = -ln(A/B)

The spread is computed using the OLS hedge ratio from pairs.parquet:
  spread = close_A - hedge_ratio_ols * close_B
Then z-scored: (spread - spread.mean()) / spread.std()

Results are saved to output/research/sample_entropy_spreads.parquet.
Each row has: tf, symbol_a, symbol_b, sampen, n_bars, half_life
These become candidate ml.py Stage 2 features (lower SampEn → pair is
more mechanically predictable → higher confidence entry signal).

Usage:
    python research/sample_entropy_spreads.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aligned_pair_loader import load_aligned_pair
from data import _clean_close

_OUT = "output/research/sample_entropy_spreads.parquet"
_TF_DIRS = [
    ("1min", "1m"), ("2min", "2m"), ("3min", "3m"), ("5min", "5m"),
    ("15min", "15m"), ("30min", "30m"), ("1hr", "1h"), ("4hr", "4h"),
]


def _sample_entropy(u, m=2, r_scale=0.2):
    """
    Sample entropy of 1-D array u.
    r = r_scale * std(u). Returns NaN if computation is not possible.
    """
    u = u[np.isfinite(u)]
    n = len(u)
    if n < 4 * m:
        return np.nan
    r = r_scale * float(np.std(u, ddof=1))
    if r < 1e-12:
        return np.nan

    # Count template matches using vectorized Chebyshev distance
    def _count_matches(length):
        count = 0
        templates = np.array([u[i:i + length] for i in range(n - length)])
        for i in range(len(templates)):
            diffs = np.max(np.abs(templates - templates[i]), axis=1)
            # Exclude self-match (i==i) per SampEn definition
            count += np.sum(diffs < r) - 1
        return count

    B = _count_matches(m)
    A = _count_matches(m + 1)

    if B == 0 or A == 0:
        return np.nan
    return float(-np.log(A / B))


def main():
    rows = []
    for tf_dir, tf_label in _TF_DIRS:
        path = f"output/results/{tf_dir}/pairs.parquet"
        if not os.path.exists(path):
            continue
        pairs = pd.read_parquet(path)
        for _, row in pairs.iterrows():
            sym_a, sym_b = row["symbol_a"], row["symbol_b"]
            hedge = float(row.get("hedge_ratio_ols", np.nan))
            half_life = float(row.get("half_life_rolling", np.nan))
            if not np.isfinite(hedge):
                print(f"SKIP {sym_a}/{sym_b}@{tf_label}: no valid hedge ratio")
                continue

            df_a, df_b = load_aligned_pair(sym_a, sym_b, tf_label)
            if df_a is None or df_b is None:
                print(f"SKIP {sym_a}/{sym_b}@{tf_label}: cache missing")
                continue

            close_a = pd.Series(_clean_close(df_a), index=df_a.index, name="a")
            close_b = pd.Series(_clean_close(df_b), index=df_b.index, name="b")
            combined = pd.concat([close_a, close_b], axis=1).dropna()
            if len(combined) < 100:
                print(f"SKIP {sym_a}/{sym_b}@{tf_label}: only {len(combined)} bars")
                continue

            spread = combined["a"] - hedge * combined["b"]
            spread_std = float(spread.std())
            if spread_std < 1e-8:
                print(f"SKIP {sym_a}/{sym_b}@{tf_label}: zero-variance spread")
                continue
            spread_z = ((spread - spread.mean()) / spread_std).values

            se = _sample_entropy(spread_z, m=2, r_scale=0.2)
            print(f"  {sym_a}/{sym_b}@{tf_label}  SampEn={se:.4f}  "
                  f"hl={half_life:.1f}  n={len(spread_z)}")

            rows.append({
                "tf": tf_label, "symbol_a": sym_a, "symbol_b": sym_b,
                "sample_entropy": se,
                "half_life": half_life,
                "n_bars": len(spread_z),
                "spread_std": spread_std,
            })

    if not rows:
        print("No results — are there pairs.parquet files in output/results/?")
        return

    out = pd.DataFrame(rows).sort_values(["tf", "sample_entropy"])

    print(f"\n--- Sample Entropy Summary ---")
    print(f"N pairs: {len(out)}")
    for tf, grp in out.groupby("tf"):
        print(f"  {tf}: mean SampEn={grp['sample_entropy'].mean():.3f}  "
              f"min={grp['sample_entropy'].min():.3f}  "
              f"max={grp['sample_entropy'].max():.3f}")
    print(f"\nLowest SampEn (most regular spreads):")
    print(out.nsmallest(10, "sample_entropy")[
        ["tf", "symbol_a", "symbol_b", "sample_entropy", "half_life"]
    ].to_string(index=False))

    os.makedirs(os.path.dirname(_OUT), exist_ok=True)
    out.to_parquet(_OUT, index=False)
    print(f"\nFull results written to {_OUT}")


if __name__ == "__main__":
    main()
