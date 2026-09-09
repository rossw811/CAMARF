"""
debug/_verify_pit_wfa_trade_bootstrap.py -- synthetic checks for
research/pit_wfa_trade_bootstrap.py, run BEFORE trusting it against real
pit_wfa.py trades.

aggregate_portfolio (backtest.py) only reads t.pnl_net, t.entry_time,
t.exit_time from each trade -- a minimal mock with just those three
attributes is sufficient to test bootstrap_portfolio_sharpe without
constructing full Trade dataclass instances (many required fields
irrelevant to the Sharpe computation being tested here).
"""
import os
import sys
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.pit_wfa_trade_bootstrap import bootstrap_portfolio_sharpe
from backtest import aggregate_portfolio

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


@dataclass
class _MockTrade:
    pnl_net: float
    entry_time: pd.Timestamp
    exit_time: Optional[pd.Timestamp] = None
    symbol_a: str = "AAA"
    symbol_b: str = "BBB"
    tf: str = "1h"


print("Check 1: bootstrap_portfolio_sharpe reproduces the point estimate's ballpark on a "
      "large-n, low-variance synthetic series")
rng = np.random.default_rng(0)
dates = pd.date_range("2020-01-01", periods=200, freq="1D")
# Consistently positive P&L, low noise -- should give a robust, tight positive CI.
pnls = rng.normal(loc=10.0, scale=2.0, size=200)
trades_pos = [_MockTrade(pnl_net=p, entry_time=d, exit_time=d) for p, d in zip(pnls, dates)]
original = aggregate_portfolio(trades_pos, [])
boot = bootstrap_portfolio_sharpe(trades_pos, n_boot=2000, rng=np.random.default_rng(1))
ci_low, ci_high = np.nanpercentile(boot, [2.5, 97.5])
check("bootstrap mean is close to the original point estimate",
      abs(np.nanmean(boot) - original["sharpe_portfolio"]) < 1.0)
check("a robust, consistently-positive P&L series produces a CI that stays positive "
      "(genuinely significant result, not a coin flip)",
      ci_low > 0)

print("Check 2: a THIN, mixed-sign trade set (matching the real 5-trade rolling/fold2 case) "
      "produces a CI that straddles zero -- correctly reflects genuine uncertainty, unlike "
      "the robust all-positive/all-negative cases above and below")
thin_dates = pd.date_range("2020-01-01", periods=5, freq="30D")
thin_pnls = [50.0, -30.0, 20.0, -40.0, 60.0]  # mixed signs, small n, matches real 5-trade shape
trades_thin = [_MockTrade(pnl_net=p, entry_time=d, exit_time=d) for p, d in zip(thin_pnls, thin_dates)]
boot_thin = bootstrap_portfolio_sharpe(trades_thin, n_boot=2000, rng=np.random.default_rng(2))
ci_low_thin, ci_high_thin = np.nanpercentile(boot_thin, [2.5, 97.5])
check("a thin, mixed-sign 5-trade CI straddles zero (genuinely inconclusive, not falsely "
      "confident in either direction)",
      ci_low_thin < 0 < ci_high_thin)
check("the thin-trade CI is not degenerate (has real spread, not collapsed to a point)",
      (ci_high_thin - ci_low_thin) > 0.5)

print("Check 3: an all-losing trade set produces a robustly NEGATIVE bootstrap CI")
loss_dates = pd.date_range("2020-01-01", periods=100, freq="1D")
loss_pnls = rng.normal(loc=-10.0, scale=2.0, size=100)
trades_neg = [_MockTrade(pnl_net=p, entry_time=d, exit_time=d) for p, d in zip(loss_pnls, loss_dates)]
boot_neg = bootstrap_portfolio_sharpe(trades_neg, n_boot=2000, rng=np.random.default_rng(3))
check("a robust, consistently-losing series produces a CI that stays negative",
      np.nanpercentile(boot_neg, 97.5) < 0)

print("Check 4: reproducibility with a fixed seed")
b_a = bootstrap_portfolio_sharpe(trades_thin, n_boot=500, rng=np.random.default_rng(7))
b_b = bootstrap_portfolio_sharpe(trades_thin, n_boot=500, rng=np.random.default_rng(7))
check("identical seed produces identical bootstrap draws (deterministic, not flaky)",
      np.array_equal(b_a, b_b, equal_nan=True))

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
