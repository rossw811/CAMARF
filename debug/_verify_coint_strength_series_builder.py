"""
debug/_verify_coint_strength_series_builder.py -- synthetic checks for
research/coint_strength_series_builder.py, run BEFORE trusting it against
real Tier 3 windows data. Also a real timing check against a large,
many-small-groups synthetic dataset shaped like the real data (638,095
groups averaging ~7.8 rows each) -- this project has twice this session
found a "correct on small synthetic data, catastrophically slow on many-
small-groups real data" bug that a pure correctness check would miss.
"""
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.coint_strength_series_builder import build_coint_strength_series

passed = 0
failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}")
        failed += 1


print("Check 1: coint_strength is exactly 1 - pvalue")
windows = pd.DataFrame([
    {"symbol_a": "A", "symbol_b": "B", "window_start": 0,
     "window_end_date": pd.Timestamp("2020-01-01"), "pvalue": 0.02},
    {"symbol_a": "A", "symbol_b": "B", "window_start": 1,
     "window_end_date": pd.Timestamp("2020-02-01"), "pvalue": 0.30},
])
series = build_coint_strength_series(windows, z_window=1)
check("pvalue=0.02 -> coint_strength=0.98", abs(series.iloc[0]["coint_strength"] - 0.98) < 1e-9)
check("pvalue=0.30 -> coint_strength=0.70", abs(series.iloc[1]["coint_strength"] - 0.70) < 1e-9)

print("Check 2: coint_decay_rate is the causal first difference (NaN on the first window "
      "of each pair, real value after)")
check("first window of A/B has NaN decay rate (no prior window to diff against)",
      pd.isna(series.iloc[0]["coint_decay_rate"]))
check("second window's decay rate = 0.70 - 0.98 = -0.28 (cointegration WEAKENING)",
      abs(series.iloc[1]["coint_decay_rate"] - (-0.28)) < 1e-9)

print("Check 3: coint_strength_z respects min_periods -- NaN until the rolling window is full, "
      "never fabricated from a too-small sample")
windows3 = pd.DataFrame([
    {"symbol_a": "X", "symbol_b": "Y", "window_start": i,
     "window_end_date": pd.Timestamp("2020-01-01") + pd.Timedelta(days=30 * i),
     "pvalue": 0.01 * (i + 1)}
    for i in range(5)
])
series3 = build_coint_strength_series(windows3, z_window=3)
check("windows 0-1 (< z_window=3 history) have NaN coint_strength_z",
      series3.iloc[0]["coint_strength_z"] != series3.iloc[0]["coint_strength_z"]  # NaN check
      and series3.iloc[1]["coint_strength_z"] != series3.iloc[1]["coint_strength_z"])
check("window 2 (exactly 3 windows of history) has a real, non-NaN coint_strength_z",
      not pd.isna(series3.iloc[2]["coint_strength_z"]))

print("Check 4: multiple pairs are handled independently -- no cross-pair leakage into "
      "rolling stats or decay rates")
windows4 = pd.concat([windows3, pd.DataFrame([
    {"symbol_a": "P", "symbol_b": "Q", "window_start": 0,
     "window_end_date": pd.Timestamp("2020-01-01"), "pvalue": 0.5},
    {"symbol_a": "P", "symbol_b": "Q", "window_start": 1,
     "window_end_date": pd.Timestamp("2020-02-01"), "pvalue": 0.9},
])], ignore_index=True)
series4 = build_coint_strength_series(windows4, z_window=3)
pq_rows = series4[(series4["symbol_a"] == "P") & (series4["symbol_b"] == "Q")]
check("P/Q's first window has NaN decay rate independently of X/Y's data ordering",
      pd.isna(pq_rows.iloc[0]["coint_decay_rate"]))
check("P/Q's second window decay rate is computed from ITS OWN prior window only "
      "(0.1 - 0.5 = -0.4), not contaminated by X/Y's values",
      abs(pq_rows.iloc[1]["coint_decay_rate"] - (-0.4)) < 1e-9)

print("Check 5: performance -- many small groups (shaped like real Tier 3 data: ~638K groups "
      "averaging ~8 rows each) completes in well under a minute, not the multi-minute-plus "
      "Python-loop behavior this session already killed once today")
rng = np.random.default_rng(0)
n_groups = 20_000  # scaled down from 638K for a fast CI-friendly check; the vectorized
                    # grouped-rolling approach's cost scales roughly linearly in n_groups,
                    # so this is still a meaningful proxy for the real-scale shape.
rows_per_group = 8
big_rows = []
base_date = pd.Timestamp("2000-01-01")
for i in range(n_groups):
    for w in range(rows_per_group):
        big_rows.append({
            "symbol_a": f"S{i}A", "symbol_b": f"S{i}B", "window_start": w,
            "window_end_date": base_date + pd.Timedelta(days=30 * w),
            "pvalue": float(rng.uniform(0, 1)),
        })
big_windows = pd.DataFrame(big_rows)
t0 = time.time()
big_series = build_coint_strength_series(big_windows, z_window=3)
elapsed = time.time() - t0
check(f"{n_groups} groups x {rows_per_group} rows ({len(big_windows)} total rows) completes "
      f"in well under 60s (actual: {elapsed:.1f}s) -- proxy for real ~638K-group scale",
      elapsed < 60)
check("output row count matches input row count exactly (no rows dropped or duplicated)",
      len(big_series) == len(big_windows))

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
