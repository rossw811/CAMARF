"""
Regression test for code-review findings M8 + M9 (2026-09-26), macro point-in-time availability.
  M8: CFTC COT is indexed on its Tuesday as-of date but published Friday 15:30 ET -> visible 3 days early.
  M9: daily FRED series were reindexed with no lag, and RegimeConditioner looks up `macro.index <= entry date`, so a
      day-t entry saw day-t's VIX close (16:15 ET, after the equity close and after any intraday entry) and FRED
      dailies that publish the next business day; DTWEXBGS (H.10) is released weekly on Monday for the PRIOR week,
      so its daily values were visible up to ~a week early.
Fix (macro._release_available): each value is mapped to its release date and becomes visible on the FIRST trading
day strictly after that release -- daily FRED: release = observation day; DTWEXBGS: release = the Monday after the
observation's week; COT: release = as-of Tuesday + 3 days (Friday).
Checks:
  1. daily series: value at trading day d is the observation from the previous trading day;
  2. DTWEXBGS: a Wednesday observation is first visible the Tuesday of the following week;
  3. COT: a Tuesday as-of reading is first visible the following Monday;
  4. monthly series keep their M7 publication lags (unchanged behaviour).
Run: python debug/_verify_macro_daily_cot_availability.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import macro

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    master = pd.bdate_range("2024-01-01", "2024-03-29")
    vix = pd.Series(np.arange(len(master), dtype=float), index=master)
    usd = pd.Series(np.arange(len(master), dtype=float) + 1000, index=master)
    cpi = pd.Series([300.0, 301.0, 302.0], index=pd.to_datetime(["2023-12-01", "2024-01-01", "2024-02-01"]))
    out = macro._align_to_trading_calendar({"vix_close": vix, "usd_index": usd}, {"cpi": cpi}, master)

    d = pd.Timestamp("2024-02-14")                              # Wednesday
    prev = pd.Timestamp("2024-02-13")
    check("daily_uses_previous_trading_day", out.loc[d, "vix_close"] == vix.loc[prev],
          f"got {out.loc[d, 'vix_close']} expected {vix.loc[prev]}")
    wed = pd.Timestamp("2024-02-07")
    vis = out.index[out["usd_index"] >= usd.loc[wed]][0]
    check("dtwexbgs_visible_tuesday_after_next_monday", vis == pd.Timestamp("2024-02-13"), f"first visible {vis.date()}")

    tue = pd.Timestamp("2024-02-06")
    cot = pd.Series([0.1, 0.2], index=[pd.Timestamp("2024-01-30"), tue])
    a = macro._release_available(cot, master, "cot")
    first = a.index[a == 0.2][0]
    check("cot_visible_monday_after_friday_release", first == pd.Timestamp("2024-02-12"), f"first visible {first.date()}")

    jan = out.index[out["cpi"] == 301.0][0]
    check("monthly_m7_lag_unchanged", jan == pd.Timestamp("2024-02-16"), f"CPI Jan-2024 first visible {jan.date()}")
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
