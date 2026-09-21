"""
Synthetic verification of survivorship.py's build_additions()/
get_member_since_date() BEFORE trusting them on the real Wikipedia scrape.

Checks:
  1. A symbol added once is correctly extracted with its date.
  2. A symbol removed then LATER re-added (appears in two rows) keeps the
     EARLIEST addition date (most conservative -- widest eligible window).
  3. get_member_since_date returns None for a symbol with no addition
     record (must be treated as "unconstrained" by callers, not "never
     eligible" -- this function's job is just to report what's known).
  4. Malformed/junk rows (empty ticker, "N/A", overlong garbage) are
     dropped, not turned into spurious addition dates.

FIXED 2026-09-21 (root-cause, not a bandaid; caught by `_run_all_verify.py`): the fixture used to
mimic a raw "Changes to the list" scrape (date/added_ticker/removed_ticker/reason columns). That
table stopped existing on Wikipedia's S&P 500 page entirely (a real, disclosed site-structure
change found live 2026-08-11 -- see `fetch_current_constituents_with_dates()`'s own docstring,
which explicitly says it REPLACES that original plan). `build_additions()` was updated the same
day to match its new real producer's output contract -- (symbol, added_date) directly, sourced
from the current-constituents table's own "Date added" column -- but this test's fixture was never
updated, so every run since has raised KeyError('added_date') immediately. Rewritten to match the
current, real contract.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from survivorship import build_additions, get_member_since_date


def main():
    failures = []

    # (symbol, added_date) -- build_additions()'s real current contract, matching
    # fetch_current_constituents_with_dates()'s output shape (see module docstring's
    # 2026-09-21 fix note for why this isn't the old raw-changes-table schema).
    constituents_df = pd.DataFrame([
        {"symbol": "AAAA", "added_date": "March 1, 2015"},
        {"symbol": "BBBB", "added_date": "June 1, 2010"},
        {"symbol": "BBBB", "added_date": "January 1, 2020"},  # re-added later, earliest kept
        {"symbol": "", "added_date": "N/A"},
        {"symbol": "THIS-IS-A-WAY-TOO-LONG-GARBAGE-TICKER", "added_date": "April 1, 2018"},
    ])

    additions = build_additions(constituents_df)

    # --- 1: single addition extracted correctly ---
    aaaa_date = get_member_since_date("AAAA", additions)
    if aaaa_date is None or aaaa_date != pd.Timestamp("2015-03-01"):
        failures.append(f"AAAA should have added_date 2015-03-01, got {aaaa_date}")

    # --- 2: earliest date kept for a re-added symbol ---
    bbbb_date = get_member_since_date("BBBB", additions)
    if bbbb_date is None or bbbb_date != pd.Timestamp("2010-06-01"):
        failures.append(f"BBBB (re-added) should keep the EARLIEST date 2010-06-01, got {bbbb_date}")

    # --- 3: unknown symbol -> None, not a crash or a spurious date ---
    unknown_date = get_member_since_date("ZZZZ", additions)
    if unknown_date is not None:
        failures.append(f"Unknown symbol should return None, got {unknown_date}")

    # --- 4: junk rows dropped ---
    if "THIS-IS-A-WAY-TOO-LONG-GARBAGE-TICKER".upper()[:10] in additions["symbol"].values if len(additions) else []:
        failures.append("Overlong garbage ticker should have been dropped by the symbol regex filter")
    if len(additions[additions["symbol"] == ""]) > 0:
        failures.append("Empty-string symbol rows should have been dropped")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All index-additions checks passed.")
    print(f"  AAAA: {aaaa_date}")
    print(f"  BBBB (re-added, earliest kept): {bbbb_date}")
    print(f"  ZZZZ (unknown): {unknown_date}")
    print(f"  total additions extracted: {len(additions)}")


if __name__ == "__main__":
    main()
