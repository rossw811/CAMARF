"""
Regression test (2026-10-07) for period_bars.resample_to_period_end's volume sum. Found while restating the coarse
WRDS volume: groupby "sum" turns a period whose daily volume is ALL missing into 0 (AAPL 7D bars in 1982 stored
volume 0 where CRSP has no volume), and a period with some unknown days into a partial sum -- fake "no trading" /
understated volume rather than "unknown".
Rule: a day with a valid close but NaN volume = unknown volume -> the period's volume is NaN. A day with no close
(a missing bar) contributes nothing. A period with no volume at all -> NaN, never 0. Volume 0 on a priced day stays 0.
Checks (synthetic daily frame, weekly and monthly):
  1. all-NaN-volume week -> NaN (was 0)
  2. a week with one priced day of unknown volume -> NaN (was the partial sum)
  3. a week with a missing bar (close and volume NaN) -> the sum of the other days
  4. a genuine zero-volume week stays 0; a normal week sums exactly
  5. a custom agg dict (data.py passes its own) gets the same rule
Run: python debug/_verify_period_bars_volume_nan.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from period_bars import resample_to_period_end

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    idx = pd.bdate_range("2021-01-04", "2021-02-26")          # Mondays..Fridays, 8 weeks
    d = pd.DataFrame({"open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "volume": 100.0}, index=idx)
    wk = lambda day: pd.Timestamp(day).to_period("W-FRI").end_time.normalize()
    d.loc["2021-01-04":"2021-01-08", "volume"] = np.nan                       # week 1: no volume at all
    d.loc["2021-01-13", "volume"] = np.nan                                    # week 2: one unknown day
    d.loc["2021-01-20", ["close", "open", "high", "low", "volume"]] = np.nan  # week 3: one missing bar
    d.loc["2021-01-25":"2021-01-29", "volume"] = 0.0                          # week 4: genuinely no trading
    for label, agg in (("default", None), ("custom", {"open": "first", "high": "max", "low": "min",
                                                       "close": "last", "volume": "sum"})):
        w = resample_to_period_end(d, "7D", agg)
        v = w["volume"]
        check(f"{label}_all_nan_week_is_nan", np.isnan(v.loc[wk("2021-01-06")]), v.loc[wk("2021-01-06")])
        check(f"{label}_unknown_day_week_is_nan", np.isnan(v.loc[wk("2021-01-13")]), v.loc[wk("2021-01-13")])
        check(f"{label}_missing_bar_week_sums_rest", v.loc[wk("2021-01-20")] == 400.0, v.loc[wk("2021-01-20")])
        check(f"{label}_zero_volume_week_stays_zero", v.loc[wk("2021-01-27")] == 0.0, v.loc[wk("2021-01-27")])
        check(f"{label}_normal_week_exact", v.loc[wk("2021-02-03")] == 500.0, v.loc[wk("2021-02-03")])
    m = resample_to_period_end(d, "1M")
    check("month_with_unknown_days_is_nan", np.isnan(m.loc[pd.Timestamp("2021-01-31"), "volume"]))
    check("clean_month_exact", m.loc[pd.Timestamp("2021-02-28"), "volume"] == 100.0 * 20)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
