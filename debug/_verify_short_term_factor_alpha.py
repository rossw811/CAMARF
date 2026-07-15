"""
Synthetic verification for research/short_term_factor_alpha.py's
reversal_signal() gap-aware-rolling fix (Phase 10 bias sweep finding #2,
2026-07-14). Confirms the fix recovers a trailing-window sum that a naive
.rolling(window).sum() on the raw ragged-calendar DataFrame would wrongly
null out, without changing values where there's no gap at all.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from research.short_term_factor_alpha import reversal_signal

idx = pd.date_range("2026-01-01", periods=10, freq="D")

# Symbol A: complete, no gaps -- fix must reproduce the naive result exactly.
a = pd.Series([0.01] * 10, index=idx)
# Symbol B: one isolated NaN (a foreign-listing holiday) at position 4,
# inside what would be the trailing window for later rows -- naive
# .rolling(5).sum() nulls out every window touching position 4; the fix
# should still recover a value once 5 REAL trading days have accumulated.
b_vals = [0.01] * 10
b_vals[4] = np.nan
b = pd.Series(b_vals, index=idx)

returns_df = pd.DataFrame({"A": a, "B": b})
result = reversal_signal(returns_df, window=5)

naive = -((returns_df.rolling(5).sum() - returns_df.rolling(5).sum().mean())
          / returns_df.rolling(5).sum().std().replace(0, 1))

print("Symbol A (no gap) — fixed vs naive match:",
      np.allclose(result["A"].dropna().values, naive["A"].dropna().values))

n_valid_naive_b = naive["B"].notna().sum()
n_valid_fixed_b = result["B"].notna().sum()
print(f"Symbol B (one gap) — naive valid rows: {n_valid_naive_b}, fixed valid rows: {n_valid_fixed_b}")

ok = (
    np.allclose(result["A"].dropna().values, naive["A"].dropna().values)
    and n_valid_fixed_b > n_valid_naive_b
)
print("\nPASS" if ok else "\nFAIL")
sys.exit(0 if ok else 1)
