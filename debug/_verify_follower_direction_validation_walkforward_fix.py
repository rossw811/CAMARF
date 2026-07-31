"""
Synthetic verification for Tier 2.4 (Grand Sweep 2026-07-20):
follower_direction_validation.py's redesign from an expanding-window
pseudo-OOS test (SEM computed from thousands of heavily-overlapping beta
estimates treated as independent) to a genuine non-overlapping walk-forward
test.

Under the NULL (x, y independent white noise, true beta = 0), a valid
statistical test should reject H0 at close to its nominal rate (~5% at
alpha=0.05) across repeated draws. The pre-fix expanding-window approach
should reject FAR more often than 5% (its SEM shrinks toward zero as the
number of expanding steps grows, even though the true independent
information content does not) -- the exact "manufactures artificially
significant t-stats for almost any pair" failure mode the audit flagged.
The fixed walk-forward approach should reject close to the nominal 5% rate.

Run: python debug/_verify_follower_direction_validation_walkforward_fix.py
"""
import os
import sys

import numpy as np
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from follower_direction_validation import _walk_forward_betas


def _old_buggy_rolling_ols_oos(x, y, min_periods=60):
    """Pre-fix implementation, reproduced here (not imported -- the fixed
    module no longer contains it) purely to demonstrate the bug it had."""
    n = len(x)
    betas = []
    for t in range(min_periods, n):
        xi, yi = x[:t], y[:t]
        mask = np.isfinite(xi) & np.isfinite(yi)
        if mask.sum() < min_periods:
            betas.append(np.nan)
            continue
        xi_m, yi_m = xi[mask], yi[mask]
        vx = np.var(xi_m, ddof=1)
        if vx < 1e-12:
            betas.append(np.nan)
            continue
        beta = np.cov(xi_m, yi_m, ddof=1)[0, 1] / vx
        betas.append(beta)
    return np.array(betas)


def _old_agg_test(betas):
    valid = np.isfinite(betas)
    betas_v = betas[valid]
    n_oos = len(betas_v)
    if n_oos < 2:
        return np.nan
    mean_beta = np.mean(betas_v)
    pooled_se = np.std(betas_v, ddof=1) / np.sqrt(n_oos)
    if pooled_se < 1e-12:
        return np.nan
    agg_t = mean_beta / pooled_se
    return float(2 * stats.t.sf(abs(agg_t), df=n_oos - 1))


def main():
    rng = np.random.default_rng(11)
    n_bars = 2000
    n_trials = 200
    alpha = 0.05

    old_rejections = 0
    new_rejections = 0
    new_skipped = 0

    for trial in range(n_trials):
        x = rng.normal(0, 1, n_bars)
        y = rng.normal(0, 1, n_bars)  # independent of x -- true beta = 0

        old_betas = _old_buggy_rolling_ols_oos(x, y, min_periods=60)
        old_p = _old_agg_test(old_betas)
        if np.isfinite(old_p) and old_p < alpha:
            old_rejections += 1

        _, test_betas = _walk_forward_betas(x, y, train_window=252, test_window=60)
        if len(test_betas) < 8:
            new_skipped += 1
            continue
        _, new_p = stats.ttest_1samp(test_betas, popmean=0.0)
        if new_p < alpha:
            new_rejections += 1

    old_rate = old_rejections / n_trials
    new_rate = new_rejections / (n_trials - new_skipped) if (n_trials - new_skipped) > 0 else float("nan")

    print(f"Under the NULL (true beta=0, {n_trials} independent trials, n_bars={n_bars}):")
    print(f"  Old (expanding-window pseudo-OOS) false-positive rate: {old_rate:.1%} (nominal alpha={alpha:.0%})")
    print(f"  New (walk-forward, non-overlapping) false-positive rate: {new_rate:.1%} ({n_trials - new_skipped} usable trials)")

    assert old_rate > 0.25, (
        f"Test setup failed to reproduce the bug -- old implementation's false-positive rate "
        f"({old_rate:.1%}) should be far above the nominal 5% under the null."
    )
    assert new_rate < 0.15, (
        f"Fixed implementation's false-positive rate ({new_rate:.1%}) is still well above the "
        f"nominal 5% -- walk-forward fix may not be working correctly."
    )
    print("\nPASS: old expanding-window test massively over-rejects the null (manufactured "
          "significance); fixed walk-forward test's rejection rate is close to nominal.")


if __name__ == "__main__":
    main()
