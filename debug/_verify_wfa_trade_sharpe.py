"""
Regression test (inconsistency sweep, 2026-09-27): wfa._fold_metrics annualized per-TRADE P&L by sqrt(bars_per_year)
-- the exact bug backtest.compute_metrics fixed on 2026-09-04 (a per-trade series is not a per-bar series; the fix
annualizes by the observed trade frequency, sqrt(n_trades / years)). The fix was never propagated to wfa.py, so every
WFA fold Sharpe was mis-annualized (and its 4h bars-per-year was 252 instead of 2 x 252). Fix: one shared helper,
portfolio_math.trade_frequency_sharpe, used by both.
Checks:
  1. 24 trades over ~2 years: WFA fold Sharpe == mean/std * sqrt(24 / years_covered) (not sqrt(252));
  2. backtest.compute_metrics and wfa._fold_metrics give the SAME Sharpe on the same trades;
  3. the helper returns NaN for a single trade / zero dispersion.
Run: python debug/_verify_wfa_trade_sharpe.py
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import portfolio_math as pm
import wfa
from backtest import compute_metrics

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    rng = np.random.default_rng(0)
    entries = pd.date_range("2022-01-03", periods=24, freq="MS") + pd.Timedelta(days=2)
    exits = entries + pd.Timedelta(days=5)
    pnl = rng.normal(10, 30, 24)
    years = (exits.max() - entries.min()).total_seconds() / (365.25 * 86400)
    expected = pnl.mean() / pnl.std() * np.sqrt(24 / years)
    wt = [SimpleNamespace(pnl_net=float(p), entry_time=e, exit_time=x) for p, e, x in zip(pnl, entries, exits)]
    m = wfa._fold_metrics(wt, "1D")
    check("wfa_trade_frequency_annualization", abs(m["sharpe"] - round(expected, 4)) < 1e-4,
          f"got={m['sharpe']} expected={expected:.4f} (sqrt(252) version would be {pnl.mean() / pnl.std() * np.sqrt(252):.4f})")
    bt = [SimpleNamespace(pnl_net=float(p), entry_time=e, exit_time=x, mae=np.nan, mfe=np.nan, hold_bars=1,
                          exit_reason="mean_revert", pnl_gross=float(p), side="long")
          for p, e, x in zip(pnl, entries, exits)]
    try:
        bm = compute_metrics(bt, "1D", "A", "B", "ols")
        b_sh = bm.get("sharpe") if isinstance(bm, dict) else getattr(bm, "sharpe", None)
    except Exception as e:
        b_sh = f"error: {e}"
    check("backtest_and_wfa_agree", isinstance(b_sh, float) and abs(b_sh - m["sharpe"]) < 1e-4, f"backtest={b_sh} wfa={m['sharpe']}")
    check("helper_degenerate_nan", np.isnan(pm.trade_frequency_sharpe(np.array([1.0]), entries[:1], exits[:1]))
          and np.isnan(pm.trade_frequency_sharpe(np.array([2.0, 2.0]), entries[:2], exits[:2])))
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
