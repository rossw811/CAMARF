"""
Regression test for intraday dollar marking in pnl_dollar.add_dollar_pnl (Ross, 2026-10-03: "build intraday dollar
marking"). Before: every non-1D trade got status "intraday" and no P&L, so under the dollar default (B2/B3) intraday
trades were dropped.
Convention (same as daily): position fixed at entry, each leg marked at its own price; price = the leg's intraday close
at or before the entry/exit bar (yfinance intraday cache, IBKR supplement as fallback), NOT normalised to the date.
Intraday closes are split-adjusted but not dividend-adjusted: a dividend inside an intraday hold is ignored (disclosed).
A price older than data._MAX_FILL_BARS business days before the bar is stale -> "missing_price" (never a stale fill).
Checks:
  1. a 1h trade: long A 100 -> 104, B 50 -> 51, beta 2 -> gross = 10,000 * (0.04 - 2 * 0.02) = 0 + costs; a second
     trade with B flat -> gross = 10,000 * 0.04 = 400 (hand-computed);
  2. exit bar missing but an earlier same-day bar exists -> uses that earlier close (at-or-before, not the day's close);
  3. stale: last price 10 business days before the exit bar -> "missing_price";
  4. a non-USD leg (".T" listing) -> "non_usd_leg";
  5. daily trades unaffected (still priced by the daily loader).
Run: python debug/_verify_pnl_dollar_intraday.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import pnl_dollar
from config import Config

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def bars(days, hours=("09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30")):
    return pd.DatetimeIndex([pd.Timestamp(f"{d.date()} {h}") for d in days for h in hours])


def main():
    if not hasattr(pnl_dollar, "load_intraday_prices"):
        check("load_intraday_prices_exists", False); return finish()
    days = pd.bdate_range("2024-03-04", periods=20)
    ix = bars(days)
    A = pd.DataFrame({"close": 100.0}, index=ix); A.loc[ix >= pd.Timestamp("2024-03-06 12:30"), "close"] = 104.0
    B = pd.DataFrame({"close": 50.0}, index=ix); B.loc[ix >= pd.Timestamp("2024-03-06 12:30"), "close"] = 51.0
    Bflat = pd.DataFrame({"close": 50.0}, index=ix)
    Agap = A[(A.index < pd.Timestamp("2024-03-08")) | (A.index > pd.Timestamp("2024-03-26"))]   # hole past the exit
    Ahole = A.drop(pd.Timestamp("2024-03-06 14:30"))                                         # exit bar missing
    frames = {("SYNA", "1h"): A, ("SYNB", "1h"): B, ("FLAT", "1h"): Bflat, ("GAPA", "1h"): Agap,
              ("HOLEA", "1h"): Ahole, ("7203.T", "1h"): A}
    orig = pnl_dollar.load_intraday_prices
    pnl_dollar.load_intraday_prices = lambda s, tf: frames.get((s, tf))
    try:
        def tr(a, b, beta, entry, exit_, tf="1h"):
            return {"tf": tf, "symbol_a": a, "symbol_b": b, "hedge_ratio": beta, "entry_time": pd.Timestamp(entry),
                    "exit_time": pd.Timestamp(exit_), "side": "long", "n_shares_a": 100}
        T = pd.DataFrame([tr("SYNA", "SYNB", 2.0, "2024-03-05 10:30", "2024-03-06 14:30"),
                          tr("SYNA", "FLAT", 2.0, "2024-03-05 10:30", "2024-03-06 14:30"),
                          tr("HOLEA", "FLAT", 2.0, "2024-03-05 10:30", "2024-03-06 14:30"),
                          tr("GAPA", "FLAT", 1.0, "2024-03-05 10:30", "2024-03-22 10:30"),
                          tr("7203.T", "FLAT", 1.0, "2024-03-05 10:30", "2024-03-06 14:30")])
        D = pnl_dollar.add_dollar_pnl(T, commission_per_share=0.0, slippage_bps=0.0)
        st = D["pnl_dollar_status"].tolist()
        g = D["pnl_dollar_gross"].tolist()
        check("1a.hedged_move_zero", st[0] == "ok" and np.isclose(g[0], 0.0), f"{st[0]} gross={g[0]}")
        check("1b.unhedged_leg_400", st[1] == "ok" and np.isclose(g[1], 400.0), f"{st[1]} gross={g[1]}")
        check("2.at_or_before_within_day", st[2] == "ok" and np.isclose(g[2], 400.0), f"{st[2]} gross={g[2]}")
        check("3.stale_price_missing", st[3] == "missing_price", st[3])
        check("4.non_usd_leg", st[4] == "non_usd_leg", st[4])
    finally:
        pnl_dollar.load_intraday_prices = orig
    idx = pd.bdate_range("2024-01-02", periods=30)
    dA = pd.DataFrame({"close": 100.0, "tr": 100.0}, index=idx); dA.loc[idx[10]:, ["close", "tr"]] = 110.0
    dB = pd.DataFrame({"close": 50.0, "tr": 50.0}, index=idx)
    D1 = pnl_dollar.add_dollar_pnl(pd.DataFrame([{"tf": "1D", "symbol_a": "X", "symbol_b": "Y", "hedge_ratio": 1.0,
                                                   "entry_time": idx[2], "exit_time": idx[15], "side": "long",
                                                   "n_shares_a": 100}]), commission_per_share=0.0, slippage_bps=0.0,
                                   price_loader=lambda s: {"X": dA, "Y": dB}.get(s))
    check("5.daily_unchanged", D1["pnl_dollar_status"].iloc[0] == "ok" and np.isclose(D1["pnl_dollar_gross"].iloc[0], 1000.0),
          f"{D1['pnl_dollar_status'].iloc[0]} {D1['pnl_dollar_gross'].iloc[0]}")
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
