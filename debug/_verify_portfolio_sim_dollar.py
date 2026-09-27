"""
Checks for portfolio_sim.replay_portfolio(pnl_mode="dollar") (2026-09-27). The legacy replay marks
open positions to market as (spread - entry_spread) * n_shares_a -- the same beta-drift / log-unit
accounting as code-review B2 -- and takes notional from shares x the yfinance 1h cache. Dollar mode
uses the trade's notional_dollar_entry and pnl_dollar_net (pnl_dollar.py) and marks open positions
at real prices: side * N_a * (r_a(t) - beta_entry * r_b(t)).

Hand-built case, $25,000 capital, fixed sizing:
  T1 AAA/BBB long, notional $20,000 (N_a $10,000, beta 1.0), day0 -> day4, pnl_dollar_net +600
  On day2 T1 is marked at AAA -20% / BBB 0% -> MTM = +1 * $10,000 * (-0.20 - 1.0*0) = -$2,000
     -> equity 23,000 (the trough).
  T2 CCC/DDD long, notional $20,000, enters day2 while T1 open -> available = equity incl. MTM
     (23,000) - committed (20,000) = $3,000 -> scale 0.15 -> actual pnl 0.15 * (-400) = -60.
Final equity = 25,000 + 600 - 60 = 25,540.

Run: python debug/_verify_portfolio_sim_dollar.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import pnl_dollar
import portfolio_sim

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def _px(vals):
    idx = pd.bdate_range("2026-03-02", periods=len(vals))
    v = np.asarray(vals, float)
    return pd.DataFrame({"close": v, "tr": v}, index=idx)


PRICES = {"AAA": _px([100, 100, 80, 100, 106]), "BBB": _px([50] * 5),
          "CCC": _px([10] * 5), "DDD": _px([10] * 5)}


def main():
    pnl_dollar._cache.clear()
    pnl_dollar._cache.update(PRICES)
    d = pd.bdate_range("2026-03-02", periods=5)
    trades = pd.DataFrame([
        dict(symbol_a="AAA", symbol_b="BBB", tf="1D", side="long", hedge_ratio=1.0, entry_time=d[0], exit_time=d[4],
             notional_dollar_entry=20_000.0, pnl_dollar_net=600.0, entry_spread=0.0, entry_z=3.1,
             half_life_at_entry=10.0, n_shares_a=100, n_shares_b=100, pnl_net=1.0),
        dict(symbol_a="CCC", symbol_b="DDD", tf="1D", side="long", hedge_ratio=1.0, entry_time=d[2], exit_time=d[3],
             notional_dollar_entry=20_000.0, pnl_dollar_net=-400.0, entry_spread=0.0, entry_z=3.1,
             half_life_at_entry=10.0, n_shares_a=100, n_shares_b=100, pnl_net=1.0),
    ])
    r = portfolio_sim.replay_portfolio(trades, 25_000, "fixed", pnl_mode="dollar")
    tk = r["taken"].set_index("symbol_a")
    check("both_taken", r["n_taken"] == 2, f"n_taken={r['n_taken']}")
    check("T2_scaled_0.15", abs(tk.loc["CCC", "size_scale"] - 0.15) < 1e-9, f"{tk.loc['CCC', 'size_scale']}")
    check("T2_actual_pnl_-60", abs(tk.loc["CCC", "actual_pnl"] + 60.0) < 1e-9, f"{tk.loc['CCC', 'actual_pnl']}")
    check("final_equity_25540", abs(r["final_equity"] - 25_540.0) < 1e-9, f"{r['final_equity']}")
    check("mtm_trough_23000", abs(r["trough_mtm_equity"] - 23_000.0) < 1e-6, f"{r['trough_mtm_equity']}")
    try:
        portfolio_sim.replay_portfolio(trades, 25_000, "half_kelly", pnl_mode="dollar")
        check("risk_sizing_rejected_in_dollar_mode", False, "no error raised")
    except ValueError:
        check("risk_sizing_rejected_in_dollar_mode", True)
    bad = trades.copy()
    bad.loc[0, "pnl_dollar_net"] = np.nan
    try:
        portfolio_sim.replay_portfolio(bad, 25_000, "fixed", pnl_mode="dollar")
        check("nan_dollar_pnl_rejected", False, "no error raised")
    except ValueError:
        check("nan_dollar_pnl_rejected", True)
    pnl_dollar._cache.clear()
    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
