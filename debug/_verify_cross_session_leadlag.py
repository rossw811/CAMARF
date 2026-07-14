"""
Synthetic verification for research/cross_session_leadlag.py (2026-07-13).

Confirms:
  1. overnight_gap_series / close_to_close_series compute the correct
     session-boundary quantities on a small hand-built OHLC fixture.
  2. daily_lagged_corr_scan + best_lag correctly recover a KNOWN engineered
     lead-lag relationship (B's overnight gap today predicts A's overnight
     gap tomorrow, i.e. B leads A by 1 day) at the right lag and sign.
  3. A synthetic NULL case (independent random walks, no engineered
     relationship) does NOT spuriously flag a non-zero lag as significant
     after permutation correction — the false-positive-control check.
"""
import os
import sys

import numpy as np
import pandas as pd

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "research"))

from cross_session_leadlag import (
    overnight_gap_series, close_to_close_series,
    daily_lagged_corr_scan, best_lag, permutation_pvalue,
)


def _make_session_df(dates, opens, closes):
    """Build a minimal 2-bar-per-day OHLC frame (open bar, close bar) —
    enough for _daily_sessions' groupby(date).first()/last() logic."""
    rows = []
    idx = []
    for d, o, c in zip(dates, opens, closes):
        rows.append({"open": o, "high": max(o, c), "low": min(o, c), "close": o, "volume": 100})
        idx.append(pd.Timestamp(d) + pd.Timedelta(hours=9))
        rows.append({"open": c, "high": max(o, c), "low": min(o, c), "close": c, "volume": 100})
        idx.append(pd.Timestamp(d) + pd.Timedelta(hours=15))
    return pd.DataFrame(rows, index=pd.DatetimeIndex(idx))


def test_session_boundary_quantities():
    dates = pd.bdate_range("2026-01-05", periods=5)
    opens = [100.0, 102.0, 101.0, 105.0, 103.0]
    closes = [101.0, 100.5, 104.0, 102.5, 106.0]
    df = _make_session_df(dates, opens, closes)

    gap = overnight_gap_series(df)
    # day 2 (2026-01-06): open=102.0 vs prior close=101.0 -> log(102/101)
    expected_gap_day2 = np.log(102.0 / 101.0)
    assert abs(gap.iloc[1] - expected_gap_day2) < 1e-9, \
        f"overnight_gap_series wrong: {gap.iloc[1]} vs {expected_gap_day2}"
    assert pd.isna(gap.iloc[0]), "first day's overnight gap must be NaN (no prior close)"

    c2c = close_to_close_series(df)
    expected_c2c_day2 = np.log(100.5 / 101.0)
    assert abs(c2c.iloc[1] - expected_c2c_day2) < 1e-9, \
        f"close_to_close_series wrong: {c2c.iloc[1]} vs {expected_c2c_day2}"
    print("PASS: session-boundary quantities (overnight_gap_series, close_to_close_series)")


def test_engineered_lead_lag_recovered():
    rng = np.random.default_rng(7)
    n = 300
    dates = pd.bdate_range("2024-01-01", periods=n + 1)
    b_gap = rng.normal(0, 0.01, n + 1)
    # A's overnight gap on day t+1 = 0.8 * B's overnight gap on day t + small noise
    # -> B leads A by 1 day. Build OHLC series whose overnight_gap_series
    # reproduces these engineered gap sequences exactly.
    a_gap = np.zeros(n + 1)
    a_gap[0] = rng.normal(0, 0.01)
    for t in range(1, n + 1):
        a_gap[t] = 0.8 * b_gap[t - 1] + rng.normal(0, 0.002)

    def _build_from_gaps(gaps, dates):
        price = 100.0
        opens, closes = [], []
        for i, g in enumerate(gaps):
            o = price * np.exp(g) if i > 0 else price
            c = o * (1 + rng.normal(0, 0.001))
            opens.append(o)
            closes.append(c)
            price = c
        return _make_session_df(dates, opens, closes)

    df_a = _build_from_gaps(a_gap, dates)
    df_b = _build_from_gaps(b_gap, dates)

    gap_a = overnight_gap_series(df_a)
    gap_b = overnight_gap_series(df_b)
    scan, n_obs = daily_lagged_corr_scan(gap_a, gap_b, max_lag=5)
    k_star, c_star, n_star = best_lag(scan)
    # Convention (see daily_lagged_corr_scan): lag<0 means b(t) aligned with
    # a(t-lag) i.e. b leads a. Engineered relationship is B leads A by 1 day
    # -> expect k_star == -1.
    assert k_star == -1, f"expected best_lag=-1 (B leads A by 1 day), got {k_star}"
    assert c_star > 0.5, f"expected strong positive correlation at best lag, got {c_star}"
    perm_p, n_perm = permutation_pvalue(gap_a, gap_b, max_lag=5, real_abs_corr=abs(c_star), n_perm=200)
    assert perm_p is not None and perm_p < 0.05, \
        f"engineered lead-lag should survive permutation correction, got p={perm_p}"
    print(f"PASS: engineered 1-day lead-lag recovered (best_lag={k_star}, corr={c_star:.3f}, "
          f"perm_p={perm_p:.4f})")


def test_null_case_no_false_positive():
    rng = np.random.default_rng(99)
    n = 300
    dates = pd.bdate_range("2024-01-01", periods=n + 1)
    a_gap = rng.normal(0, 0.01, n + 1)
    b_gap = rng.normal(0, 0.01, n + 1)  # fully independent of a_gap

    def _build_from_gaps(gaps, dates):
        price = 100.0
        opens, closes = [], []
        for i, g in enumerate(gaps):
            o = price * np.exp(g) if i > 0 else price
            c = o * (1 + rng.normal(0, 0.001))
            opens.append(o)
            closes.append(c)
            price = c
        return _make_session_df(dates, opens, closes)

    df_a = _build_from_gaps(a_gap, dates)
    df_b = _build_from_gaps(b_gap, dates)
    gap_a = overnight_gap_series(df_a)
    gap_b = overnight_gap_series(df_b)
    scan, n_obs = daily_lagged_corr_scan(gap_a, gap_b, max_lag=5)
    k_star, c_star, n_star = best_lag(scan)
    perm_p, n_perm = permutation_pvalue(gap_a, gap_b, max_lag=5, real_abs_corr=abs(c_star), n_perm=200)
    assert perm_p is not None and perm_p >= 0.05, \
        f"independent random-walk gaps must NOT survive permutation correction, got p={perm_p}"
    print(f"PASS: null case (independent series) correctly NOT flagged (best_lag={k_star}, "
          f"corr={c_star:.3f}, perm_p={perm_p:.4f})")


if __name__ == "__main__":
    test_session_boundary_quantities()
    test_engineered_lead_lag_recovered()
    test_null_case_no_false_positive()
    print("\nAll cross_session_leadlag.py verification cases passed.")
