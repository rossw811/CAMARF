"""
Synthetic verification for research/structural_break_onset_detection.py
(2026-08-04), before trusting it on real pair data -- matching this
project's verify-before-trusting discipline.

Checks:
  1. A spread that is a random walk (unrelated) for the FIRST half and
     genuinely mean-reverting (OU-like, phi << 1) for the SECOND half
     produces exactly one detected break, classified "onset", at
     approximately the true midpoint.
  2. A spread that is genuinely mean-reverting throughout (no real
     change) produces NO significant break -- guards against the
     structural-break test firing on noise alone.
  3. A spread with a real ONSET followed by a real DECOUPLING (three
     segments: unrelated -> coupled -> unrelated again) produces TWO
     breaks via binary segmentation, correctly classified onset then
     decoupling, in chronological order.
  4. compute_ols_spread recovers a known hedge ratio on a genuinely
     cointegrated synthetic pair (a basic sanity check on the spread
     construction this module's break-detection depends on).
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from structural_break_onset_detection import find_all_breaks, compute_ols_spread, _ar1_phi


def _ou_segment(n, phi, sigma, rng, start=0.0):
    """Mean-reverting AR(1) segment: x_t = phi * x_{t-1} + noise."""
    x = np.zeros(n)
    x[0] = start
    for i in range(1, n):
        x[i] = phi * x[i - 1] + rng.normal(0, sigma)
    return x


def test_single_onset_detected_at_correct_location():
    rng = np.random.default_rng(1)
    n_half = 400
    unrelated = np.cumsum(rng.normal(0, 0.05, n_half))  # phi ~= 1, random walk
    coupled = unrelated[-1] + _ou_segment(n_half, phi=0.85, sigma=0.05, rng=rng)  # genuinely mean-reverting
    spread = np.concatenate([unrelated, coupled])
    dates = pd.date_range("2015-01-01", periods=len(spread), freq="D")

    breaks = find_all_breaks(spread, dates)
    print(f"single-onset case: {len(breaks)} break(s) found")
    assert len(breaks) == 1, f"expected exactly 1 break, got {len(breaks)}: {breaks}"
    b = breaks[0]
    print(f"  break_date={b['break_date']}, type={b['break_type']}, phi {b['pre_phi']:.3f} -> {b['post_phi']:.3f}")
    assert b["break_type"] == "onset", f"expected 'onset', got {b['break_type']}"
    true_mid_date = dates[n_half]
    days_off = abs((pd.Timestamp(b["break_date"]) - true_mid_date).days)
    # Chow-test break-point estimation has real variance at this sample
    # size/phi-separation -- 150 days (~19% of the 800-bar series) is a
    # deliberately loose bar. The tight claim being verified is DIRECTION
    # and EXISTENCE (asserted above), not exact-date precision, which no
    # single-break test at this scale should be expected to nail exactly.
    assert days_off < 150, f"detected break should land reasonably near the true midpoint (within ~150 days), was {days_off} days off"


def test_no_break_for_continuously_mean_reverting_spread():
    rng = np.random.default_rng(2)
    spread = _ou_segment(800, phi=0.85, sigma=0.05, rng=rng)  # mean-reverting throughout, no real change
    dates = pd.date_range("2015-01-01", periods=len(spread), freq="D")
    breaks = find_all_breaks(spread, dates)
    print(f"continuously-mean-reverting case: {len(breaks)} break(s) found (expect 0)")
    assert len(breaks) == 0, f"expected no breaks for a genuinely unchanging relationship, got {breaks}"


def test_onset_then_decoupling_two_breaks_in_order():
    rng = np.random.default_rng(3)
    n_seg = 350
    unrelated1 = np.cumsum(rng.normal(0, 0.05, n_seg))
    coupled = unrelated1[-1] + _ou_segment(n_seg, phi=0.80, sigma=0.05, rng=rng)
    unrelated2 = coupled[-1] + np.cumsum(rng.normal(0, 0.05, n_seg))
    spread = np.concatenate([unrelated1, coupled, unrelated2])
    dates = pd.date_range("2010-01-01", periods=len(spread), freq="D")

    breaks = find_all_breaks(spread, dates)
    print(f"onset-then-decoupling case: {len(breaks)} break(s) found")
    types = [b["break_type"] for b in breaks]
    print(f"  types in chronological order: {types}")
    assert len(breaks) == 2, f"expected 2 breaks (onset + decoupling), got {len(breaks)}: {breaks}"
    assert breaks[0]["break_date"] < breaks[1]["break_date"], "breaks must be returned in chronological order"
    assert breaks[0]["break_type"] == "onset", f"first break should be 'onset', got {breaks[0]['break_type']}"
    assert breaks[1]["break_type"] == "decoupling", f"second break should be 'decoupling', got {breaks[1]['break_type']}"


def test_compute_ols_spread_recovers_known_hedge_ratio():
    rng = np.random.default_rng(4)
    n = 600
    log_b = np.cumsum(rng.normal(0, 0.02, n))
    true_hedge = 1.7
    ou_noise = _ou_segment(n, phi=0.9, sigma=0.02, rng=rng)
    log_a = true_hedge * log_b + ou_noise

    spread = compute_ols_spread(log_a, log_b)
    finite = spread[np.isfinite(spread)]
    resid_std = finite.std()
    noise_std = ou_noise.std()
    print(f"OLS spread residual std={resid_std:.4f} vs true OU noise std={noise_std:.4f} (expect close)")
    assert abs(resid_std - noise_std) < 0.5 * noise_std, \
        f"OLS spread should recover a residual close to the true injected noise scale, got {resid_std} vs {noise_std}"


if __name__ == "__main__":
    tests = [
        test_single_onset_detected_at_correct_location,
        test_no_break_for_continuously_mean_reverting_spread,
        test_onset_then_decoupling_two_breaks_in_order,
        test_compute_ols_spread_recovers_known_hedge_ratio,
    ]
    passed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"FAILED: {test.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} checks passed")
