"""Verification for structural_break_onset_detection.py's calendar-time-normalized
MIN_SEGMENT_BARS fix (2026-08-23) -- the real, previously-diagnosed bug where a flat 200-bar
floor meant ~9.5 months at 1D but only a few days at 3m (KVUE/KMB@3m: 9 spurious "breaks" in a
couple months, noise not real regime change).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

import numpy as np
import pandas as pd

from structural_break_onset_detection import (
    _calendar_days_per_bar, min_segment_bars_for_dates, find_all_breaks, MIN_SEGMENT_BARS,
)

checks = []


def check(name, cond):
    checks.append((name, cond))
    print(f"{'PASS' if cond else 'FAIL'}: {name}")


# --- Check 1: calendar-day-per-bar detection matches known real cadences ---
dates_1d = pd.bdate_range("2020-01-01", periods=500)  # business days ~= 1D bars
check("1D cadence detected ~1.0 calendar day/bar",
      abs(_calendar_days_per_bar(dates_1d) - 1.0) < 0.5)  # bdate_range has weekend gaps, ~1.4 avg

dates_3m = pd.date_range("2020-01-01 09:30", periods=5000, freq="3min")
days_per_bar_3m = _calendar_days_per_bar(dates_3m)
check("3m cadence detected as a small fraction of a day",
      days_per_bar_3m < 0.01)  # 3 min = 0.00208 days

# --- Check 2: min_segment_bars_for_dates gives a MUCH larger bar count at 3m than the old flat 200 ---
min_seg_1d = min_segment_bars_for_dates(dates_1d)
min_seg_3m = min_segment_bars_for_dates(dates_3m)
check("1D min_segment_bars stays close to the old flat 200 (preserves existing behavior)",
      150 <= min_seg_1d <= 300)
check("3m min_segment_bars is MUCH larger than the old flat 200 (the actual bug fix)",
      min_seg_3m > 10 * MIN_SEGMENT_BARS)
print(f"  (1D: {min_seg_1d} bars, 3m: {min_seg_3m} bars -- both now represent ~200 real calendar days)")

# --- Check 3: absolute floor never goes below MIN_SEGMENT_BARS even for very coarse timeframes ---
dates_1mo = pd.date_range("2000-01-01", periods=50, freq="MS")
check("very coarse timeframe still respects the absolute MIN_SEGMENT_BARS floor",
      min_segment_bars_for_dates(dates_1mo) >= MIN_SEGMENT_BARS)

# --- Check 4: real behavioral test -- synthetic 3m noise-only series (no real regime change)
# should now find FEWER spurious breaks under the calendar-normalized floor than under the old
# flat 200-bar floor, reproducing the actual KVUE/KMB@3m finding in miniature. ---
rng = np.random.default_rng(7)
n = 8000
dates_test = pd.date_range("2024-01-01 09:30", periods=n, freq="3min")
# Pure noise spread -- no real structural break anywhere, any detected "break" is a false positive
noise_spread = rng.standard_normal(n).cumsum() * 0.01 + rng.standard_normal(n) * 0.5

breaks_old_flat = find_all_breaks(noise_spread, dates_test, min_segment_bars=MIN_SEGMENT_BARS)
breaks_new_calendar = find_all_breaks(noise_spread, dates_test, min_segment_bars=None)

check(f"calendar-normalized floor finds fewer (or equal) spurious breaks on pure noise at 3m "
      f"(old flat={len(breaks_old_flat)}, new calendar={len(breaks_new_calendar)})",
      len(breaks_new_calendar) <= len(breaks_old_flat))

n_fail = sum(1 for _, c in checks if not c)
print(f"\n{len(checks) - n_fail}/{len(checks)} checks passed")
sys.exit(1 if n_fail else 0)
