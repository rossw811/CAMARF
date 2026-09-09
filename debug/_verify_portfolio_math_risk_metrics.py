"""
debug/_verify_portfolio_math_risk_metrics.py -- synthetic checks for portfolio_math.py's new
Sortino/rolling-Sharpe/Calmar/M2 metrics (added 2026-09-07, Ross's queued risk-metrics item).

Run: python debug/_verify_portfolio_math_risk_metrics.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from portfolio_math import (
    downside_deviation, sortino_from_daily_pnl, rolling_sharpe, calmar_from_daily_pnl, m2_ratio,
    sharpe_from_daily_pnl,
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


print("Check 1: downside_deviation -- only counts observations BELOW the MAR, matching the "
      "textbook semi-deviation formula, not std() of just the negative subset")
idx = pd.date_range("2024-01-01", periods=6, freq="D")
pnl1 = pd.Series([10.0, -5.0, 20.0, -10.0, 0.0, 5.0], index=idx)
dd1 = downside_deviation(pnl1, mar=0.0)
manual_dd1 = np.sqrt(np.mean(np.minimum(pnl1.to_numpy(), 0.0) ** 2))
check(f"downside_deviation ({dd1:.4f}) matches manual semi-deviation computation ({manual_dd1:.4f})",
      abs(dd1 - manual_dd1) < 1e-9)

print("Check 2: sortino_from_daily_pnl -- a series with LARGE gains and SMALL losses shows a "
      "higher Sortino than Sharpe (Sortino ignores upside variance, Sharpe penalizes it)")
rng = np.random.default_rng(0)
n = 300
idx2 = pd.date_range("2024-01-01", periods=n, freq="D")
# Asymmetric: big positive tail, small negative tail -- exactly the case Sortino is meant to reward.
pnl2 = pd.Series(np.where(rng.random(n) < 0.6, rng.uniform(50, 200, n), -rng.uniform(1, 20, n)), index=idx2)
sharpe2 = sharpe_from_daily_pnl(pnl2)
sortino2 = sortino_from_daily_pnl(pnl2)
check(f"Sortino ({sortino2:.3f}) is materially higher than Sharpe ({sharpe2:.3f}) for this "
      f"upside-skewed series", sortino2 > sharpe2)

print("Check 3: rolling_sharpe -- produces NaN before the window fills (min_periods=window by "
      "default), then a real, finite value once it does")
pnl3 = pd.Series(rng.normal(10, 5, 100), index=pd.date_range("2024-01-01", periods=100, freq="D"))
roll = rolling_sharpe(pnl3, window=30)
check("first 29 values are NaN (window not yet filled)", roll.iloc[:29].isna().all())
check("value at index 29 (30th observation, window just filled) is finite",
      np.isfinite(roll.iloc[29]))
check("rolling_sharpe matches a manual computation at one spot-checked point (index 60)",
      np.isclose(roll.iloc[60],
                  pnl3.iloc[31:61].mean() / pnl3.iloc[31:61].std() * np.sqrt(252)))

print("Check 4: calmar_from_daily_pnl -- matches portfolio_sim.py's own calmar_from_replay() "
      "on the SAME underlying trade data, confirming no drift between the two implementations")
import portfolio_sim
trades_df = pd.DataFrame({
    "symbol_a": ["A"] * 10, "symbol_b": ["B"] * 10, "tf": ["1D"] * 10,
    "entry_time": pd.date_range("2024-01-01", periods=10, freq="10D"),
    "exit_time": pd.date_range("2024-01-05", periods=10, freq="10D"),
    "entry_spread": [1.0] * 10, "entry_z": [3.0] * 10, "half_life_at_entry": [10.0] * 10,
    "side": ["long"] * 10, "n_shares_a": [100] * 10, "n_shares_b": [100.0] * 10,
    "pnl_net": [500.0, -200.0, 800.0, -100.0, 300.0, -400.0, 600.0, -150.0, 200.0, -50.0],
})
replay = portfolio_sim.replay_portfolio(trades_df, starting_capital=100_000, sizing_method="fixed")
replay_calmar = portfolio_sim.calmar_from_replay(replay)
from portfolio_math import daily_pnl_from_trades
daily_pnl4 = daily_pnl_from_trades(
    pd.DataFrame({"exit_time": trades_df["exit_time"], "pnl_net": trades_df["pnl_net"]}))
mine_calmar = calmar_from_daily_pnl(daily_pnl4, starting_capital=100_000)
check(f"calmar_from_daily_pnl ({mine_calmar:.4f}) matches portfolio_sim.calmar_from_replay() "
      f"({replay_calmar:.4f}) on the same trades (fixed sizing means replay P&L == raw P&L)",
      np.isfinite(mine_calmar) and np.isfinite(replay_calmar) and abs(mine_calmar - replay_calmar) < 0.01)

print("Check 5: calmar_from_daily_pnl -- requires starting_capital explicitly; invalid/missing "
      "capital returns NaN rather than a fabricated ratio")
check("starting_capital=0 -> NaN, not a divide-by-zero crash or a silent default",
      np.isnan(calmar_from_daily_pnl(pnl3, starting_capital=0)))

print("Check 6: m2_ratio -- a strategy with the SAME Sharpe as the benchmark but at a "
      "DIFFERENT volatility rescales to the benchmark's own annualized return (M2's defining "
      "property: equal Sharpe -> equal M2 regardless of the strategy's own leverage/vol)")
idx6 = pd.date_range("2024-01-01", periods=252, freq="D")
bench_daily = pd.Series(rng.normal(0.0004, 0.01, 252), index=idx6)  # ~10% annualized return, ~16% vol
# Strategy dollar P&L engineered to have the SAME Sharpe as the benchmark but at HALF the benchmark's
# daily-return volatility (in % terms) -- scale factor 0.5 preserves the mean/std ratio exactly.
starting_capital6 = 100_000
strategy_pnl6 = bench_daily * 0.5 * starting_capital6
m2 = m2_ratio(strategy_pnl6, bench_daily, starting_capital=starting_capital6)
bench_annualized_return = float(bench_daily.mean() * 252)
check(f"M2 ({m2:.4f}) is close to the benchmark's own annualized return ({bench_annualized_return:.4f}) "
      f"since the strategy has identical Sharpe, just different scale",
      abs(m2 - bench_annualized_return) < 0.01)

print("Check 7: m2_ratio -- missing/too-short benchmark series returns NaN rather than a "
      "fabricated comparison")
check("empty benchmark series -> NaN", np.isnan(m2_ratio(pnl3, pd.Series(dtype=float), starting_capital=100_000)))

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
