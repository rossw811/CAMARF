"""
Synthetic verification for research/cycle_detection.py (2026-08-02), before
trusting it on real pair data — matching this project's verify-before-trusting
discipline.

Checks:
  1. dominant_cycle() recovers a KNOWN period from a synthetic sinusoid +
     noise (within a reasonable tolerance for a discretized dyadic-ish
     period grid).
  2. rolling_plv() gives a HIGH PLV for two series with the same frequency
     and a constant phase offset, and a LOW PLV for two independent-
     frequency series — checks direction, not just a plausible range.
  3. rolling_plv() is CAUSAL: perturbing the signal strictly AFTER time t
     must not change plv[t]. This is the exact class of check this
     session's causality audit (BUG-D99-103) already established as
     mandatory for anything computed on a rolling/windowed basis.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from cycle_detection import dominant_cycle, rolling_plv, cross_timeframe_consistency


def test_dominant_cycle_recovers_known_period():
    rng = np.random.default_rng(0)
    n = 2000
    true_period = 40.0
    t = np.arange(n)
    signal = np.sin(2 * np.pi * t / true_period) + rng.normal(0, 0.3, n)
    result = dominant_cycle(signal)
    recovered = result["dominant_period_global"]
    print(f"true period=40.0 bars, recovered={recovered:.1f} bars")
    # Log-spaced grid of 40 points from 4 to n/4=500 -- allow generous
    # tolerance for discretization, not an exact match.
    assert 25 <= recovered <= 65, f"expected recovered period near 40, got {recovered}"


def test_plv_high_for_phase_locked_pair():
    rng = np.random.default_rng(1)
    n = 1000
    period = 30.0
    t = np.arange(n)
    phase_offset = 0.7  # constant offset -- should still phase-lock
    a = np.sin(2 * np.pi * t / period) + rng.normal(0, 0.05, n)
    b = np.sin(2 * np.pi * t / period + phase_offset) + rng.normal(0, 0.05, n)
    plv = rolling_plv(a, b, window=60)
    mean_plv = np.nanmean(plv)
    print(f"phase-locked pair (same freq, constant offset): mean PLV={mean_plv:.3f} (expect high, >0.8)")
    assert mean_plv > 0.8, f"expected high PLV for a phase-locked pair, got {mean_plv}"


def test_plv_low_for_independent_pair():
    rng = np.random.default_rng(2)
    n = 1000
    a = rng.normal(0, 1, n)  # white noise -- no periodicity at all
    b = rng.normal(0, 1, n)  # independent white noise
    plv = rolling_plv(a, b, window=60)
    mean_plv = np.nanmean(plv)
    print(f"independent white-noise pair: mean PLV={mean_plv:.3f} (expect low, <0.5)")
    assert mean_plv < 0.5, f"expected low PLV for independent series, got {mean_plv}"


def test_plv_direction_locked_beats_independent():
    """Checks the ESTIMATOR responds in the right direction, not just that
    each case individually lands in a plausible range."""
    rng = np.random.default_rng(3)
    n = 1000
    period = 25.0
    t = np.arange(n)
    a_locked = np.sin(2 * np.pi * t / period) + rng.normal(0, 0.05, n)
    b_locked = np.sin(2 * np.pi * t / period + 1.1) + rng.normal(0, 0.05, n)
    a_indep = rng.normal(0, 1, n)
    b_indep = rng.normal(0, 1, n)
    plv_locked = np.nanmean(rolling_plv(a_locked, b_locked, window=50))
    plv_indep = np.nanmean(rolling_plv(a_indep, b_indep, window=50))
    print(f"locked PLV={plv_locked:.3f} vs independent PLV={plv_indep:.3f}")
    assert plv_locked > plv_indep, "phase-locked pair should have strictly higher PLV than independent pair"


def test_plv_is_causal():
    """The exact causality check this session's audit (BUG-D99-103) applies
    everywhere: plv[t] for t < some cutoff must be IDENTICAL whether or not
    the signal is perturbed strictly after that cutoff."""
    rng = np.random.default_rng(4)
    n = 500
    window = 40
    period = 20.0
    t = np.arange(n)
    a = np.sin(2 * np.pi * t / period) + rng.normal(0, 0.05, n)
    b = np.sin(2 * np.pi * t / period + 0.5) + rng.normal(0, 0.05, n)

    cutoff = 300
    plv_before = rolling_plv(a.copy(), b.copy(), window)

    a_perturbed = a.copy()
    b_perturbed = b.copy()
    # Large perturbation strictly AFTER the cutoff -- must not leak backward.
    a_perturbed[cutoff + 1:] += 1000.0
    b_perturbed[cutoff + 1:] -= 1000.0
    plv_after = rolling_plv(a_perturbed, b_perturbed, window)

    pre_cutoff_before = plv_before[:cutoff + 1]
    pre_cutoff_after = plv_after[:cutoff + 1]
    matches = np.allclose(pre_cutoff_before, pre_cutoff_after, equal_nan=True)
    print(f"causal check: plv[:{cutoff + 1}] unchanged after future perturbation: {matches}")
    assert matches, "rolling_plv leaked future information into a past value -- NOT causal"


def test_cross_timeframe_consistency_basic():
    # Same true calendar-day period expressed in different bar units should
    # report as consistent.
    cons_same = cross_timeframe_consistency(period_a_bars=6.5 * 5, tf_a="1hr",
                                             period_b_bars=5, tf_b="1day")
    print(f"same-period-in-days case: {cons_same}")
    assert cons_same["consistent_within_2x"] is True

    cons_diff = cross_timeframe_consistency(period_a_bars=6.5, tf_a="1hr",
                                             period_b_bars=100, tf_b="1day")
    print(f"very-different-period case: {cons_diff}")
    assert cons_diff["consistent_within_2x"] is False


if __name__ == "__main__":
    test_dominant_cycle_recovers_known_period()
    test_plv_high_for_phase_locked_pair()
    test_plv_low_for_independent_pair()
    test_plv_direction_locked_beats_independent()
    test_plv_is_causal()
    test_cross_timeframe_consistency_basic()
    print("\nAll cycle_detection.py synthetic checks passed.")
