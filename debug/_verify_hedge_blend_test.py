"""
debug/_verify_hedge_blend_test.py -- synthetic ground-truth checks for
research/hedge_blend_test.py, BEFORE trusting it against real production trades/universe data.

Run: python debug/_verify_hedge_blend_test.py
(Fully synthetic/offline -- no real data or WRDS connection needed.)
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.hedge_blend_test import pair_strategy_daily_returns, blend_and_evaluate

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


print("Check 1: pair_strategy_daily_returns -- correctly resamples trade-level pnl_net to a "
      "DAILY return series, dividing by starting_capital, using exit_time (falling back to "
      "entry_time only when exit_time is missing)")
trades = pd.DataFrame({
    "pnl_net": [1000.0, -500.0, 2000.0],
    "entry_time": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-05"]),
    "exit_time": pd.to_datetime(["2024-01-02", "2024-01-02", "2024-01-05"]),
})
r1 = pair_strategy_daily_returns(trades, starting_capital=100_000)
check("2024-01-02 aggregates both trades that exited that day (1000 - 500 = 500, /100000 = 0.005)",
      np.isclose(r1.loc["2024-01-02"], 0.005))
check("2024-01-05's single trade correctly shows 2000/100000 = 0.02",
      np.isclose(r1.loc["2024-01-05"], 0.02))
check("2024-01-03/04 (no exits, but within the resampled calendar range) are filled with 0, "
      "not dropped or NaN", r1.loc["2024-01-03"] == 0.0 and r1.loc["2024-01-04"] == 0.0)

print("Check 2: blend_and_evaluate -- weight=1.0 reproduces the PURE pair-return series exactly "
      "(the with/without baseline, hedge contributes nothing)")
pair_ret = pd.Series([0.01, -0.02, 0.015, 0.005, -0.01] * 20,
                      index=pd.date_range("2024-01-01", periods=100, freq="D"))
hedge_ret = pd.Series(np.random.default_rng(0).normal(0, 0.03, 100),
                       index=pd.date_range("2024-01-01", periods=100, freq="D"))
r2_pure = blend_and_evaluate(pair_ret, hedge_ret, weight=1.0)
manual_sharpe = float(pair_ret.mean() / pair_ret.std() * np.sqrt(252))
check(f"weight=1.0's Sharpe ({r2_pure['sharpe']:.4f}) exactly matches the pure pair-return "
      f"series' own Sharpe ({manual_sharpe:.4f})", np.isclose(r2_pure["sharpe"], manual_sharpe))

print("Check 3: blend_and_evaluate -- blending in a NEGATIVELY-CORRELATED hedge reduces "
      "volatility relative to the pure pair-only baseline (the real diversification-benefit "
      "case this test is designed to detect)")
rng = np.random.default_rng(1)
base_noise = rng.normal(0, 0.02, 200)
idx = pd.date_range("2024-01-01", periods=200, freq="D")
pair_ret3 = pd.Series(base_noise + 0.001, index=idx)
hedge_ret3 = pd.Series(-base_noise, index=idx)  # perfectly anti-correlated with the pair strategy
r3_pure = blend_and_evaluate(pair_ret3, hedge_ret3, weight=1.0)
r3_blend = blend_and_evaluate(pair_ret3, hedge_ret3, weight=0.5)
check(f"a 50/50 blend with a perfectly anti-correlated hedge has LOWER volatility "
      f"({r3_blend['volatility']:.6f}) than the pure pair-only baseline ({r3_pure['volatility']:.6f})",
      r3_blend["volatility"] < r3_pure["volatility"])

print("Check 4: blend_and_evaluate -- the hedge return series is correctly reindexed onto the "
      "PAIR strategy's own dates (not the other way around) -- a hedge date with no matching "
      "pair-strategy date contributes nothing")
pair_dates = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
pair_vals = [0.01, 0.02, 0.0, 0.01, -0.005]
pair_ret4 = pd.Series(pair_vals, index=pair_dates)
hedge_dates = pd.to_datetime(list(pair_dates) + ["2024-01-06"])
hedge_ret4 = pd.Series([0.05] * 5 + [0.05], index=hedge_dates)
r4 = blend_and_evaluate(pair_ret4, hedge_ret4, weight=0.5)
# 2024-01-06 exists only in the hedge series and must NOT enter the blend at all.
manual_mean = float(np.mean([0.5 * v + 0.5 * 0.05 for v in pair_vals]))
check(f"blended mean ({r4['mean_daily_return']:.5f}) matches manual computation over the "
      f"pair strategy's own 2 dates only, not 3 ({manual_mean:.5f})",
      np.isclose(r4["mean_daily_return"], manual_mean))

print("Check 5: blend_and_evaluate -- too few observations (or zero-variance blend) returns "
      "NaN rather than a fabricated Sharpe")
tiny = pd.Series([0.01, 0.02], index=pd.date_range("2024-01-01", periods=2, freq="D"))
r5 = blend_and_evaluate(tiny, tiny, weight=1.0)
check("fewer than 5 observations -> NaN Sharpe, not a fabricated value from too little data",
      np.isnan(r5["sharpe"]))

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
