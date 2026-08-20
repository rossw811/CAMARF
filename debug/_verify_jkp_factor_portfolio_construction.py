"""
Synthetic verification of research/jkp_factor_portfolio_construction.py::
build_factor_returns() -- run BEFORE trusting the real 16M-row WRDS query,
per this project's standing discipline (verify synthetically first).

Checks:
  1. A characteristic with a KNOWN, exact top-tercile/bottom-tercile return
     spread (constructed by hand) is recovered exactly by build_factor_
     returns -- proves the tercile sort + spread arithmetic is correct.
  2. The `invert` convention (size/investment/beta -- LOW minus HIGH) is
     applied correctly: an inverted factor's sign is the OPPOSITE of a
     non-inverted factor given the identical underlying data.
  3. A month with too few names (< n_terciles * 10) is correctly SKIPPED,
     not included with a degenerate/noisy spread.
  4. NaN characteristic values are excluded from the ranking, not treated
     as a real (e.g. zero) value that could bias which stocks land in the
     top/bottom tercile.
  5. Multiple months each get their own independent spread (no leakage of
     one month's ranks into another).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from research.jkp_factor_portfolio_construction import build_factor_returns, _FACTOR_DEFS, _CHAR_COLS


def _make_month(date, n_per_tercile, char_col, char_values, ret_values):
    # build_factor_returns loops over ALL registered factors each call, so
    # every characteristic column referenced by _FACTOR_DEFS must be PRESENT
    # (even if NaN/unused for this test) -- dropna(subset=[...]) KeyErrors
    # on a genuinely missing column, distinct from a present-but-NaN one.
    rows = []
    for i, (c, r) in enumerate(zip(char_values, ret_values)):
        row = {"permno": i, "date": date, "ret_exc_lead1m": r}
        for other_col in _CHAR_COLS:
            row[other_col] = c if other_col == char_col else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    failures = []
    date = pd.Timestamp("2000-01-31")
    # build_factor_returns labels each row with the REALIZED-return month
    # (date + 1 month-end), not the characteristic-observation date itself
    # (real bug found + fixed 2026-08-13 via a direct AAPL spot-check) --
    # every lookup below must use this same realized-date label.
    realized_date = date + pd.offsets.MonthEnd(1)

    # --- Check 1: exact known spread for a non-inverted factor (value: be_me) ---
    # 30 names, 10 per tercile. Bottom tercile (lowest be_me) gets ret=0.01,
    # middle tercile ret=0.05 (irrelevant to the spread), top tercile ret=0.09.
    # Expected non-inverted spread (top - bottom) = 0.09 - 0.01 = 0.08.
    char_col_value = _FACTOR_DEFS["value"][0]
    char_values = list(range(30))  # 0..29, monotonic -> clean tercile split
    ret_values = [0.01] * 10 + [0.05] * 10 + [0.09] * 10
    panel1 = _make_month(date, 10, char_col_value, char_values, ret_values)
    factors1 = build_factor_returns(panel1)
    got1 = factors1.loc[realized_date, "value"]
    if abs(got1 - 0.08) > 1e-9:
        failures.append(f"Check 1: expected value spread 0.08, got {got1}")

    # --- Check 2: invert convention -- size uses market_equity, invert=True,
    # so LOW characteristic (bottom tercile) is the LONG leg: spread = bottom - top.
    # Same underlying data/returns as Check 1 -> expected spread = 0.01 - 0.09 = -0.08
    # (the exact negative of Check 1's non-inverted result).
    char_col_size = _FACTOR_DEFS["size"][0]
    panel2 = _make_month(date, 10, char_col_size, char_values, ret_values)
    factors2 = build_factor_returns(panel2)
    got2 = factors2.loc[realized_date, "size"]
    if abs(got2 - (-0.08)) > 1e-9:
        failures.append(f"Check 2: expected size (inverted) spread -0.08, got {got2}")
    if abs(got1 - (-got2)) > 1e-9:
        failures.append(f"Check 2b: inverted and non-inverted spreads on identical data should be "
                         f"exact negatives, got value={got1} size={got2}")

    # --- Check 3: too few names in a month -> skipped entirely ---
    small_panel = _make_month(date, 3, char_col_value, list(range(15)), [0.05] * 15)
    factors3 = build_factor_returns(small_panel)
    if "value" in factors3.columns and len(factors3["value"].dropna()) > 0:
        failures.append(f"Check 3: month with only 15 names (< 30 required) should be skipped, "
                         f"got {factors3}")

    # --- Check 4: NaN characteristic values excluded from ranking ---
    char_values_nan = list(range(30)) + [np.nan] * 5  # 5 extra NaN rows, should be dropped
    ret_values_nan = ret_values + [0.5] * 5  # extreme returns on the NaN rows -- must NOT affect result
    panel4 = _make_month(date, 10, char_col_value, char_values_nan, ret_values_nan)
    factors4 = build_factor_returns(panel4)
    got4 = factors4.loc[realized_date, "value"]
    if abs(got4 - 0.08) > 1e-9:
        failures.append(f"Check 4: NaN characteristic rows should be excluded from ranking, "
                         f"expected spread 0.08 (unaffected by the 0.5-return NaN rows), got {got4}")

    # --- Check 5: two independent months, no cross-month leakage ---
    date2 = pd.Timestamp("2000-02-29")
    realized_date2 = date2 + pd.offsets.MonthEnd(1)
    ret_values_m2 = [0.10] * 10 + [0.05] * 10 + [0.20] * 10  # different spread: 0.20-0.10=0.10
    panel5a = _make_month(date, 10, char_col_value, char_values, ret_values)
    panel5b = _make_month(date2, 10, char_col_value, char_values, ret_values_m2)
    panel5 = pd.concat([panel5a, panel5b], ignore_index=True)
    factors5 = build_factor_returns(panel5)
    got5_m1 = factors5.loc[realized_date, "value"]
    got5_m2 = factors5.loc[realized_date2, "value"]
    if abs(got5_m1 - 0.08) > 1e-9 or abs(got5_m2 - 0.10) > 1e-9:
        failures.append(f"Check 5: two independent months should each get their own correct spread, "
                         f"expected 0.08/0.10, got {got5_m1}/{got5_m2}")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All JKP factor-portfolio-construction checks passed.")
    print(f"  Check 1: known non-inverted spread -> {got1:.4f} (expected 0.08)")
    print(f"  Check 2: inverted convention is exact negative -> {got2:.4f} (expected -0.08)")
    print(f"  Check 3: too-few-names month correctly skipped")
    print(f"  Check 4: NaN characteristic rows excluded -> {got4:.4f} (expected 0.08)")
    print(f"  Check 5: independent months -> {got5_m1:.4f}/{got5_m2:.4f} (expected 0.08/0.10)")


if __name__ == "__main__":
    main()
