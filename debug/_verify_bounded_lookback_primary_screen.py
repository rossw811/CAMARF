"""
Synthetic verification for research/bounded_lookback_primary_screen.py's
eg_tier_on_window(). Tests the core claim the script exists to check: a
pair cointegrated in an OLD sub-period but NOT in the recent period should
look better (lower EG p-value / higher tier) on the full sample than on a
bounded recent-only window — mirroring this project's own headline
Strictness Paradox finding (NTRS/STT, SHW/UNP) on a controlled synthetic
case with a KNOWN ground truth, not real data.

Run: python debug/_verify_bounded_lookback_primary_screen.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from bounded_lookback_primary_screen import eg_tier_on_window

np.random.seed(42)


def _make_index(n, freq_days=1):
    return pd.date_range("2000-01-01", periods=n, freq=f"{freq_days}D")


def case1_stays_cointegrated_throughout():
    """Control: genuinely cointegrated the whole way through. Full-sample
    and bounded-recent should BOTH pass — no false downgrade from the
    bounded window alone."""
    n = 4000  # ~11 years of daily bars
    log_b = np.cumsum(np.random.normal(0, 0.01, n)) + 4.0
    resid = np.zeros(n)
    for t in range(1, n):
        resid[t] = 0.9 * resid[t - 1] + np.random.normal(0, 0.02)
    log_a = 1.2 * log_b + resid
    idx = _make_index(n)

    full = eg_tier_on_window(log_a, log_b, idx)
    cutoff = idx.max() - pd.Timedelta(days=5 * 365)
    mask = idx >= cutoff
    recent = eg_tier_on_window(log_a[mask], log_b[mask], idx[mask])

    print(f"Case 1 (stays cointegrated): full tier={full['stats_tier']} (p={full['eg_pval']:.4f}), "
          f"5y tier={recent['stats_tier']} (p={recent['eg_pval']:.4f})")
    assert full["eg_pval"] < 0.05, "full-sample should show significant cointegration"
    assert recent["eg_pval"] < 0.05, "recent-only should ALSO show significant cointegration (control)"
    print("  PASS: both windows correctly detect the genuine, persistent relationship")


def case2_decoupled_recently():
    """The core claim: cointegrated for the first ~8 years, then the
    relationship breaks down (residual becomes a random walk) for the
    final ~3 years. Full-sample EG, dominated by the long cointegrated
    history, should still look significant. The bounded 5y-recent window
    should correctly fail to find cointegration in the broken period."""
    n_old, n_new = 3000, 1000  # ~8.2y cointegrated, ~2.7y decoupled
    log_b = np.cumsum(np.random.normal(0, 0.01, n_old + n_new)) + 4.0

    resid = np.zeros(n_old + n_new)
    for t in range(1, n_old):
        resid[t] = 0.9 * resid[t - 1] + np.random.normal(0, 0.02)
    # From n_old onward: residual becomes its own random walk (unit root,
    # genuinely NOT mean-reverting) instead of continuing the AR(1) process.
    for t in range(n_old, n_old + n_new):
        resid[t] = resid[t - 1] + np.random.normal(0, 0.02)

    log_a = 1.2 * log_b + resid
    idx = _make_index(n_old + n_new)

    full = eg_tier_on_window(log_a, log_b, idx)
    cutoff = idx.max() - pd.Timedelta(days=int(2.5 * 365))
    mask = idx >= cutoff
    recent = eg_tier_on_window(log_a[mask], log_b[mask], idx[mask])

    print(f"Case 2 (decoupled recently): full tier={full['stats_tier']} (p={full['eg_pval']:.4f}), "
          f"~2.5y tier={recent['stats_tier']} (p={recent['eg_pval']:.4f})")
    assert full["eg_pval"] < 0.10, (
        f"full-sample should look at least borderline-cointegrated (dominated by 8y of real "
        f"cointegration), got p={full['eg_pval']:.4f} — scenario didn't construct the intended trap"
    )
    assert recent["eg_pval"] > full["eg_pval"], (
        "the bounded recent-only window should show a WORSE (higher) p-value than full-sample "
        "once the relationship has genuinely broken down — this is the entire mechanism the "
        "script exists to catch"
    )
    print("  PASS: bounded-recent window correctly catches the recent breakdown that full-sample misses")


def case3_insufficient_data():
    """Degenerate case: too few bars. Should return None, not crash or
    fabricate a result."""
    n = 30
    log_b = np.cumsum(np.random.normal(0, 0.01, n)) + 4.0
    log_a = 1.2 * log_b + np.random.normal(0, 0.02, n)
    idx = _make_index(n)
    result = eg_tier_on_window(log_a, log_b, idx)
    print(f"Case 3 (insufficient data, n={n}): result={result}")
    assert result is None, "should return None for insufficient data, not a fabricated tier"
    print("  PASS: correctly returns None rather than fabricating a result")


if __name__ == "__main__":
    case1_stays_cointegrated_throughout()
    case2_decoupled_recently()
    case3_insufficient_data()
    print("\nAll bounded_lookback_primary_screen checks passed.")
