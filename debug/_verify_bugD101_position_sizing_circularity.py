"""
Synthetic verification of BUG-D101: the position-sizing circularity found in
the 2026-07-27 causality audit. Four fields (coint_fraction_rolling,
half_life_trend_slope, mean_reversion_speed, hurst_rs) were single
whole-history scalars applied identically to every trade/training-example
for a pair regardless of entry date -- a window ending in 2024 was always
allowed to justify a trade's position size/ML features in 2015.

Fix: analysis.py now builds causal per-bar companions
(coint_fraction_rolling_t, half_life_trend_slope_t, mean_reversion_speed_t,
hurst_rs_t), persisted in spread_series parquet, read point-in-time by
backtest.py (position sizing + ML gate features + Trade.hurst_at_entry) and
ml.py (EntryEvent feature construction), scalar fallback when the per-bar
value is absent/NaN.

Three checks:
  1. Causality of the new estimator functions themselves (analysis.py):
     SpreadModel.expanding_half_life_trend_slope and
     HurstEstimator.expanding_hurst_rs -- past-bar values must not depend on
     future data (same technique as BUG-D99/BUG-D100's verify scripts).
  2. backtest.py wiring: two entries at well-separated times, with HAND-SET
     distinct causal per-bar values, must produce DIFFERENT ml_features and
     DIFFERENT n_shares_a (coint_frac_sizing) / hurst_at_entry -- not the
     same scalar for both.
  3. ml.py wiring: same idea via _build_examples_for_pair -- two entry
     events at different feat_pos must read different per-bar values.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from analysis import SpreadModel, HurstEstimator
from data import GapFlag
from config import Config

rng = np.random.default_rng(101)


def _check_causality_hl_slope(failures):
    n = 600
    cutoff = 300
    hl_shared_past = 20 + np.cumsum(rng.normal(scale=0.3, size=cutoff))
    hl_future_a = hl_shared_past[-1] + np.cumsum(rng.normal(scale=0.3, size=n - cutoff))
    hl_future_b = hl_shared_past[-1] + np.cumsum(rng.normal(loc=2.0, scale=0.3, size=n - cutoff))  # steep trend

    hl_a = np.concatenate([hl_shared_past, hl_future_a])
    hl_b = np.concatenate([hl_shared_past, hl_future_b])

    arr_a = SpreadModel.expanding_half_life_trend_slope(hl_a, step=21)
    arr_b = SpreadModel.expanding_half_life_trend_slope(hl_b, step=21)

    past_diff = np.nanmax(np.abs(arr_a[:cutoff] - arr_b[:cutoff]))
    if past_diff > 1e-9:
        failures.append(f"expanding_half_life_trend_slope: past values differ by {past_diff:.6f} depending on future data — not causal")
    future_diff = np.nanmax(np.abs(arr_a[cutoff:] - arr_b[cutoff:]))
    if future_diff < 0.01:
        failures.append(f"expanding_half_life_trend_slope: future divergence only {future_diff:.4f} — synthetic construction too weak")
    return arr_a, past_diff, future_diff


def _check_causality_hurst(failures):
    n = 600
    cutoff = 300
    shared_past = np.cumsum(rng.normal(scale=1.0, size=cutoff))
    # Mean-reverting future (anti-persistent increments) vs trending future
    future_meanrev = np.zeros(n - cutoff)
    for i in range(1, len(future_meanrev)):
        future_meanrev[i] = future_meanrev[i - 1] - 0.3 * future_meanrev[i - 1] + rng.normal(scale=0.5)
    future_trend = np.cumsum(rng.normal(loc=0.2, scale=0.3, size=n - cutoff))

    spread_a = np.concatenate([shared_past, shared_past[-1] + future_meanrev])
    spread_b = np.concatenate([shared_past, shared_past[-1] + future_trend])

    arr_a = HurstEstimator.expanding_hurst_rs(spread_a, step=21)
    arr_b = HurstEstimator.expanding_hurst_rs(spread_b, step=21)

    past_diff = np.nanmax(np.abs(arr_a[:cutoff] - arr_b[:cutoff]))
    if past_diff > 1e-9:
        failures.append(f"expanding_hurst_rs: past values differ by {past_diff:.6f} depending on future data — not causal")
    future_diff = np.nanmax(np.abs(arr_a[cutoff:] - arr_b[cutoff:]))
    if future_diff < 0.02:
        failures.append(f"expanding_hurst_rs: future divergence only {future_diff:.4f} — synthetic construction too weak")
    return past_diff, future_diff


def _build_synthetic_spread_df(n=500, early_entry=100, late_entry=400):
    """
    Hand-built spread_series-shaped DataFrame with DISTINCT, KNOWN causal
    per-bar values at two well-separated bars, plus a scalar pair_row whose
    fallback values are DIFFERENT from both -- if the code under test reads
    the scalar instead of the per-bar array, the captured features at the
    two entries would be IDENTICAL (both == scalar) instead of matching
    their own bar's per-bar value.
    """
    idx = pd.bdate_range("2019-01-02", periods=n, freq="B")
    z = np.zeros(n)
    z[early_entry] = 3.0
    z[early_entry + 1] = 0.1
    z[late_entry] = -3.0
    z[late_entry + 1] = -0.1
    hl = np.full(n, 20.0)
    gap = np.zeros(n)

    cfrac_t = np.full(n, np.nan)
    hlslope_t = np.full(n, np.nan)
    meanrev_t = np.full(n, np.nan)
    hurst_t = np.full(n, np.nan)
    cfrac_t[early_entry], cfrac_t[late_entry] = 0.85, 0.15
    hlslope_t[early_entry], hlslope_t[late_entry] = 0.02, -0.09
    meanrev_t[early_entry], meanrev_t[late_entry] = 0.05, 0.01
    hurst_t[early_entry], hurst_t[late_entry] = 0.20, 0.44

    df = pd.DataFrame(
        {
            "spread": rng.normal(scale=0.1, size=n),
            "z_rolling": z,
            "half_life_rolling": hl,
            "gap_flag_a": gap,
            "gap_flag_b": gap,
            "hedge_ratio_ols_t": np.full(n, 1.0),
            "hedge_ratio_kalman_t": np.full(n, 1.0),
            "coint_fraction_rolling_t": cfrac_t,
            "half_life_trend_slope_t": hlslope_t,
            "mean_reversion_speed_t": meanrev_t,
            "hurst_rs_t": hurst_t,
        },
        index=idx,
    )
    return df


def _check_backtest_wiring(failures):
    from backtest import BacktestEngine, RegimeConditioner, MLConditioner

    df = _build_synthetic_spread_df()
    pair_row = pd.Series({
        "symbol_a": "SYNA", "symbol_b": "SYNB", "tf_label": "1D",
        "hedge_ratio_ols": 1.0, "hedge_ratio_kalman_mean": 1.0,
        # Scalar fallbacks deliberately DIFFERENT from either per-bar value.
        "coint_fraction_rolling": 0.50, "half_life_trend_slope": -0.50,
        "mean_reversion_speed": 0.50, "hurst_rs": 0.50,
    })

    captured_ml_features = []
    engine = BacktestEngine(
        cfg=Config.BACKTEST,
        regime_cond=RegimeConditioner(enabled=False),
        ml_cond=MLConditioner(enabled=False),
        storm_flags={"coint_frac_sizing": True},
    )
    real_predict = engine.ml_cond.predict_prob

    def _capture_predict(features):
        captured_ml_features.append(dict(features))
        return real_predict(features)

    engine.ml_cond.predict_prob = _capture_predict

    trades = engine.run(pair_row, df, hedge_method="ols", holdout_only=False)

    if len(captured_ml_features) < 2:
        failures.append(f"backtest.py: expected >=2 entries, got {len(captured_ml_features)} — test construction issue")
        return
    if len(trades) < 2:
        failures.append(f"backtest.py: expected >=2 trades, got {len(trades)}")
        return

    f_early, f_late = captured_ml_features[0], captured_ml_features[1]

    checks = [
        ("coint_fraction_rolling", 0.85, 0.15),
        ("half_life_trend_slope", 0.02, -0.09),
        ("mean_reversion_speed", 0.05, 0.01),
        ("hurst_exponent", 0.20, 0.44),
    ]
    for key, expected_early, expected_late in checks:
        got_early, got_late = f_early.get(key), f_late.get(key)
        if got_early is None or abs(got_early - expected_early) > 1e-9:
            failures.append(f"backtest.py ml_features[{key}] at early entry = {got_early}, expected {expected_early} (per-bar value) — scalar fallback used instead?")
        if got_late is None or abs(got_late - expected_late) > 1e-9:
            failures.append(f"backtest.py ml_features[{key}] at late entry = {got_late}, expected {expected_late} (per-bar value) — scalar fallback used instead?")
        if got_early is not None and got_late is not None and abs(got_early - got_late) < 1e-9:
            failures.append(f"backtest.py ml_features[{key}]: early and late entries got the SAME value ({got_early}) — not reading per-bar data")

    # n_shares_a: coint_frac_sizing should scale the two trades differently
    # (0.85 vs 0.15 causal fraction), not identically.
    if len(trades) >= 2:
        n_early, n_late = trades[0].n_shares_a, trades[1].n_shares_a
        if n_early == n_late:
            failures.append(f"backtest.py: n_shares_a identical for early/late trades ({n_early}) despite coint_fraction_rolling_t=0.85 vs 0.15 — coint_frac_sizing not reading per-bar value")
        # hurst_at_entry on the Trade record itself (separate from ml_features)
        if abs(trades[0].hurst_at_entry - 0.20) > 1e-9:
            failures.append(f"backtest.py: Trade.hurst_at_entry (early) = {trades[0].hurst_at_entry}, expected 0.20")
        if abs(trades[1].hurst_at_entry - 0.44) > 1e-9:
            failures.append(f"backtest.py: Trade.hurst_at_entry (late) = {trades[1].hurst_at_entry}, expected 0.44")


def _check_ml_wiring(failures):
    from ml import _build_examples_for_pair, MLRunSummary

    df = _build_synthetic_spread_df()
    pair_row = pd.Series({
        "hedge_ratio_ols": 1.0, "hedge_ratio_kalman_mean": 1.0,
        "half_life_rolling": 20.0,
        "coint_fraction_rolling": 0.50, "half_life_trend_slope": -0.50,
        "mean_reversion_speed": 0.50, "hurst_rs": 0.50,
    })
    summary = MLRunSummary()
    events = _build_examples_for_pair("SYNA", "SYNB", "1D", pair_row, summary, series=df)

    if len(events) < 2:
        failures.append(f"ml.py: expected >=2 entry events, got {len(events)} — test construction issue")
        return

    e_early, e_late = events[0], events[1]
    checks = [
        ("coint_fraction_rolling", 0.85, 0.15),
        ("half_life_trend_slope", 0.02, -0.09),
        ("mean_reversion_speed", 0.05, 0.01),
        ("hurst_exponent", 0.20, 0.44),
    ]
    for attr, expected_early, expected_late in checks:
        got_early, got_late = getattr(e_early, attr), getattr(e_late, attr)
        if got_early is None or abs(got_early - expected_early) > 1e-9:
            failures.append(f"ml.py EntryEvent.{attr} at early entry = {got_early}, expected {expected_early}")
        if got_late is None or abs(got_late - expected_late) > 1e-9:
            failures.append(f"ml.py EntryEvent.{attr} at late entry = {got_late}, expected {expected_late}")


def main():
    failures = []

    _, past1, fut1 = _check_causality_hl_slope(failures)
    past2, fut2 = _check_causality_hurst(failures)
    _check_backtest_wiring(failures)
    _check_ml_wiring(failures)

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("BUG-D101 verification passed.")
    print(f"  expanding_half_life_trend_slope: past diff under differing futures = {past1:.2e}, future divergence = {fut1:.4f}")
    print(f"  expanding_hurst_rs: past diff under differing futures = {past2:.2e}, future divergence = {fut2:.4f}")
    print("  backtest.py: ml_features + n_shares_a + Trade.hurst_at_entry all read per-bar causal values")
    print("  ml.py: EntryEvent fields all read per-bar causal values at feat_pos")


if __name__ == "__main__":
    main()
