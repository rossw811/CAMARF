"""
debug/_verify_coint_strength_bar_system.py -- synthetic ground-truth checks for
research/coint_strength_bar_system.py, BEFORE trusting it against the real 5M-row
coint_strength_series.parquet.

Run: python debug/_verify_coint_strength_bar_system.py
(Fully synthetic/offline -- no real data needed.)
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research.coint_strength_bar_system as bars

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


def make_pair_df(z_seq, decay_seq, pv_seq, sym_a="A", sym_b="X"):
    n = len(z_seq)
    return pd.DataFrame({
        "symbol_a": [sym_a] * n, "symbol_b": [sym_b] * n, "window_start": range(n),
        "coint_strength_z_fixed": z_seq, "coint_decay_rate": decay_seq, "pvalue": pv_seq,
    })


print("Check 1: entry at first z>=1.0, exit via decay<0 firing BEFORE a later z-reversion would "
      "have (the earlier of the two exit conditions wins), and z stays below the entry "
      "threshold afterward so no spurious re-entry occurs")
z1 = [0.2, 0.5, 1.2, 1.8, 2.0, 0.5, 0.3, 0.1]  # crosses 1.0 at idx2; idx5 onward stays < 1.0 (no re-entry)
decay1 = [np.nan, 0.01, 0.02, 0.01, -0.01, -0.02, -0.01, 0.0]  # turns negative at idx4
pv1 = [0.9, 0.9, 0.01, 0.01, 0.01, 0.9, 0.9, 0.9]
df1 = make_pair_df(z1, decay1, pv1)
result1 = bars.detect_bars(df1, entry_threshold=1.0, exit_threshold=0.0)
check("exactly 1 bar detected (no spurious re-entry after the exit)", len(result1) == 1)
check("bar entered at window_start=2 (first z>=1.0)",
      len(result1) == 1 and result1.iloc[0]["entry_window_start"] == 2)
check("bar exits at window_start=4 (decay-triggered -- fires before z would have reverted "
      "below exit_threshold at idx5)",
      len(result1) == 1 and result1.iloc[0]["exit_window_start"] == 4)
check("exit correctly attributed to decay, not z-reversion",
      len(result1) == 1 and result1.iloc[0]["exited_by_decay"] == True and
      result1.iloc[0]["exited_by_z_reversion"] == False)
check("bar length is 3 windows (idx2, idx3, idx4 inclusive)",
      len(result1) == 1 and result1.iloc[0]["n_windows_in_bar"] == 3)
check("in-bar persist rate is 1.0 (all 3 windows have pvalue<0.05)",
      len(result1) == 1 and result1.iloc[0]["persist_rate_in_bar"] == 1.0)

print("Check 2: pure z-reversion exit (no decay ever goes negative) exits correctly via "
      "z crossing below exit_threshold")
z2 = [0.2, 1.5, 2.0, 1.8, -0.5]
decay2 = [np.nan, 0.02, 0.01, 0.01, 0.01]  # always positive/flat -- never triggers a decay exit
pv2 = [0.9, 0.01, 0.01, 0.01, 0.9]
df2 = make_pair_df(z2, decay2, pv2)
result2 = bars.detect_bars(df2, entry_threshold=1.0, exit_threshold=0.0)
check("1 bar, entered at idx1, exited at idx4 via pure z-reversion",
      len(result2) == 1 and result2.iloc[0]["entry_window_start"] == 1 and
      result2.iloc[0]["exit_window_start"] == 4 and
      result2.iloc[0]["exited_by_z_reversion"] == True and
      result2.iloc[0]["exited_by_decay"] == False)

print("Check 3: a series that never crosses the entry threshold produces zero bars")
z3 = [0.1, 0.2, -0.1, 0.3, 0.5]
decay3 = [np.nan, 0.01, 0.01, 0.01, 0.01]
pv3 = [0.9, 0.9, 0.9, 0.9, 0.9]
df3 = make_pair_df(z3, decay3, pv3)
result3 = bars.detect_bars(df3, entry_threshold=1.0, exit_threshold=0.0)
check("0 bars when entry threshold is never crossed", len(result3) == 0)

print("Check 4: a bar still open at the series' end is captured (not silently dropped) and "
      "flagged as still-open, not a real exit")
z4 = [0.1, 1.5, 1.8, 2.0]  # crosses entry at idx1, never reverts, series just ends
decay4 = [np.nan, 0.01, 0.01, 0.01]
pv4 = [0.9, 0.01, 0.01, 0.01]
df4 = make_pair_df(z4, decay4, pv4)
result4 = bars.detect_bars(df4, entry_threshold=1.0, exit_threshold=0.0)
check("1 bar captured even though it never formally exited",
      len(result4) == 1 and result4.iloc[0]["entry_window_start"] == 1 and
      result4.iloc[0]["exit_window_start"] == 3)
check("flagged as still-open at series end, not a false z-reversion/decay exit",
      len(result4) == 1 and result4.iloc[0]["exited_at_series_end"] == True and
      result4.iloc[0]["exited_by_z_reversion"] == False and
      result4.iloc[0]["exited_by_decay"] == False)

print("Check 5: two separate pairs are processed independently -- no cross-pair leakage of "
      "entry/exit state")
df5a = make_pair_df([0.1, 1.5, -0.5], [np.nan, 0.01, 0.01], [0.9, 0.01, 0.9], sym_a="P1", sym_b="Q1")
df5b = make_pair_df([0.1, 0.2, 0.1], [np.nan, 0.01, 0.01], [0.9, 0.9, 0.9], sym_a="P2", sym_b="Q2")
df5 = pd.concat([df5a, df5b], ignore_index=True)
result5 = bars.detect_bars(df5, entry_threshold=1.0, exit_threshold=0.0)
check("exactly 1 bar total (only P1/Q1 crosses the entry threshold, P2/Q2 never does)",
      len(result5) == 1)
check("the 1 bar belongs to P1/Q1, not P2/Q2",
      len(result5) == 1 and result5.iloc[0]["symbol_a"] == "P1")

print("Check 6: two sequential bars for the SAME pair (enter, exit, re-enter, exit again) are "
      "both captured separately, not merged into one")
z6 = [0.1, 1.5, -0.5, 0.2, 1.8, -0.3]
decay6 = [np.nan, 0.01, 0.01, 0.01, 0.01, 0.01]
pv6 = [0.9, 0.01, 0.9, 0.9, 0.01, 0.9]
df6 = make_pair_df(z6, decay6, pv6)
result6 = bars.detect_bars(df6, entry_threshold=1.0, exit_threshold=0.0)
check("2 separate bars detected for the same pair", len(result6) == 2)
if len(result6) == 2:
    check("first bar: entry=1, exit=2", result6.iloc[0]["entry_window_start"] == 1 and
          result6.iloc[0]["exit_window_start"] == 2)
    check("second bar: entry=4, exit=5", result6.iloc[1]["entry_window_start"] == 4 and
          result6.iloc[1]["exit_window_start"] == 5)

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
