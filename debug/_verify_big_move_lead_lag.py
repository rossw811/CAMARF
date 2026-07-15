"""
Synthetic verification for research/big_move_lead_lag.py's _big_move_dates
(task #69 Piece C, 2026-07-14). Confirms the fix for the dense-calendar-grid
NaN bug: a rolling window computed directly on a mostly-NaN dense grid
returns all-NaN and silently finds zero events — caught on real LNT/VTR
data (trailing_vol was NaN everywhere despite 3,705 real bars).
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from big_move_lead_lag import _big_move_dates


def test_sparse_dense_grid_still_finds_events():
    # Simulate aligned_pair_loader's dense grid: real bars are a small
    # minority, scattered among NaN placeholder rows, exactly like real
    # 1h data reindexed onto a dense multi-year calendar grid.
    rng = np.random.default_rng(0)
    n_total = 5000
    idx = pd.date_range("2024-01-01", periods=n_total, freq="h")
    ret = pd.Series(np.nan, index=idx)

    # Real bars: every 7th slot (mimics ~14% real-bar density, matching
    # the real LNT/VTR case), normal returns with std ~0.0035.
    real_positions = np.arange(0, n_total, 7)
    ret.iloc[real_positions] = rng.normal(0, 0.0035, len(real_positions))

    # Plant 5 unambiguous big moves (10x normal std) at known positions,
    # spaced far enough apart that each gets its own rolling-vol window
    # of ordinary (non-big) real bars before it.
    planted = real_positions[[50, 150, 250, 350, 450]]
    for p in planted:
        ret.iloc[p] = 0.035  # ~10 std devs given the 0.0035 baseline

    dates = _big_move_dates(ret, z_threshold=2.0, vol_window=20)
    assert len(dates) > 0, "BUG: found zero events on a series with 5 planted 10-std moves"

    planted_dates = set(pd.DatetimeIndex(idx[planted]).normalize())
    found_planted = planted_dates & set(dates)
    print(f"planted={len(planted_dates)}, total_flagged={len(dates)}, "
          f"planted_recovered={len(found_planted)}")
    assert len(found_planted) >= 4, (
        f"BUG: only recovered {len(found_planted)}/5 planted big moves"
    )
    print("PASS: sparse dense-grid series correctly finds big-move events")


def test_all_nan_trailing_vol_regression():
    # The exact failure mode caught on real data: rolling window landing
    # on a mostly-NaN dense grid produces all-NaN trailing_vol. Directly
    # assert this no longer produces zero events for a case that SHOULD
    # have events.
    idx = pd.date_range("2024-01-01", periods=2000, freq="h")
    ret = pd.Series(np.nan, index=idx)
    real_positions = np.arange(0, 2000, 6)  # sparse, same shape as real data
    rng = np.random.default_rng(1)
    ret.iloc[real_positions] = rng.normal(0, 0.002, len(real_positions))
    ret.iloc[real_positions[100]] = 0.05  # obvious outlier

    dates = _big_move_dates(ret, z_threshold=2.0, vol_window=20)
    assert len(dates) > 0, "REGRESSION: the dense-grid NaN bug is back"
    print(f"PASS: regression check — {len(dates)} events found (not zero)")


if __name__ == "__main__":
    test_sparse_dense_grid_still_finds_events()
    test_all_nan_trailing_vol_regression()
    print("\nAll cases passed.")
