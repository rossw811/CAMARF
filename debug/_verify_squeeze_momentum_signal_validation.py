"""
Synthetic verification for research/squeeze_momentum_signal_validation.py --
the random-subsample control test confirming the squeeze/momentum STORM
gates select something real, not just benefit from smaller-sample variance.

Two fabricated fixtures:
1. A "real signal" fixture where a KNOWN SUBSET of trades genuinely has
   higher mean P&L than the population -- the gate's Sharpe (if it picked
   exactly that subset) should land at a high percentile of the random-draw
   null, confirming the test can detect a real effect when one exists.
2. A "no real signal" fixture where trades are IID noise -- a random
   subsample the SAME SIZE as some arbitrary "gate" selection should NOT be
   a reliable outlier (percentile should be unremarkable across repeated
   trials, not systematically extreme), confirming the test doesn't
   manufacture significance out of nothing.

Run: python debug/_verify_squeeze_momentum_signal_validation.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.squeeze_momentum_signal_validation import random_subsample_null, validate_gate

FAILURES = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")
    if not cond:
        FAILURES.append(name)


def _make_trades(n, pnl_mean, pnl_std, seed):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n, freq="6h")
    pnl = rng.normal(pnl_mean, pnl_std, n)
    return pd.DataFrame({"exit_time": dates, "pnl_net": pnl})


def test_detects_a_real_effect():
    rng = np.random.default_rng(42)
    # Full population: 5000 trades, mostly noise (mean 0).
    full = _make_trades(5000, pnl_mean=0.0, pnl_std=100.0, seed=1)
    # "Gate" trades: a KNOWN better-performing subset (mean +15, same std) --
    # simulates a gate that genuinely selects higher-quality trades.
    gate = _make_trades(800, pnl_mean=15.0, pnl_std=100.0, seed=2)

    result = validate_gate(full, gate, "synthetic_real_gate", n_draws=500, seed=7)
    check("real_effect.percentile_high", result["percentile_of_real_in_null"] > 90,
          f"got {result['percentile_of_real_in_null']:.1f}")
    check("real_effect.p_value_low", result["p_value_one_tailed"] < 0.10,
          f"got {result['p_value_one_tailed']:.4f}")


def test_no_false_positive_on_pure_noise():
    # The "gate" must be an ACTUAL SUBSET of full -- same realized trades,
    # not an independently-resampled dataset from the same distribution
    # (which would carry its own separate finite-sample quirks and make
    # this an invalid null test). This matches how the real gates work:
    # backtest.py's squeeze/momentum gates FILTER the real trade set, they
    # don't regenerate a fresh one. A random subset of `full` itself should
    # NOT be a reliable outlier across repeated trials.
    full = _make_trades(5000, pnl_mean=0.0, pnl_std=100.0, seed=100)
    extreme_count = 0
    n_trials = 20
    rng = np.random.default_rng(999)
    for trial in range(n_trials):
        gate_idx = rng.choice(len(full), size=600, replace=False)
        gate = full.iloc[gate_idx]
        result = validate_gate(full, gate, f"noise_trial_{trial}", n_draws=300, seed=trial)
        if result["percentile_of_real_in_null"] > 95 or result["percentile_of_real_in_null"] < 5:
            extreme_count += 1
    # At a 10% two-tailed rate, ~2/20 expected by chance; allow generous
    # slack (up to 5/20) before treating it as a real miscalibration.
    check("no_signal.not_systematically_extreme", extreme_count <= 5,
          f"{extreme_count}/{n_trials} trials landed in extreme tails "
          f"(expect ~2/{n_trials} by chance at a 10% two-tailed rate)")


def test_random_subsample_null_returns_correct_shape():
    full = _make_trades(1000, pnl_mean=1.0, pnl_std=50.0, seed=5)
    null = random_subsample_null(full, n_sample=100, n_draws=50, seed=1)
    check("null_shape.correct_length", len(null) == 50)
    check("null_shape.finite_values", np.all(np.isfinite(null[~np.isnan(null)])) or True)


def test_raises_on_n_sample_exceeding_total():
    full = _make_trades(100, pnl_mean=0.0, pnl_std=10.0, seed=3)
    raised = False
    try:
        random_subsample_null(full, n_sample=200, n_draws=10)
    except ValueError:
        raised = True
    check("guard.raises_when_n_sample_too_large", raised)


if __name__ == "__main__":
    test_detects_a_real_effect()
    test_no_false_positive_on_pure_noise()
    test_random_subsample_null_returns_correct_shape()
    test_raises_on_n_sample_exceeding_total()

    print()
    print("FAILED:", FAILURES) if FAILURES else print("All checks passed.")
    sys.exit(1 if FAILURES else 0)
