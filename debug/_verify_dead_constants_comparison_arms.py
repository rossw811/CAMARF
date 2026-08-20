"""
Verifies the 3 backtest.py-level comparison arms added 2026-08-14: two from
Thread G-Full's dead-constant follow-up (max_half_life_filter, real_corr_exit)
plus liquidity_bar_filter (Ross's direct instruction: "skip trades and avoid
use of illiquid bars"). Runs the REAL BacktestEngine.run() (not a
re-implemented copy of the logic), same harness pattern as
debug/_verify_bug_d56_compose.py.

(concentration_cap/leverage_cap, the portfolio-level arms, are verified
separately in debug/_verify_flat_risk_pct_override.py -- portfolio_sim.py-
level behavior, not a per-pair BacktestEngine one.)

Checks:
  1. max_half_life_filter: a pair whose half_life_rolling is above MAX_HALF_LIFE
     at the only bar clearing ENTRY_ZSCORE produces ZERO trades when the flag
     is on, but a normal trade when it's off (baseline unaffected).
  2. real_corr_exit: a position held with coint_fraction_rolling_t dropping
     below CORR_EXIT_THRESHOLD mid-hold (while z stays within safe bounds,
     not triggering stop/signal/z-widening exits) closes with exit_reason
     "real_corr_exit" exactly at that bar when the flag is on, but stays open
     to end-of-series ("eod") when it's off.
  3. liquidity_bar_filter: a pair whose ONLY entry-qualifying bar coincides
     with one leg being individually illiquid (own dollar volume below
     MIN_DOLLAR_VOLUME) produces ZERO trades when the flag is on, but a
     normal trade when it's off.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from backtest import BacktestEngine, RegimeConditioner, MLConditioner
from config import Config


def build_pair_row():
    return pd.Series({
        "symbol_a": "TESTA", "symbol_b": "TESTB", "tf_label": "1h",
        "hedge_ratio_ols": 1.0, "hedge_ratio_kalman_mean": 1.0,
        "hurst_rs": 0.4, "coint_fraction_rolling": 0.5,
    })


def run_case(spread_df, storm_flags):
    engine = BacktestEngine(
        cfg=Config.BACKTEST,
        regime_cond=RegimeConditioner(enabled=False),
        ml_cond=MLConditioner(enabled=False),
        storm_flags=storm_flags,
    )
    return engine.run(build_pair_row(), spread_df, hedge_method="ols")


def build_max_half_life_df():
    n = 100
    idx = pd.date_range("2024-01-01 09:30", periods=n, freq="1h")
    z = np.full(n, 0.3)
    z[60] = 2.5  # the ONLY bar clearing ENTRY_ZSCORE=2.0
    spread = np.zeros(n)
    # Deliberately ABOVE MAX_HALF_LIFE (default 50) but still >= MIN_HALF_LIFE_BARS
    # (default 5) -- clears the EXISTING floor filter, only the NEW ceiling should stop it.
    hl = np.full(n, 80.0)
    return pd.DataFrame({
        "z_rolling": z, "spread": spread, "half_life_rolling": hl,
        "gap_flag_a": 0, "gap_flag_b": 0,
    }, index=idx)


def build_real_corr_exit_df():
    n = 100
    idx = pd.date_range("2024-01-01 09:30", periods=n, freq="1h")
    z = np.full(n, 0.3)
    z[60] = 2.5  # entry (short side)
    # Hold z within a SAFE band after entry (not >= STOP_ZSCORE=3.5, not <= EXIT_ZSCORE=0.0,
    # not > 2.0x entry_z=5.0 which would trigger the existing z-widening corr_exit heuristic).
    z[61:] = 1.0
    spread = np.zeros(n)
    hl = np.full(n, 20.0)  # MAX_HOLD_MULTIPLIER=2.0 * 20 = 40 bars -> triggers ~bar 100, safely late
    cfrac = np.full(n, 0.5)  # comfortably above CORR_EXIT_THRESHOLD=0.20 everywhere by default
    cfrac[70] = 0.05  # drops below threshold at bar 70, well within the hold window
    return pd.DataFrame({
        "z_rolling": z, "spread": spread, "half_life_rolling": hl,
        "gap_flag_a": 0, "gap_flag_b": 0,
        "coint_fraction_rolling_t": cfrac,
    }, index=idx)


def build_liquidity_bar_filter_df():
    """DAILY frequency, matching liquid_bar_mask's own daily-cache assumption
    (liquid_bar_mask reads {symbol}_1day.parquet, reindexed against the
    spread_series' own index -- an hourly index wouldn't align)."""
    n = 100
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    z = np.full(n, 0.3)
    z[60] = 2.5  # the ONLY bar clearing ENTRY_ZSCORE=2.0
    spread = np.zeros(n)
    hl = np.full(n, 20.0)
    return idx, pd.DataFrame({
        "z_rolling": z, "spread": spread, "half_life_rolling": hl,
        "gap_flag_a": 0, "gap_flag_b": 0,
    }, index=idx)


def _write_price_cache(symbol, idx, illiquid_bar_positions):
    """Writes a real {symbol}_1day.parquet with close/volume such that bars
    at illiquid_bar_positions have dollar volume BELOW MIN_DOLLAR_VOLUME,
    every other bar comfortably above it."""
    n = len(idx)
    closes = np.full(n, 50.0)
    volumes = np.full(n, Config.DATA.MIN_DOLLAR_VOLUME / 50.0 * 10)  # 10x threshold, comfortably liquid
    for pos in illiquid_bar_positions:
        volumes[pos] = 100.0  # dollar_vol = 50*100 = 5,000, far below any real threshold
    df = pd.DataFrame({"open": closes, "high": closes, "low": closes,
                        "close": closes, "volume": volumes}, index=idx)
    path = os.path.join(Config.DATA.CACHE_DIR, f"{symbol}_1day.parquet")
    df.to_parquet(path)
    return path


def main():
    failures = []

    # --- Check 1: max_half_life_filter ---
    df1 = build_max_half_life_df()
    trades_off = run_case(df1, {})
    trades_on = run_case(df1, {"max_half_life_filter": True})
    if not trades_off:
        failures.append("Check 1: baseline (flag off) should produce a trade at the only "
                         "entry-qualifying bar -- fixture needs adjustment")
    if trades_on:
        failures.append(f"Check 1: flag ON should SKIP entry (half_life_rolling=80 > "
                         f"MAX_HALF_LIFE={Config.BACKTEST.MAX_HALF_LIFE}), but got "
                         f"{len(trades_on)} trade(s)")

    # --- Check 2: real_corr_exit ---
    df2 = build_real_corr_exit_df()
    trades_off2 = run_case(df2, {})
    trades_on2 = run_case(df2, {"real_corr_exit": True})
    if not trades_off2 or trades_off2[0].exit_reason != "eod":
        failures.append(f"Check 2: baseline (flag off) should hold to end-of-series (exit_reason="
                         f"'eod'), got {trades_off2[0].exit_reason if trades_off2 else 'no trade'}")
    if not trades_on2 or trades_on2[0].exit_reason != "real_corr_exit":
        failures.append(f"Check 2: flag ON should exit via 'real_corr_exit' when "
                         f"coint_fraction_rolling_t drops below CORR_EXIT_THRESHOLD, got "
                         f"{trades_on2[0].exit_reason if trades_on2 else 'no trade'}")
    elif trades_on2[0].exit_time != df2.index[70]:
        failures.append(f"Check 2: expected exit exactly at the bar coint_fraction drops "
                         f"({df2.index[70]}), got {trades_on2[0].exit_time}")

    # --- Check 3: liquidity_bar_filter ---
    idx3, df3 = build_liquidity_bar_filter_df()
    pair_row3 = pd.Series({
        "symbol_a": "TESTLIQA", "symbol_b": "TESTLIQB", "tf_label": "1D",
        "hedge_ratio_ols": 1.0, "hedge_ratio_kalman_mean": 1.0,
        "hurst_rs": 0.4, "coint_fraction_rolling": 0.5,
    })
    path_a = path_b = None
    try:
        # TESTLIQA illiquid exactly at bar 60 (the only entry-qualifying bar); TESTLIQB liquid throughout.
        path_a = _write_price_cache("TESTLIQA", idx3, illiquid_bar_positions=[60])
        path_b = _write_price_cache("TESTLIQB", idx3, illiquid_bar_positions=[])

        def run_case3(storm_flags):
            engine = BacktestEngine(
                cfg=Config.BACKTEST, regime_cond=RegimeConditioner(enabled=False),
                ml_cond=MLConditioner(enabled=False), storm_flags=storm_flags,
            )
            return engine.run(pair_row3, df3, hedge_method="ols")

        trades_off3 = run_case3({})
        trades_on3 = run_case3({"liquidity_bar_filter": True})
        if not trades_off3:
            failures.append("Check 3: baseline (flag off) should produce a trade at the only "
                             "entry-qualifying bar -- fixture needs adjustment")
        if trades_on3:
            failures.append(f"Check 3: flag ON should SKIP entry (TESTLIQA illiquid at the "
                             f"entry-qualifying bar), but got {len(trades_on3)} trade(s)")
    finally:
        for p in (path_a, path_b):
            if p and os.path.exists(p):
                os.remove(p)

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All dead-constant comparison-arm checks passed.")
    print(f"  Check 1: max_half_life_filter -- flag off: {len(trades_off)} trade(s), "
          f"flag on: {len(trades_on)} trade(s) (correctly skipped)")
    print(f"  Check 2: real_corr_exit -- flag off exit_reason={trades_off2[0].exit_reason}, "
          f"flag on exit_reason={trades_on2[0].exit_reason} at {trades_on2[0].exit_time}")
    print(f"  Check 3: liquidity_bar_filter -- flag off: {len(trades_off3)} trade(s), "
          f"flag on: {len(trades_on3)} trade(s) (correctly skipped)")


if __name__ == "__main__":
    main()
