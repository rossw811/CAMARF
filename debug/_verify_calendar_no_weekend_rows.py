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
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
