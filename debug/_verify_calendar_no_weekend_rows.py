"""
Regression test for code-review finding U3 (2026-09-26): align_to_common_calendar built the DAILY canonical index
as the union of every symbol's dates, so crypto's Saturday/Sunday bars added weekend rows that are NaN for every
equity; np.diff-based log returns then made every equity Monday return NaN (~20% of daily returns, including all
weekend-news moves, silently removed from every correlation). Now weekend dates are excluded from the DAILY
canonical index (crypto's weekend move folds into Monday's close-to-close return); intraday is untouched.
Checks: equity Monday log return is finite and equals log(Mon/Fri); crypto keeps Mon-Fri rows; no Sat/Sun rows.
Run: python debug/_verify_calendar_no_weekend_rows.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from universe_loader import align_to_common_calendar

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    wk = pd.bdate_range("2026-06-01", "2026-06-12")
    all_days = pd.date_range("2026-06-01", "2026-06-12")
    eq = pd.DataFrame({"close": np.linspace(100, 110, len(wk))}, index=wk)
    cr = pd.DataFrame({"close": np.linspace(60000, 61200, len(all_days))}, index=all_days)
    out = align_to_common_calendar({"EQ": eq, "BTC": cr}, lookback_years=1)
    idx = out["EQ"].index
    check("no_weekend_rows", not (idx.dayofweek >= 5).any(), f"weekend rows: {int((idx.dayofweek >= 5).sum())}")
    r = pd.Series(np.diff(np.log(out["EQ"]["close"].to_numpy()), prepend=np.nan), index=idx)
    mon = pd.Timestamp("2026-06-08")
    exp = np.log(eq.loc[mon, "close"] / eq.loc[pd.Timestamp("2026-06-05"), "close"])
    check("monday_return_finite_and_correct", np.isfinite(r[mon]) and abs(r[mon] - exp) < 1e-12, f"r_mon={r[mon]}")
    check("crypto_weekdays_kept", out["BTC"]["close"].notna().sum() == len(wk))
    # 2026-10-18 (found running D11): WRDS monthly bars sit on calendar month-ends, ~2 in 7 of them a Sat/Sun; the
    # all-midnight test treated them as daily and dropped them (86 of 120 months on the real 1M cache).
    me = pd.date_range("2016-01-31", "2025-12-31", freq="ME")
    mo = align_to_common_calendar({"M": pd.DataFrame({"close": np.arange(1.0, len(me) + 1)}, index=me)},
                                  lookback_years=10)
    check("monthly_weekend_month_ends_kept", len(mo["M"]) == len(me) and mo["M"]["close"].notna().all(),
          f"{len(mo['M'])}/{len(me)} months kept ({int((me.dayofweek >= 5).sum())} fall on a weekend)")
    # Review of 2ec0c521: a grid-level median test still drops them when daily and coarse series share one call
    dly = pd.bdate_range("2016-01-01", "2025-12-31")
    mix = align_to_common_calendar({"M": pd.DataFrame({"close": np.arange(1.0, len(me) + 1)}, index=me),
                                    "D": pd.DataFrame({"close": 1.0}, index=dly),
                                    "BTC": pd.DataFrame({"close": 1.0}, index=pd.date_range("2016-01-01", "2025-12-31"))},
                                   lookback_years=10)
    check("mixed_daily_monthly_keeps_every_month", int(mix["M"]["close"].notna().sum()) == len(me),
          f"{int(mix['M']['close'].notna().sum())}/{len(me)}")
    wknd_only_crypto = mix["D"].index[(mix["D"].index.dayofweek >= 5)]
    check("mixed_call_drops_weekend_rows_only_crypto_has", wknd_only_crypto.isin(me).all(),
          f"{len(wknd_only_crypto)} weekend rows kept, all month-ends")
    sun = pd.date_range("2016-01-03", periods=260, freq="W-SUN")
    mon = pd.date_range("2016-01-04", periods=260, freq="W-MON")
    wk2 = align_to_common_calendar({"S": pd.DataFrame({"close": 1.0}, index=sun),
                                    "Mo": pd.DataFrame({"close": 1.0}, index=mon)}, lookback_years=10)
    check("weekly_sunday_bars_kept_beside_monday_bars", int(wk2["S"]["close"].notna().sum()) == len(sun),
          f"{int(wk2['S']['close'].notna().sum())}/{len(sun)}")
    qe = pd.date_range("2016-03-31", "2025-12-31", freq="QE")
    q = align_to_common_calendar({"Q": pd.DataFrame({"close": 1.0}, index=qe)}, lookback_years=10)
    check("quarterly_weekend_quarter_ends_kept", len(q["Q"]) == len(qe), f"{len(q['Q'])}/{len(qe)}")
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
