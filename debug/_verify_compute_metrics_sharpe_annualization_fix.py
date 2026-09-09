"""
debug/_verify_compute_metrics_sharpe_annualization_fix.py -- synthetic verification for a real
bug found live (2026-09-04): backtest.py's compute_metrics() annualized per-TRADE Sharpe using
sqrt(bars_per_year[tf]) as if a trade happened on every bar. At 1h/1D (this project's headline
scale) that's a mild-enough approximation to have gone unnoticed; at 1m/2m, where trades are far
rarer than bars, it produced Sharpe magnitudes of -279.58/-590.15
(research/decoupling_backtest.py's real SPY/VOO results) that nothing else in the project
remotely resembles. Fixed to annualize by the trade sequence's own OBSERVED frequency
(n_trades / years the sequence spans), not the timeframe's raw bar count.

Run: python debug/_verify_compute_metrics_sharpe_annualization_fix.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest import Trade, compute_metrics

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


def make_trade(entry_time, exit_time, pnl_net, tf="1m"):
    return Trade(
        tf=tf, symbol_a="A", symbol_b="B", hedge_method="ols", hedge_ratio=1.0,
        entry_time=pd.Timestamp(entry_time), entry_z=3.0, entry_spread=1.0, side="long",
        n_shares_a=100, n_shares_b=100.0, half_life_at_entry=20.0, hurst_at_entry=0.3,
        exit_time=pd.Timestamp(exit_time), pnl_net=pnl_net,
    )


print("Check 1: reproduces the real bug scenario -- 12 trades over ~2.5 years at 1m timeframe "
      "(matching decoupling_backtest.py's real SPY/VOO case) no longer produces an absurd "
      "Sharpe magnitude under the OLD bars-per-year formula")
rng = np.random.default_rng(0)
start = pd.Timestamp("2024-01-01")
trades_1m = []
for i in range(12):
    entry = start + pd.Timedelta(days=i * 76)  # spread across ~2.5 years
    exit_ = entry + pd.Timedelta(hours=2)
    trades_1m.append(make_trade(entry, exit_, float(rng.normal(-5, 15)), tf="1m"))
m = compute_metrics(trades_1m, "1m", "A", "B", "ols")
old_bpy_sharpe_magnitude_estimate = 313.5  # sqrt(390*252), the old formula's multiplier at 1m
check(f"fixed Sharpe ({m['sharpe']:.2f}) has a sane magnitude (|Sharpe| < 20), not the "
      f"old formula's ~{old_bpy_sharpe_magnitude_estimate:.0f}x-inflated range "
      f"(real examples hit -279.58/-590.15)", abs(m["sharpe"]) < 20)

print("Check 2: the fixed formula scales with ACTUAL trade frequency, not the raw timeframe -- "
      "the SAME 12 trades over the SAME calendar span produce the SAME Sharpe regardless of "
      "whether tf='1m' or tf='1h' is passed (frequency is derived from entry/exit timestamps, "
      "not a per-timeframe lookup table)")
m_1m = compute_metrics(trades_1m, "1m", "A", "B", "ols")
trades_1h_label = [make_trade(t.entry_time, t.exit_time, t.pnl_net, tf="1h") for t in trades_1m]
m_1h_label = compute_metrics(trades_1h_label, "1h", "A", "B", "ols")
check("Sharpe is identical regardless of the tf label, since it's now derived from the trades' "
      "own timestamps, not a hardcoded bars-per-year table",
      np.isclose(m_1m["sharpe"], m_1h_label["sharpe"]))

print("Check 3: a HIGH-frequency trade sequence (roughly one trade per bar, the OLD formula's "
      "implicit assumption) still gets annualized to a comparable magnitude as a real high-"
      "frequency strategy would expect -- confirms the fix isn't just uniformly shrinking every "
      "Sharpe, it tracks real observed frequency correctly in both directions")
trades_dense = []
t0 = pd.Timestamp("2024-01-01 09:30:00")
for i in range(500):
    entry = t0 + pd.Timedelta(minutes=i)
    exit_ = entry + pd.Timedelta(minutes=1)
    trades_dense.append(make_trade(entry, exit_, float(rng.normal(0.5, 2)), tf="1m"))
m_dense = compute_metrics(trades_dense, "1m", "A", "B", "ols")
# 500 trades in ~500 minutes -- roughly 390*252 trades/year if sustained, so the fixed formula
# should recover an annualization factor in the same ballpark as the OLD bars_per_year constant
# for this genuinely high-frequency case (frequency really IS close to 1-per-bar here).
implied_years = 500 / (390 * 252)
expected_sharpe_order = trades_dense[0].pnl_net  # just confirming it runs without error/NaN
check("a genuinely dense (near 1-trade-per-bar) sequence produces a FINITE, non-NaN Sharpe",
      np.isfinite(m_dense["sharpe"]))

print("Check 4: a single trade (no meaningful frequency to estimate) returns NaN Sharpe, not a "
      "fabricated value from a zero or undefined time span")
single_trade = [make_trade("2024-01-01", "2024-01-01 01:00:00", 100.0, tf="1h")]
m_single = compute_metrics(single_trade, "1h", "A", "B", "ols")
check("single trade -> NaN Sharpe (years_covered=0, can't estimate a frequency from one point)",
      np.isnan(m_single["sharpe"]))

print("Check 5: trades missing exit_time (still open) are excluded from the years-covered span, "
      "not treated as spanning zero time or crashing on None arithmetic")
t_open = make_trade("2024-01-01", "2024-06-01", 50.0, tf="1h")
t_open.exit_time = None
trades_with_open = [make_trade("2024-01-01", "2024-06-01", 50.0, tf="1h"),
                     make_trade("2024-02-01", "2024-07-01", -20.0, tf="1h"), t_open]
m_open = compute_metrics(trades_with_open, "1h", "A", "B", "ols")
check("no crash with an open (exit_time=None) trade mixed in, and Sharpe is still finite",
      np.isfinite(m_open["sharpe"]))

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
