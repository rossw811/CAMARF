"""
debug/_verify_beta_weighted_portfolio.py -- synthetic checks for
research/beta_weighted_portfolio.py, BEFORE trusting it against real production trades/SPY data.

Run: python debug/_verify_beta_weighted_portfolio.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.beta_weighted_portfolio import (
    rolling_beta, value_at_date, trade_net_dollar_beta_exposure, build_daily_net_exposure,
    hedge_overlay_daily_pnl,
)

passed = 0
failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}")
        failed += 1


print("Check 1: rolling_beta -- recovers a KNOWN injected beta exactly (asset return = "
      "beta * market return + independent noise)")
rng = np.random.default_rng(0)
n = 300
idx = pd.date_range("2024-01-01", periods=n, freq="D")
market_ret = pd.Series(rng.normal(0, 0.01, n), index=idx)
true_beta = 1.5
asset_ret = true_beta * market_ret + pd.Series(rng.normal(0, 0.001, n), index=idx)
beta_series = rolling_beta(asset_ret, market_ret, window=63)
check(f"recovered beta at the end of the series ({beta_series.iloc[-1]:.3f}) is close to the "
      f"true injected beta ({true_beta})", abs(beta_series.iloc[-1] - true_beta) < 0.1)
check("first 62 values are NaN (window not yet filled) -- causal, no lookahead",
      beta_series.iloc[:62].isna().all())

print("Check 2: value_at_date -- causal 'pad' lookup, never returns a value from AFTER the "
      "requested date (the exact lookahead risk this function exists to prevent)")
series2 = pd.Series([1.0, 2.0, 3.0], index=pd.to_datetime(["2024-01-01", "2024-01-05", "2024-01-10"]))
check("a date between two index points returns the EARLIER value (pad), not the later one",
      value_at_date(series2, "2024-01-07") == 2.0)
check("a date before the series starts returns NaN, not a fabricated extrapolation",
      np.isnan(value_at_date(series2, "2023-12-01")))

print("Check 3: trade_net_dollar_beta_exposure -- a LONG trade with EQUAL leg betas has ZERO "
      "net exposure (the market-neutral case pairs trading is theoretically supposed to "
      "achieve when both legs really do move together with the market)")
beta_a = pd.Series([1.0], index=[pd.Timestamp("2024-01-01")])
beta_b = pd.Series([1.0], index=[pd.Timestamp("2024-01-01")])
exposure_neutral = trade_net_dollar_beta_exposure(
    "A", "B", "2024-01-01", price_a=100.0, price_b=100.0, n_shares_a=10, n_shares_b=10,
    side="long", beta_a_series=beta_a, beta_b_series=beta_b)
check(f"equal betas + equal dollar notional -> zero net exposure ({exposure_neutral:.6f})",
      abs(exposure_neutral) < 1e-9)

print("Check 4: trade_net_dollar_beta_exposure -- a LONG trade with UNEQUAL leg betas has a "
      "real, nonzero net exposure, correctly signed (higher-beta long leg -> net LONG the "
      "market)")
beta_a_high = pd.Series([1.5], index=[pd.Timestamp("2024-01-01")])
beta_b_low = pd.Series([0.5], index=[pd.Timestamp("2024-01-01")])
exposure_mismatch = trade_net_dollar_beta_exposure(
    "A", "B", "2024-01-01", price_a=100.0, price_b=100.0, n_shares_a=10, n_shares_b=10,
    side="long", beta_a_series=beta_a_high, beta_b_series=beta_b_low)
check(f"long the high-beta leg, short the low-beta leg -> positive (net long-market) exposure "
      f"({exposure_mismatch:.2f})", exposure_mismatch > 0)

print("Check 5: trade_net_dollar_beta_exposure -- missing beta history returns NaN, not a "
      "fabricated zero")
check("empty beta series -> NaN exposure, not a silent zero",
      np.isnan(trade_net_dollar_beta_exposure(
          "A", "B", "2024-01-01", 100.0, 100.0, 10, 10, "long",
          pd.Series(dtype=float), pd.Series(dtype=float))))

print("Check 6: build_daily_net_exposure -- a trade's exposure appears on every day it is open, "
      "and disappears (returns to the pre-trade baseline) the day after it exits -- a second, "
      "later trade extends the tracked date range far enough to observe the reset")
trades6 = pd.DataFrame({
    "entry_time": [pd.Timestamp("2024-01-05"), pd.Timestamp("2024-01-20")],
    "exit_time": [pd.Timestamp("2024-01-10"), pd.Timestamp("2024-01-25")],
    "net_dollar_beta_exposure": [500.0, 0.0],  # second trade's own exposure is 0 -- present only
})                                              # to extend the tracked date range past trade 1's exit+1
daily6 = build_daily_net_exposure(trades6)
check("exposure is 500 on the entry date", daily6.loc["2024-01-05"] == 500.0)
check("exposure is still 500 on the exit date itself (still open that day)",
      daily6.loc["2024-01-10"] == 500.0)
check("exposure returns to 0 the day AFTER exit", daily6.loc["2024-01-11"] == 0.0)

print("Check 6b: build_daily_net_exposure -- INTRADAY entry/exit times (real trades from "
      "sub-daily timeframes, e.g. '2023-10-02 14:00:00' for a 1h trade) don't crash with a "
      "KeyError -- real bug found live: pd.date_range's start/end weren't normalized to "
      "midnight, so every generated day carried the SAME intraday offset as the first trade's "
      "entry time, never matching normalize()'d lookups")
trades6b = pd.DataFrame({
    "entry_time": [pd.Timestamp("2023-10-02 14:00:00"), pd.Timestamp("2023-10-15 09:30:00")],
    "exit_time": [pd.Timestamp("2023-10-05 10:00:00"), pd.Timestamp("2023-10-20 16:00:00")],
    "net_dollar_beta_exposure": [200.0, 100.0],
})
daily6b = build_daily_net_exposure(trades6b)  # must not raise
check("intraday entry/exit times don't crash, and produce a real, midnight-aligned daily index",
      len(daily6b) > 0 and (daily6b.index == daily6b.index.normalize()).all())
check("exposure on the first trade's entry DATE (ignoring its 14:00 time) is 200",
      daily6b.loc["2023-10-02"] == 200.0)

print("Check 7: build_daily_net_exposure -- two OVERLAPPING trades' exposures correctly sum, "
      "not overwrite each other")
trades7 = pd.DataFrame({
    "entry_time": [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-03")],
    "exit_time": [pd.Timestamp("2024-01-10"), pd.Timestamp("2024-01-05")],
    "net_dollar_beta_exposure": [300.0, -100.0],
})
daily7 = build_daily_net_exposure(trades7)
check("both trades open on 2024-01-04 -> exposure sums to 300 + (-100) = 200",
      daily7.loc["2024-01-04"] == 200.0)
check("only the first trade open on 2024-01-06 (second already exited) -> exposure is 300",
      daily7.loc["2024-01-06"] == 300.0)

print("Check 8: hedge_overlay_daily_pnl -- an offsetting SPY position with an EXACT-opposite "
      "return exactly cancels the net exposure's dollar P&L (the defining property of a "
      "correctly-sized hedge)")
exposure8 = pd.Series([1000.0, -500.0], index=pd.date_range("2024-01-01", periods=2, freq="D"))
spy_ret8 = pd.Series([0.02, -0.01], index=exposure8.index)
hedge_pnl8 = hedge_overlay_daily_pnl(exposure8, spy_ret8)
check(f"hedge P&L on day 1 exactly offsets the $1000 exposure's own market move "
      f"({hedge_pnl8.iloc[0]:.2f} should be -1000*0.02=-20.00)", np.isclose(hedge_pnl8.iloc[0], -20.0))
check(f"hedge P&L on day 2 exactly offsets the -$500 exposure's own market move "
      f"({hedge_pnl8.iloc[1]:.2f} should be -(-500)*-0.01=-5.00)", np.isclose(hedge_pnl8.iloc[1], -5.0))

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
