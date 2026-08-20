"""
Synthetic verification of research/vol_swap_style_risk_estimate_comparison.py
-- run BEFORE trusting the real comparison run.

Checks:
  1. Causal, no lookahead (mutation test) for vol_swap_style_diff_vol.
  2. When spread diffs have ~zero mean (no real drift), the vol-swap-style
     (zero-mean) diff volatility and a standard (mean-subtracted) diff std
     should be very close -- the two conventions only diverge when there's
     real drift in the diffs.
  3. When spread diffs have a REAL, sustained non-zero mean (a genuinely
     trending spread), the zero-mean vol-swap convention and a mean-
     subtracted convention should meaningfully DIVERGE -- confirms the
     comparison is actually testing something real, not two numbers that
     always coincide.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from research.vol_swap_style_risk_estimate_comparison import vol_swap_style_diff_vol


def main():
    failures = []
    rng = np.random.default_rng(7)

    # --- Check 1: causal ---
    base = pd.Series(rng.normal(0, 1, 300).cumsum() * 0.1)
    v1 = vol_swap_style_diff_vol(base, window=30)
    mutated = base.copy()
    mutated.iloc[250:] += 100.0
    v2 = vol_swap_style_diff_vol(mutated, window=30)
    if not np.allclose(v1.iloc[:249].dropna(), v2.iloc[:249].dropna(), equal_nan=True):
        failures.append("Check 1: mutating future values changed past vol_swap_style_diff_vol -- NOT causal")

    # --- Check 2: near-zero-mean diffs -> zero-mean and mean-subtracted converge ---
    no_drift = pd.Series(rng.normal(0, 1, 500))  # random walk with ~0-mean increments
    v_zero_mean = vol_swap_style_diff_vol(no_drift, window=60)
    mean_sub_std = no_drift.diff().rolling(60, min_periods=30).std(ddof=1)
    close_pct = float((np.abs(v_zero_mean - mean_sub_std) / mean_sub_std).dropna().median())
    if close_pct > 0.15:
        failures.append(f"Check 2: with ~zero-mean diffs, zero-mean and mean-subtracted vol should be "
                         f"close (median relative diff <15%), got {close_pct:.3f}")

    # --- Check 3: real drift -> the two conventions diverge ---
    drift = pd.Series(np.full(500, 2.0) + rng.normal(0, 0.3, 500))  # diffs with mean=2.0, real drift
    drift_spread = drift.cumsum()
    v_zero_mean_drift = vol_swap_style_diff_vol(drift_spread, window=60)
    mean_sub_std_drift = drift_spread.diff().rolling(60, min_periods=30).std(ddof=1)
    divergence = float((np.abs(v_zero_mean_drift - mean_sub_std_drift) / mean_sub_std_drift).dropna().median())
    if divergence < 1.0:
        failures.append(f"Check 3: with real drift in the diffs (mean=2.0), zero-mean and "
                         f"mean-subtracted vol should meaningfully diverge (median relative diff "
                         f">100%), got {divergence:.3f} -- the two conventions may not be testing "
                         f"a real difference")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All vol-swap-style risk estimate checks passed.")
    print(f"  Check 1: causal (no lookahead) confirmed")
    print(f"  Check 2: near-zero-mean diffs, conventions converge (median rel. diff {close_pct:.3f})")
    print(f"  Check 3: real drift, conventions diverge as expected (median rel. diff {divergence:.3f})")


if __name__ == "__main__":
    main()
