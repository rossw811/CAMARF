"""
Regression test for code-review finding U2 (2026-09-26): universe_loader.align_to_common_calendar dropped a
tz-aware index with tz_localize(None) WITHOUT converting, so Binance intraday (UTC) stayed on UTC clock time while
equity intraday is ET-naive -- crypto/equity intraday pairs were 4-5 hours misaligned.
Now: tz-aware INTRADAY stamps are converted to America/New_York then made naive (project convention: ET-naive);
tz-aware DAILY stamps (all at midnight) just drop the tz and keep their date.
Checks:
  1. a UTC 14:30 bar in EDT lands on the ET-naive 10:30 row (the equity's bar);
  2. a UTC-midnight daily bar keeps its calendar date (not moved to the previous evening);
  3. tz-naive input is unchanged.
Run: python debug/_verify_loader_timezones.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from universe_loader import align_to_common_calendar

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    eq = pd.DataFrame({"close": [100.0, 101.0]}, index=pd.to_datetime(["2026-06-01 10:30", "2026-06-01 11:30"]))
    btc = pd.DataFrame({"close": [60000.0, 60100.0]},
                       index=pd.to_datetime(["2026-06-01 14:30", "2026-06-01 15:30"]).tz_localize("UTC"))
    out = align_to_common_calendar({"EQ": eq, "BTC": btc}, lookback_years=1)
    b = out["BTC"]["close"]
    check("utc_intraday_converted_to_et", b.get(pd.Timestamp("2026-06-01 10:30")) == 60000.0,
          f"BTC rows at: {list(b.dropna().index.strftime('%H:%M'))}")
    check("aligned_with_equity_bar", out["EQ"]["close"].get(pd.Timestamp("2026-06-01 10:30")) == 100.0)
    d_utc = pd.DataFrame({"close": [1.0, 2.0]}, index=pd.to_datetime(["2026-06-01", "2026-06-02"]).tz_localize("UTC"))
    d_nv = pd.DataFrame({"close": [3.0, 4.0]}, index=pd.to_datetime(["2026-06-01", "2026-06-02"]))
    o2 = align_to_common_calendar({"D1": d_utc, "D2": d_nv}, lookback_years=1)
    check("daily_utc_keeps_date", list(o2["D1"]["close"].dropna().index.strftime("%Y-%m-%d")) == ["2026-06-01", "2026-06-02"],
          f"{list(o2['D1']['close'].dropna().index)}")
    check("naive_unchanged", list(o2["D2"]["close"].dropna()) == [3.0, 4.0])
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
