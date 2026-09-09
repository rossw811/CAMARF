"""Synthetic proof for research/sequential_bootstrap_ml_comparison.py's
overlap-weighting math -- not a production script, run manually to verify
average_uniqueness_per_pair / sequential_bootstrap_indices before trusting
their output on real ml.py examples."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from sequential_bootstrap_ml_comparison import (
    compute_label_end_times, average_uniqueness_per_pair, sequential_bootstrap_indices,
)

n_checks = 0
n_passed = 0


def check(name, cond):
    global n_checks, n_passed
    n_checks += 1
    status = "PASS" if cond else "FAIL"
    if cond:
        n_passed += 1
    print(f"[{status}] {name}")


def make_df(rows):
    """rows: list of (symbol_a, symbol_b, tf_label, entry_time, horizon_bars)."""
    return pd.DataFrame(rows, columns=["symbol_a", "symbol_b", "tf_label", "entry_time", "horizon_bars"])


# --- 1. compute_label_end_times: known tf_label -> timedelta ---
df = make_df([("A", "B", "1D", pd.Timestamp("2026-01-01"), 5)])
ends = compute_label_end_times(df)
check("1D horizon: 5 bars = 5 days", ends.iloc[0] == pd.Timestamp("2026-01-06"))

df_1h = make_df([("A", "B", "1h", pd.Timestamp("2026-01-01 00:00"), 3)])
ends_1h = compute_label_end_times(df_1h)
check("1h horizon: 3 bars = 3 hours", ends_1h.iloc[0] == pd.Timestamp("2026-01-01 03:00"))

df_bad = make_df([("A", "B", "9999m", pd.Timestamp("2026-01-01"), 1)])
try:
    compute_label_end_times(df_bad)
    check("unknown tf_label raises", False)
except ValueError:
    check("unknown tf_label raises", True)

# --- 2. average_uniqueness_per_pair: solitary label -> uniqueness 1.0 ---
df_solo = make_df([("A", "B", "1D", pd.Timestamp("2026-01-01"), 5)])
uniq_solo = average_uniqueness_per_pair(df_solo)
check("solitary label has uniqueness 1.0", np.isclose(uniq_solo.iloc[0], 1.0))

# --- 3. average_uniqueness_per_pair: two labels with IDENTICAL spans -> uniqueness 0.5 each ---
df_dup = make_df([
    ("A", "B", "1D", pd.Timestamp("2026-01-01"), 5),
    ("A", "B", "1D", pd.Timestamp("2026-01-01"), 5),
])
uniq_dup = average_uniqueness_per_pair(df_dup)
check("two identical-span labels each get uniqueness 0.5",
      np.allclose(uniq_dup.values, [0.5, 0.5]))

# --- 4. average_uniqueness_per_pair: two labels with ZERO overlap -> uniqueness 1.0 each ---
df_sep = make_df([
    ("A", "B", "1D", pd.Timestamp("2026-01-01"), 2),   # [Jan 1, Jan 3)
    ("A", "B", "1D", pd.Timestamp("2026-01-10"), 2),   # [Jan 10, Jan 12), no overlap
])
uniq_sep = average_uniqueness_per_pair(df_sep)
check("two non-overlapping labels each get uniqueness 1.0",
      np.allclose(uniq_sep.values, [1.0, 1.0]))

# --- 5. average_uniqueness_per_pair: partial overlap -> uniqueness strictly between 0.5 and 1.0 ---
df_partial = make_df([
    ("A", "B", "1D", pd.Timestamp("2026-01-01"), 4),   # [Jan 1, Jan 5)
    ("A", "B", "1D", pd.Timestamp("2026-01-03"), 4),   # [Jan 3, Jan 7), overlaps Jan 3-5
])
uniq_partial = average_uniqueness_per_pair(df_partial)
check("partially-overlapping labels get uniqueness strictly between 0.5 and 1.0",
      bool(((uniq_partial.values > 0.5) & (uniq_partial.values < 1.0)).all()))

# --- 6. average_uniqueness_per_pair: overlap computed PER PAIR, not pooled across pairs ---
df_cross = make_df([
    ("A", "B", "1D", pd.Timestamp("2026-01-01"), 5),
    ("C", "D", "1D", pd.Timestamp("2026-01-01"), 5),   # same window, DIFFERENT pair
])
uniq_cross = average_uniqueness_per_pair(df_cross)
check("identical-window labels from DIFFERENT pairs each get uniqueness 1.0 (no cross-pair pooling)",
      np.allclose(uniq_cross.values, [1.0, 1.0]))

# --- 7. sequential_bootstrap_indices: returns requested count, valid original indices ---
rows = [("A", "B", "1D", pd.Timestamp("2026-01-01") + pd.Timedelta(days=i), 3) for i in range(10)]
df_many = make_df(rows)
boot = sequential_bootstrap_indices(df_many, random_state=0)
check("sequential bootstrap returns len(df) draws by default", len(boot) == len(df_many))
check("all drawn indices are valid original row positions",
      bool(set(boot.tolist()).issubset(set(df_many.index.tolist()))))

# --- 8. sequential_bootstrap_indices: heavily-overlapping labels drawn less often than isolated ones ---
# 5 labels all sharing the exact same window (heavy overlap) + 1 isolated label far away.
overlap_rows = [("A", "B", "1D", pd.Timestamp("2026-01-01"), 5) for _ in range(5)]
isolated_row = [("A", "B", "1D", pd.Timestamp("2027-01-01"), 5)]
df_skew = make_df(overlap_rows + isolated_row)
counts_overlap = []
counts_isolated = []
for seed in range(30):
    b = sequential_bootstrap_indices(df_skew, random_state=seed)
    counts_overlap.append(np.isin(b, [0, 1, 2, 3, 4]).sum())
    counts_isolated.append(np.isin(b, [5]).sum())
mean_per_overlap_label = np.mean(counts_overlap) / 5.0
mean_isolated = np.mean(counts_isolated)
check(f"isolated label drawn more on average than any single overlapping label "
      f"({mean_isolated:.2f} vs {mean_per_overlap_label:.2f} per label, over 30 seeds)",
      mean_isolated > mean_per_overlap_label)

print(f"\n{n_passed}/{n_checks} checks passed")
sys.exit(0 if n_passed == n_checks else 1)
