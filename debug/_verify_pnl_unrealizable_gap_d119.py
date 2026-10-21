"""
BUG-D119 / Amendment 5 (DECISIONS_2026-10-21 #1): a trade spanning a price hole of more than 5 trading days
(data._MAX_FILL_BARS) in either leg is unrealizable -- pnl_dollar.add_dollar_pnl gives it status "unrealizable_gap"
and no P&L. Real case: GVKEY010137_01W/GVKEY015736_01W entered 2023-03-01, leg B had no valid price 2023-09-29 ->
2025-12-17, booked +$21,958 per $10k at exit_reason data_gap. Checks (synthetic loader):
  1. hole of 810 days in leg B inside the trade -> unrealizable_gap, NaN P&L
  2. hole of exactly 5 business days -> ok (the DATA_GAP rule is "> 5")
  3. hole of 6 business days -> unrealizable_gap
  4. stale exit price (leg A's last valid bar 40 days before exit, no bar after) -> unrealizable_gap
     (daily _at_or_before had no staleness check)
  5. hole BEFORE entry or AFTER exit does not matter -> ok
  6. NaN prices inside the window count as missing (a hole of NaN rows is a hole)
  7. intraday trade with a 3-week leg hole -> unrealizable_gap; overnight/weekend is not a hole -> ok
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


import pnl_dollar  # noqa: E402


def series(days, drop=(), nan=()):
    idx = pd.bdate_range("2019-01-01", "2026-06-30")
    px = pd.Series(np.linspace(10, 20, len(idx)), index=idx)
    for a, b in drop:
        px = px[(px.index < pd.Timestamp(a)) | (px.index > pd.Timestamp(b))]
    for a, b in nan:
        px[(px.index >= pd.Timestamp(a)) & (px.index <= pd.Timestamp(b))] = np.nan
    f = pd.DataFrame({"close": px, "tr": px})
    f.attrs["usd"] = True
    return f


def run(A, B, entry, exit_, tf="1D"):
    pnl_dollar._cache.clear()
    loader = {"A": A, "B": B}.get
    t = pd.DataFrame([{"symbol_a": "A", "symbol_b": "B", "tf": tf, "hedge_ratio": 1.0, "side": "long",
                       "entry_time": pd.Timestamp(entry), "exit_time": pd.Timestamp(exit_), "n_shares_a": 100}])
    r = pnl_dollar.add_dollar_pnl(t, price_loader=loader).iloc[0]
    return r["pnl_dollar_status"], r["pnl_dollar_net"]


full = series(None)
s, p = run(full, series(None, drop=[("2023-09-29", "2025-12-16")]), "2023-03-01", "2025-12-17")
check("1 810-day hole in leg B -> unrealizable_gap, no P&L", s == "unrealizable_gap" and np.isnan(p), f"{s} {p}")

# 2023-06-05 (Mon) .. 2023-06-09 (Fri) removed = 5 business days missing
s, _ = run(full, series(None, drop=[("2023-06-05", "2023-06-09")]), "2023-05-01", "2023-07-03")
check("2 exactly 5 missing business days -> ok", s == "ok", s)
s, _ = run(full, series(None, drop=[("2023-06-05", "2023-06-12")]), "2023-05-01", "2023-07-03")
check("3 6 missing business days -> unrealizable_gap", s == "unrealizable_gap", s)

s, _ = run(series(None, drop=[("2024-02-01", "2026-06-30")]), full, "2024-01-02", "2024-03-12")
check("4 stale exit price (no leg-A bar for 40 days up to exit) -> unrealizable_gap", s == "unrealizable_gap", s)

s, _ = run(series(None, drop=[("2023-02-01", "2023-04-28")]), series(None, drop=[("2024-01-01", "2024-06-28")]),
           "2023-05-15", "2023-09-01")
check("5 holes before entry / after exit do not matter -> ok", s == "ok", s)

s, _ = run(full, series(None, nan=[("2023-06-05", "2023-06-30")]), "2023-05-01", "2023-07-31")
check("6 NaN rows inside the trade are a hole -> unrealizable_gap", s == "unrealizable_gap", s)

# intraday: hourly bars on business days 10:00-15:00 ET
hrs = pd.DatetimeIndex([d + pd.Timedelta(hours=h) for d in pd.bdate_range("2025-01-02", "2025-03-31")
                        for h in range(10, 16)])
ipx = pd.Series(np.linspace(10, 20, len(hrs)), index=hrs)
ifull = pd.DataFrame({"close": ipx, "tr": ipx})
ihole = ifull[(ifull.index < "2025-02-03") | (ifull.index >= "2025-02-24")]
orig = pnl_dollar.load_intraday_prices
try:
    pnl_dollar.load_intraday_prices = lambda s, tf: {"A": ifull, "B": ihole}[s]
    s, _ = run(None, None, "2025-01-15 11:00", "2025-03-03 14:00", tf="1h")
    check("7a intraday 3-week hole -> unrealizable_gap", s == "unrealizable_gap", s)
    pnl_dollar.load_intraday_prices = lambda s, tf: {"A": ifull, "B": ifull}[s]
    s, _ = run(None, None, "2025-01-17 15:00", "2025-01-21 10:00", tf="1h")   # over a weekend + MLK day
    check("7b intraday overnight/weekend is not a hole -> ok", s == "ok", s)
    # review of 2c0c0f6a, F3: a stale intraday exit (last bar a week before exit) is unrealizable_gap, not missing_price
    ist = ifull[ifull.index < "2025-02-04"]
    pnl_dollar.load_intraday_prices = lambda s, tf: {"A": ifull, "B": ist}[s]
    s, _ = run(None, None, "2025-01-15 11:00", "2025-02-11 14:00", tf="1h")
    check("7c intraday stale exit -> unrealizable_gap (not missing_price)", s == "unrealizable_gap", s)
finally:
    pnl_dollar.load_intraday_prices = orig

# review F3: the exit date itself counts when it has no valid bar. Last valid Mon 2020-02-03, exit Tue 2020-02-11:
# Tue 02-04 .. Tue 02-11 = 6 business days without a valid price -> unrealizable; exit Mon 02-10 = 5 -> ok.
G = series(None, nan=[("2020-02-04", "2020-02-28")])
s6, _ = run(G, full, "2020-01-20", "2020-02-11")
s5, _ = run(G, full, "2020-01-20", "2020-02-10")
check("8 stale tail counts the exit date: 6 -> unrealizable, 5 -> ok... ", s6 == "unrealizable_gap", f"{s6}")
check("8b ... but 5 with the exit date's bar missing is not > 5", s5 != "unrealizable_gap", f"{s5}")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
