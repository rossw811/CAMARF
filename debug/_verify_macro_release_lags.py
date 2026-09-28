"""
Regression test for code-review finding M7 (2026-09-26): macro.py's _MONTHLY_PUBLICATION_LAG_DAYS are documented
as "reference-period end to public release" but are ADDED TO FRED's period-START stamp (YYYY-MM-01), so CPI (+15d)
became visible ~4 weeks before release and FEDFUNDS (+5d) became visible before most of the days it averages.
Checks that every lagged monthly series is visible no earlier than its real release, for real release dates:
  CPI  Jan 2020 (stamp 2020-01-01) released 2020-02-13;  CPI Jun 2023 (2023-06-01) released 2023-07-12
  FEDFUNDS Jan 2020 average (2020-01-01) published 2020-02-03
  UNRATE Jan 2020 (2020-01-01) released 2020-02-07
Run: python debug/_verify_macro_release_lags.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import macro

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    L = macro._MONTHLY_PUBLICATION_LAG_DAYS
    cases = [("cpi", "2020-01-01", "2020-02-13"), ("cpi", "2023-06-01", "2023-07-12"),
             ("fed_funds_rate", "2020-01-01", "2020-02-03"), ("unemployment_rate", "2020-01-01", "2020-02-07")]
    for name, stamp, released in cases:
        visible = pd.Timestamp(stamp) + pd.Timedelta(days=L[name])
        check(f"{name}_{stamp}_not_before_release", visible >= pd.Timestamp(released),
              f"visible {visible.date()} vs released {released} (lag {L[name]}d)")
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
