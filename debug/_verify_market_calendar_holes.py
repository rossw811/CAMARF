"""
Amendment 5 holes on each market's own trading calendar (Ross 2026-10-22: "yes to all"). The 5-day rule counted
WEEKDAYS, so an exchange closure longer than five weekdays (Lunar New Year on some Asian listings: 6-7) read as a data
hole: pnl_dollar excluded the trade as unrealizable and backtest.py's B1 rule forced an exit. Now a missing day counts
only if the leg's market traded that day. Checks:
  1. derive_calendar: a closure every member shares is not a trading day; one member's own hole does not remove a day;
     dates with fewer than MIN_GROUP live series fall back to weekdays
  2. missing_trading_days: counts calendar trading days strictly between consecutive dates (None -> weekdays)
  3. pnl_dollar: a 7-weekday market closure inside a trade -> ok; the same leg missing 7 OPEN days -> unrealizable_gap
  4. backtest B1 gap flag: with the pair calendar a closure is not a gap; without it (weekdays) it is
  5. market_of: US / crypto / forex / yfinance suffix / Compustat Global by exchange code
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


try:
    import market_calendar as mc  # noqa: E402
except ImportError as e:
    check("market_calendar exists", False, str(e))
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1)
import pnl_dollar  # noqa: E402

days = pd.bdate_range("2020-01-01", "2020-06-30")
closure = (days >= "2020-01-24") & (days <= "2020-02-03")           # 7 weekdays, every member closed
members = {}
for i in range(8):
    keep = ~closure
    if i == 0:
        keep &= ~((days >= "2020-04-01") & (days <= "2020-04-09"))   # member 0's own 7-day hole
    members[f"S{i}"] = pd.DatetimeIndex(days[keep])
cal = mc.derive_calendar(members, min_group=5)
check("1a shared closure removed from the calendar", not cal.isin(days[closure]).any())
check("1b one member's own hole keeps the days", pd.bdate_range("2020-04-01", "2020-04-09").isin(cal).all())
few = mc.derive_calendar({k: v for k, v in list(members.items())[:3]}, min_group=5)
check("1c thin group falls back to weekdays", few.equals(pd.DatetimeIndex(days)), f"{len(few)} vs {len(days)}")

d = np.array(["2020-01-23", "2020-02-04"], dtype="datetime64[D]")
check("2 missing trading days: closure 0 on the calendar, 7 on weekdays",
      mc.missing_trading_days(d, cal).tolist() == [0] and mc.missing_trading_days(d, None).tolist() == [7],
      f"{mc.missing_trading_days(d, cal).tolist()} {mc.missing_trading_days(d, None).tolist()}")


def frame(idx):
    px = pd.Series(np.linspace(10, 20, len(idx)), index=idx)
    f = pd.DataFrame({"close": px, "tr": px}); f.attrs["usd"] = True
    return f


A = frame(members["S1"])                     # market closure only
B = frame(members["S0"])                     # closure + its own 7-day April hole
orig = mc.calendar_for
mc.calendar_for = lambda sym: cal
try:
    pnl_dollar._cache.clear()
    T = pd.DataFrame([{"symbol_a": "A", "symbol_b": "A2", "tf": "1D", "hedge_ratio": 1.0, "side": "long",
                       "entry_time": pd.Timestamp("2020-01-15"), "exit_time": pd.Timestamp("2020-02-20"), "n_shares_a": 1},
                      {"symbol_a": "A", "symbol_b": "B", "tf": "1D", "hedge_ratio": 1.0, "side": "long",
                       "entry_time": pd.Timestamp("2020-03-16"), "exit_time": pd.Timestamp("2020-04-30"), "n_shares_a": 1}])
    st = pnl_dollar.add_dollar_pnl(T, price_loader={"A": A, "A2": A, "B": B}.get)["pnl_dollar_status"].tolist()
    check("3 closure inside a trade -> ok; own 7 open days missing -> unrealizable_gap",
          st == ["ok", "unrealizable_gap"], str(st))
finally:
    mc.calendar_for = orig

import backtest as bt  # noqa: E402
spread_days = members["S1"].values.astype("datetime64[D]")
g_cal = bt.gap_before_flags(spread_days, cal)
g_wd = bt.gap_before_flags(spread_days, None)
i = int(np.searchsorted(spread_days, np.datetime64("2020-02-04")))
check("4 B1: closure is not a gap on the pair calendar, is on weekdays", (not g_cal[i]) and g_wd[i], f"{g_cal[i]} {g_wd[i]}")

ex = {"GVKEY000001_01W": "XTKS-like"}
check("5 market_of", mc.market_of("AAPL") == "US" and mc.market_of("BTC-USD") == "CRYPTO" and mc.market_of("LTC") == "US" and mc.market_of("EURUSD=X") == "FX"
      and mc.market_of("7203.T") == "yf:.T" and mc.market_of("GVKEY000001_01W", ex) == "exchg:XTKS-like"
      and mc.market_of("GVKEY000001_01W_seg2", ex) == "exchg:XTKS-like",
      str([mc.market_of(s, ex) for s in ("AAPL", "BTC-USD", "EURUSD=X", "7203.T", "GVKEY000001_01W", "GVKEY000001_01W_seg2")]))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
