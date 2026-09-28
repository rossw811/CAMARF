"""
Regression test for code-review finding D13 (2026-09-26): data.py _resample_from_daily (1M/3M/6M) and
data_wrds.resample_daily_to (3M/6M/1Y) stamped each coarse bar at the START of its period ("MS"/"QS"/"2QS"/"YS",
label="left") while the bar carries the period's LAST close -- a bar dated 2024-01-01 holds the 2024-01-31 close,
so any as-of join or cross-timeframe comparison on the stamp sees up to a period of future data. Sources also
disagreed (WRDS native monthly = last trading day, IBKR = calendar month end, yfinance = month start), so the
same month landed on different rows per source.
Fix: period_bars.resample_to_period_end -- every coarse bar is stamped at the CALENDAR end of its period
(Friday for 7D, month/quarter/half-year/year end), used by all resample sites.
Checks:
  1. every stamp >= the date of the last daily close it contains (no lookahead) for 7D/1M/3M/6M/1Y;
  2. close == last daily close in the period; open/high/low/volume aggregate correctly;
  3. an equity (weekdays, month ending on a weekend) and a 24/7 crypto series get IDENTICAL monthly stamps;
  4. 6M halves are Jun-30/Dec-31 regardless of the series' start month (a March start used to shift 2QS bins);
  5. data.py's YFinanceFeed._resample_from_daily and data_wrds.resample_daily_to both obey 1-4;
  6. restamp_to_period_end maps WRDS native last-trading-day monthly stamps onto calendar month end.
Run: python debug/_verify_period_end_stamps.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def _ohlcv(idx, seed):
    c = 100 + np.cumsum(np.random.default_rng(seed).normal(0, 1, len(idx)))
    return pd.DataFrame({"open": c + 0.1, "high": c + 1, "low": c - 1, "close": c, "volume": 1.0}, index=idx)


def _check_frame(tag, daily, out, tf):
    """Checks 1-2 for one resampled frame."""
    if out is None or out.empty:
        check(f"{tag}:{tf}:non_empty", False)
        return
    bad_look, bad_close = 0, 0
    prev = pd.Timestamp.min
    for stamp, row in out.iterrows():
        members = daily[(daily.index > prev) & (daily.index <= stamp)]
        prev = stamp
        if members.empty:
            continue
        if stamp < members.index[-1]:
            bad_look += 1
        if abs(row["close"] - members["close"].iloc[-1]) > 1e-12:
            bad_close += 1
    check(f"{tag}:{tf}:no_lookahead_and_close_is_last", bad_look == 0 and bad_close == 0,
          f"lookahead={bad_look} close_mismatch={bad_close} n={len(out)}")


def main():
    import data_wrds as dw
    from data import YFinanceFeed
    from period_bars import resample_to_period_end, restamp_to_period_end

    eq = _ohlcv(pd.bdate_range("2023-03-06", "2025-12-31"), 0)      # March start, weekdays only
    cr = _ohlcv(pd.date_range("2023-03-06", "2025-12-31"), 1)       # 24/7
    for tf in ("7D", "1M", "3M", "6M", "1Y"):
        _check_frame("helper", eq, resample_to_period_end(eq, tf), tf)

    # member aggregation on one known month (Nov 2025 ends Sunday the 30th; last weekday the 28th)
    m = resample_to_period_end(eq, "1M")
    nov = eq.loc["2025-11"]
    row = m.loc[pd.Timestamp("2025-11-30")]
    check("helper:agg_ohlcv", abs(row["open"] - nov["open"].iloc[0]) < 1e-12 and abs(row["high"] - nov["high"].max()) < 1e-12
          and abs(row["low"] - nov["low"].min()) < 1e-12 and row["volume"] == len(nov))

    me, mc = resample_to_period_end(eq, "1M").index, resample_to_period_end(cr, "1M").index
    check("equity_crypto_same_monthly_stamps", me.equals(mc), f"eq_last={me[-1]} cr_last={mc[-1]}")
    h = resample_to_period_end(eq, "6M").index
    check("half_years_jun30_dec31", all((d.month, d.day) in ((6, 30), (12, 31)) for d in h), f"{list(h.strftime('%Y-%m-%d'))}")

    yf = YFinanceFeed._resample_from_daily(eq)
    for tf in ("7D", "1M", "3M", "6M"):
        _check_frame("data.py", eq, yf.get(tf), tf)
        check(f"data.py:{tf}:same_as_helper", yf[tf].index.equals(resample_to_period_end(eq, tf).index))
    for tf in ("7D", "3M", "6M", "1Y"):
        w = dw.resample_daily_to(eq, tf)
        _check_frame("data_wrds", eq, w, tf)
        check(f"data_wrds:{tf}:same_as_helper", w.index.equals(resample_to_period_end(eq, tf).index))

    native = pd.DataFrame({"close": [1.0, 2.0, 3.0]}, index=pd.to_datetime(["2025-10-31", "2025-11-28", "2025-12-31"]))
    rs = restamp_to_period_end(native, "1M")
    check("restamp_native_monthly", list(rs.index.strftime("%Y-%m-%d")) == ["2025-10-31", "2025-11-30", "2025-12-31"]
          and list(rs["close"]) == [1.0, 2.0, 3.0], f"{list(rs.index)}")
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
