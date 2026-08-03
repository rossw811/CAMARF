"""
Synthetic verification of BUG-D99: pit_wfa.py's BUG-D69 point-in-time
override dict (backtest_pair_on_test_window) was missing `hurst_rs` — 3 of 4
scalar fields (coint_fraction_rolling, half_life_trend_slope,
mean_reversion_speed) were overridden with the genuinely train-only
pair_result's values, but hurst_rs silently leaked full_pair_result's
train+test-contaminated value instead.

Construction: a synthetic spread that is strongly MEAN-REVERTING (OU-like,
low Hurst) throughout the train window, then switches to a strongly
TRENDING/persistent regime (high Hurst) for the test window. A train-only
Hurst estimate and a train+test-combined Hurst estimate should therefore
differ by a real, non-trivial margin — if they didn't, this test wouldn't
actually be exercising the bug.

Verifies: the pair_row fed into BacktestEngine.run() carries the train-only
hurst_rs, not the train+test-combined one.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import pit_wfa
from analysis import AnalysisPipeline
from data import GapFlag

rng = np.random.default_rng(99)


def _make_leg_frame(close, idx):
    return pd.DataFrame(
        {"close": close, "gap_flag": np.full(len(idx), GapFlag.NONE)}, index=idx
    )


def main():
    failures = []

    n_train = 400
    n_test = 200
    n = n_train + n_test
    idx = pd.bdate_range("2018-01-02", periods=n, freq="B")

    # Train window: OU-like mean-reverting spread (log_a - log_b reverts to 0).
    theta, sigma = 0.08, 0.5
    spread = np.zeros(n)
    for i in range(1, n_train):
        spread[i] = spread[i - 1] - theta * spread[i - 1] + rng.normal(scale=sigma)

    # Test window: strongly trending/persistent (near-random-walk / trending),
    # a regime with materially higher Hurst than the train-window OU process.
    trend = np.cumsum(rng.normal(loc=0.15, scale=0.3, size=n_test))
    spread[n_train:] = spread[n_train - 1] + trend

    base_a = 100 + np.cumsum(rng.normal(scale=0.05, size=n))
    log_a = np.log(base_a)
    log_b = log_a - spread
    close_a = np.exp(log_a)
    close_b = np.exp(log_b)

    full_universe = {
        "SYNA": _make_leg_frame(close_a, idx),
        "SYNB": _make_leg_frame(close_b, idx),
    }

    train_start, train_end = idx[0], idx[n_train - 1]
    test_start, test_end = idx[n_train], idx[-1]

    # Genuine train-only PairResult (what screen_universe_at_cutoff would produce).
    train_only = {
        sym: df.loc[df.index <= train_end] for sym, df in full_universe.items()
    }
    built_train = AnalysisPipeline._build_pair_result(
        {"symbol_a": "SYNA", "symbol_b": "SYNB"}, train_only, "1D"
    )
    if built_train is None:
        failures.append("train-only _build_pair_result returned None — test construction bug")
        print("FAILURES:", failures)
        sys.exit(1)
    pair_result_train_only, _ = built_train

    # Train+test combined, for reference/contrast (what full_pair_result would be).
    built_full = AnalysisPipeline._build_pair_result(
        {"symbol_a": "SYNA", "symbol_b": "SYNB"}, full_universe, "1D"
    )
    pair_result_full, _ = built_full

    train_hurst = pair_result_train_only.hurst_rs
    full_hurst = pair_result_full.hurst_rs
    if not (np.isfinite(train_hurst) and np.isfinite(full_hurst)):
        failures.append(f"non-finite hurst_rs (train={train_hurst}, full={full_hurst}) — test construction bug")
    elif abs(train_hurst - full_hurst) < 0.03:
        failures.append(
            f"train-only hurst_rs ({train_hurst:.4f}) and train+test hurst_rs "
            f"({full_hurst:.4f}) are too close — synthetic construction doesn't "
            "actually distinguish the two windows, test wouldn't catch the bug"
        )

    # Capture the pair_row actually fed to BacktestEngine.run().
    captured = {}
    real_run = pit_wfa.BacktestEngine.run

    def _capture_run(self, pair_row, *args, **kwargs):
        captured["hurst_rs"] = pair_row.get("hurst_rs")
        return []

    pit_wfa.BacktestEngine.run = _capture_run
    try:
        pit_wfa.backtest_pair_on_test_window(
            pair_result_train_only, full_universe, train_start, test_start, test_end
        )
    finally:
        pit_wfa.BacktestEngine.run = real_run

    if "hurst_rs" not in captured:
        failures.append("BacktestEngine.run was never called — backtest_pair_on_test_window short-circuited before reaching the pair_row construction (check test-window length/alignment)")
    else:
        got = captured["hurst_rs"]
        if got is None or not np.isfinite(got):
            failures.append(f"pair_row['hurst_rs'] missing/non-finite: {got}")
        elif abs(got - train_hurst) > 1e-9:
            failures.append(
                f"LOOKAHEAD BUG: pair_row['hurst_rs']={got:.4f} does not match the "
                f"genuine train-only value ({train_hurst:.4f}) — BUG-D99 not fixed."
            )
        if got is not None and np.isfinite(got) and abs(got - full_hurst) < 1e-9:
            failures.append(
                f"pair_row['hurst_rs']={got:.4f} matches the train+test-CONTAMINATED "
                f"value ({full_hurst:.4f}) instead of the train-only one — override not applied."
            )

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("BUG-D99 verification passed.")
    print(f"  train-only hurst_rs = {train_hurst:.4f}")
    print(f"  train+test hurst_rs = {full_hurst:.4f}")
    print(f"  pair_row['hurst_rs'] (post-fix) = {captured['hurst_rs']:.4f} (matches train-only, not contaminated)")


if __name__ == "__main__":
    main()
