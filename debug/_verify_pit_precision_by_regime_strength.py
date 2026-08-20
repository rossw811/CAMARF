"""
Synthetic verification of research/pit_precision_by_regime_strength.py's
early_regime_strength() -- the only genuinely new logic in that script
(build_pair_data/score_cell are reused, already-verified from Finding #23's
own script). Run BEFORE trusting the real join.

Checks:
  1. A coint span that fully overlaps the early period returns its strength.
  2. A coint span that only overlaps the LATE period (not early) is
     correctly ignored -- returns None, not leaked late-period info.
  3. Multiple overlapping coint spans -> the one covering the LATEST early
     date wins (most relevant to the confirmation decision).
  4. No coint spans at all for a pair -> returns None cleanly, not a crash.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from research.pit_precision_by_regime_strength import early_regime_strength


def _row(d):
    return {"window_end_date": pd.Timestamp(d)}


def main():
    failures = []

    # --- Check 1: span fully overlaps early period ---
    segs = pd.DataFrame([
        {"symbol_a": "A", "symbol_b": "B", "state": "coint",
         "start_date": pd.Timestamp("2010-01-01"), "end_date": pd.Timestamp("2015-01-01"),
         "strength": "strong"},
    ])
    early_rows = [_row("2011-01-01"), _row("2012-01-01"), _row("2013-01-01")]
    result = early_regime_strength(("A", "B"), early_rows, segs)
    if result != "strong":
        failures.append(f"Check 1: expected 'strong', got {result!r}")

    # --- Check 2: span only overlaps LATE period, must be ignored ---
    segs2 = pd.DataFrame([
        {"symbol_a": "A", "symbol_b": "B", "state": "coint",
         "start_date": pd.Timestamp("2020-01-01"), "end_date": pd.Timestamp("2021-01-01"),
         "strength": "strong"},
    ])
    result2 = early_regime_strength(("A", "B"), early_rows, segs2)
    if result2 is not None:
        failures.append(f"Check 2: late-only span should be ignored (return None), got {result2!r}")

    # --- Check 3: multiple overlapping spans -> latest wins ---
    segs3 = pd.DataFrame([
        {"symbol_a": "A", "symbol_b": "B", "state": "coint",
         "start_date": pd.Timestamp("2010-01-01"), "end_date": pd.Timestamp("2011-06-01"),
         "strength": "weak"},
        {"symbol_a": "A", "symbol_b": "B", "state": "coint",
         "start_date": pd.Timestamp("2012-06-01"), "end_date": pd.Timestamp("2013-06-01"),
         "strength": "strong"},
    ])
    result3 = early_regime_strength(("A", "B"), early_rows, segs3)
    if result3 != "strong":
        failures.append(f"Check 3: expected the LATEST-covering span ('strong'), got {result3!r}")

    # --- Check 4: no coint spans at all ---
    segs4 = pd.DataFrame([
        {"symbol_a": "A", "symbol_b": "B", "state": "not_coint",
         "start_date": pd.Timestamp("2010-01-01"), "end_date": pd.Timestamp("2015-01-01"),
         "strength": None},
    ])
    result4 = early_regime_strength(("A", "B"), early_rows, segs4)
    if result4 is not None:
        failures.append(f"Check 4: no coint spans should return None, got {result4!r}")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All PIT-precision-by-regime-strength join checks passed.")
    print(f"  Check 1: full early overlap -> {result}")
    print(f"  Check 2: late-only span correctly ignored -> {result2}")
    print(f"  Check 3: latest-covering span wins -> {result3}")
    print(f"  Check 4: no coint spans -> {result4}")


if __name__ == "__main__":
    main()
