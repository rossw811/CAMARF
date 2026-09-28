"""
Regression test for code-review finding D17 (2026-09-27): research/full_us_market_price_fetch.build_full_market_label_map
handed a reused ticker to the FIRST permno build_delisted_label_map saw, and permnos arrived oldest-first, so the
OLDEST holder claimed the ticker: 2,719 of 4,327 reused tickers, incl. 707 whose most recent holder is listed today
(label "A" held a pre-1999 company, not Agilent; "TPC" a 1992-2000 company, not Tutor Perini). Fix: the most recent
holder (currently listed first, then latest name-end date) gets the ticker; older holders get PERMNO<n>.
Checks (synthetic security master):
  1. ticker reused by an old delisted permno (lower number) and a current one: the CURRENT permno gets the ticker;
  2. two delisted holders: the one that held it LATER gets it;
  3. a null-ticker permno still gets PERMNO<n>; no permno is dropped; labels are unique.
Run: python debug/_verify_full_market_label_recency.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

import pandas as pd

from full_us_market_price_fetch import build_full_market_label_map

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    rows = [
        (100, "XYZ", "1990-01-02", "2000-12-29", False),
        (200, "XYZ", "2010-01-04", "2026-09-25", True),
        (300, "OLD", "1970-01-02", "1980-12-31", False),
        (400, "OLD", "1985-01-02", "1995-12-29", False),
        (500, None, "2001-01-02", "2005-12-30", False),
        (600, "UNQ", "2001-01-02", "2026-09-25", True),
    ]
    master = pd.DataFrame(rows, columns=["permno", "ticker", "namedt", "nameenddt", "is_current"])
    master["namedt"] = pd.to_datetime(master["namedt"])
    master["nameenddt"] = pd.to_datetime(master["nameenddt"])
    lm = build_full_market_label_map(master)
    check("current_holder_gets_ticker", lm.get("XYZ") == 200 and lm.get("PERMNO100") == 100, f"{lm}")
    check("later_delisted_holder_gets_ticker", lm.get("OLD") == 400 and lm.get("PERMNO300") == 300)
    check("null_ticker_kept_all_unique", lm.get("PERMNO500") == 500 and sorted(lm.values()) == [100, 200, 300, 400, 500, 600]
          and len(set(lm)) == len(lm))
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
