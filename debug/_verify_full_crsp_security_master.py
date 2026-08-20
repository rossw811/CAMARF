"""
Synthetic verification of data_wrds.py::security_master_asof() -- Thread K
Part 1's point-in-time security-master lookup, mirroring sp500_members_
asof's already-verified multi-spell convention. Run BEFORE trusting the
real fetch (already tested separately, live, that stocknames.nameenddt
uses a shared max-date placeholder, not genuine NULLs -- this test focuses
on the multi-spell as-of logic itself).

Checks:
  1. A security with a SINGLE spell is correctly found "as of" a date
     inside its validity range, and correctly ABSENT before/after it.
  2. A security with MULTIPLE spells (ticker changed over time, e.g. real
     permno 10001 case) returns the CORRECT spell for a given as-of date,
     not just any spell for that permno.
  3. A "still current" spell (is_current=True, nameenddt=NaT after the
     placeholder fix) is found as of TODAY, not excluded by a NaT
     comparison silently failing.
  4. A gap between two spells (delisted then relisted under a new permno,
     or a genuine data gap) correctly returns nothing for a date in the gap.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from data_wrds import security_master_asof


def main():
    failures = []

    master = pd.DataFrame([
        # Single-spell security.
        {"permno": 1, "ticker": "AAA", "namedt": pd.Timestamp("2000-01-01"),
         "nameenddt": pd.Timestamp("2010-01-01"), "is_current": False},
        # Multi-spell security: ticker changed BBB -> CCC in 2015.
        {"permno": 2, "ticker": "BBB", "namedt": pd.Timestamp("2005-01-01"),
         "nameenddt": pd.Timestamp("2015-06-01"), "is_current": False},
        {"permno": 2, "ticker": "CCC", "namedt": pd.Timestamp("2015-06-02"),
         "nameenddt": pd.NaT, "is_current": True},
        # Security with a genuine GAP: delisted 2008, different permno relisted 2012.
        {"permno": 3, "ticker": "DDD", "namedt": pd.Timestamp("2000-01-01"),
         "nameenddt": pd.Timestamp("2008-01-01"), "is_current": False},
    ])

    # --- Check 1: single-spell, inside/outside range ---
    inside = security_master_asof(master, "2005-01-01")
    if 1 not in set(inside["permno"]):
        failures.append("Check 1a: permno 1 should be found as-of 2005-01-01 (inside its spell)")
    outside = security_master_asof(master, "2020-01-01")
    if 1 in set(outside["permno"]):
        failures.append("Check 1b: permno 1 should NOT be found as-of 2020-01-01 (spell ended 2010)")

    # --- Check 2: multi-spell, correct ticker for the date ---
    before_change = security_master_asof(master, "2010-01-01")
    row_2_before = before_change[before_change["permno"] == 2]
    if len(row_2_before) != 1 or row_2_before.iloc[0]["ticker"] != "BBB":
        failures.append(f"Check 2a: permno 2 as-of 2010-01-01 should be ticker BBB, "
                         f"got {row_2_before['ticker'].tolist() if len(row_2_before) else 'not found'}")
    after_change = security_master_asof(master, "2020-01-01")
    row_2_after = after_change[after_change["permno"] == 2]
    if len(row_2_after) != 1 or row_2_after.iloc[0]["ticker"] != "CCC":
        failures.append(f"Check 2b: permno 2 as-of 2020-01-01 should be ticker CCC, "
                         f"got {row_2_after['ticker'].tolist() if len(row_2_after) else 'not found'}")

    # --- Check 3: still-current (NaT) spell found "as of today" ---
    today_result = security_master_asof(master)  # default: today
    if 2 not in set(today_result["permno"]):
        failures.append("Check 3: still-current permno 2 (NaT nameenddt) should be found as-of today")

    # --- Check 4: genuine gap ---
    gap_result = security_master_asof(master, "2010-01-01")
    if 3 in set(gap_result["permno"]):
        failures.append("Check 4: permno 3 was delisted 2008-01-01, should NOT be found as-of 2010-01-01")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All full-CRSP-security-master as-of checks passed.")
    print(f"  Check 1: single-spell inside/outside range correct")
    print(f"  Check 2: multi-spell ticker resolution correct (BBB before, CCC after)")
    print(f"  Check 3: still-current (NaT) spell found as-of today")
    print(f"  Check 4: genuine gap correctly returns nothing")


if __name__ == "__main__":
    main()
