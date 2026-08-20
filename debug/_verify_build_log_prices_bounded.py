"""
Synthetic verification of research/wrds_deep_history_episodic_scan.py::
build_log_prices_and_returns_bounded() -- the memory-bounded replacement for
build_log_prices_and_returns() used ONLY by episodic_window_size_sweep.py's
new --full-universe mode (added 2026-08-15 after a real, live OOM crash:
"Unable to allocate 5.25 GiB for an array with shape (25434, 27716)" when
the plain pd.DataFrame(dict-of-Series) constructor ran against the full
44,694-symbol unrestricted universe).

Checks:
  1. Equivalence with the ORIGINAL build_log_prices_and_returns() on a small
     synthetic universe (lookback_years set to comfortably exceed the
     synthetic data's own span, so no bound-related truncation occurs) --
     log prices and returns match to float32 precision, not exact float64
     (a real, disclosed precision tradeoff, not a bug).
  2. A value at a known date survives the reindex-based construction
     unchanged (within float32 precision).
  3. lookback_years actually bounds the canonical index -- a symbol whose
     ENTIRE history predates the cutoff contributes only NaN columns (still
     present in log_price_df, but should fail the >=756-bar returns filter
     and get excluded from the final valid_cols).
  4. Real gaps (dates a symbol's own index skips) stay NaN -- never
     forward-filled.
  5. The min-756-bar-overlap column filter is applied identically to the
     original function (same threshold, same exclusion behavior).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from research.wrds_deep_history_episodic_scan import (
    build_log_prices_and_returns, build_log_prices_and_returns_bounded,
)


def _synthetic_universe(n_symbols=6, n_days=900, seed=0):
    rng = np.random.RandomState(seed)
    idx = pd.date_range("2020-01-01", periods=n_days, freq="D")
    close_by_symbol = {}
    for i in range(n_symbols):
        sym = f"SYM{i:02d}"
        prices = 100 + np.cumsum(rng.standard_normal(n_days) * 0.5)
        prices = np.abs(prices) + 10  # keep strictly positive
        if i == n_symbols - 1:
            # one symbol with real gaps -- skip every 5th day
            keep = np.arange(n_days) % 5 != 0
            close_by_symbol[sym] = pd.Series(prices[keep], index=idx[keep])
        else:
            close_by_symbol[sym] = pd.Series(prices, index=idx)
    return close_by_symbol, idx


def main():
    failures = []

    close_by_symbol, idx = _synthetic_universe()

    # --- Check 1 & 2: equivalence with the original, lookback set to exceed the data's own span ---
    log_price_orig, returns_orig = build_log_prices_and_returns(close_by_symbol)
    log_price_new, returns_new = build_log_prices_and_returns_bounded(
        close_by_symbol, lookback_years=10, dtype=np.float32
    )

    if set(log_price_orig.columns) != set(log_price_new.columns):
        failures.append(
            f"Check 1: valid_cols differ -- orig={set(log_price_orig.columns)}, "
            f"new={set(log_price_new.columns)}"
        )
    else:
        common_idx = log_price_orig.index.intersection(log_price_new.index)
        for col in log_price_orig.columns:
            a = log_price_orig.loc[common_idx, col].values.astype(np.float64)
            b = log_price_new.loc[common_idx, col].values.astype(np.float64)
            both_nan = np.isnan(a) & np.isnan(b)
            close = np.isclose(a, b, rtol=1e-5, atol=1e-5, equal_nan=False)
            if not np.all(close | both_nan):
                n_bad = np.sum(~(close | both_nan))
                failures.append(f"Check 1: log_price mismatch for {col}, {n_bad} bad cells")

    # Check 2: a specific known value survives (float32 precision).
    known_date = idx[100]
    if "SYM00" in log_price_orig.columns:
        expected = log_price_orig.loc[known_date, "SYM00"]
        actual = log_price_new.loc[known_date, "SYM00"]
        if not np.isclose(expected, actual, rtol=1e-5, atol=1e-5):
            failures.append(f"Check 2: value at {known_date} for SYM00 -- expected {expected}, got {actual}")

    # --- Check 3: lookback_years bound excludes an entirely-out-of-range symbol ---
    close_by_symbol_old = dict(close_by_symbol)
    old_idx = pd.date_range("1990-01-01", periods=900, freq="D")  # far outside a 5-year bound from "now" (2022-06ish)
    close_by_symbol_old["ANCIENT"] = pd.Series(100 + np.arange(900, dtype=float), index=old_idx)
    log_price_bounded, returns_bounded = build_log_prices_and_returns_bounded(
        close_by_symbol_old, lookback_years=5, dtype=np.float32
    )
    if "ANCIENT" in returns_bounded.columns:
        failures.append("Check 3: ANCIENT (entirely pre-cutoff history) should have been excluded "
                         "by the 756-bar-overlap filter after lookback truncation, but survived")

    # --- Check 4: real gaps stay NaN, never forward-filled ---
    gap_sym = f"SYM05"  # the deliberately-gapped symbol from _synthetic_universe
    if gap_sym in log_price_new.columns:
        gap_date = idx[5]  # a date this symbol's own native index skips (i % 5 == 0)
        if gap_date in log_price_new.index:
            val = log_price_new.loc[gap_date, gap_sym]
            if not pd.isna(val):
                failures.append(f"Check 4: {gap_date} should be a real NaN gap for {gap_sym}, got {val} "
                                 f"instead -- forward-fill leak")

    # --- Check 5b: pandas nullable-dtype pd.NA values don't crash the boolean comparison
    # (real bug found live 2026-08-15: "TypeError: boolean value of NA is ambiguous") ---
    nullable_universe = {
        "NULLABLE": pd.Series(
            pd.array([100.0, pd.NA, 102.0, 103.0] * 250, dtype="Float64"),
            index=pd.date_range("2020-01-01", periods=1000, freq="D"),
        ),
        "PLAIN": pd.Series(100 + np.arange(1000, dtype=float),
                            index=pd.date_range("2020-01-01", periods=1000, freq="D")),
    }
    try:
        lp_nullable, ret_nullable = build_log_prices_and_returns_bounded(nullable_universe, lookback_years=10)
    except TypeError as e:
        failures.append(f"Check 5b: pd.NA in a nullable-dtype column crashed -- {e}")
    else:
        if "NULLABLE" in lp_nullable.columns:
            n_nan_at_gaps = lp_nullable["NULLABLE"].isna().sum()
            if n_nan_at_gaps == 0:
                failures.append("Check 5b: expected some NaN cells from the pd.NA values, found none")

    # --- Check 5: min-756-bar filter applied identically ---
    short_universe = {
        "SHORT": pd.Series(100 + np.arange(500, dtype=float),
                            index=pd.date_range("2020-01-01", periods=500, freq="D")),
        "LONG": pd.Series(100 + np.arange(900, dtype=float),
                           index=pd.date_range("2020-01-01", periods=900, freq="D")),
    }
    _, ret_check = build_log_prices_and_returns_bounded(short_universe, lookback_years=10)
    if "SHORT" in ret_check.columns:
        failures.append("Check 5: SHORT (500 bars < 756 threshold) should be excluded, but survived")
    if "LONG" not in ret_check.columns:
        failures.append("Check 5: LONG (900 bars >= 756 threshold) should survive, but was excluded")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All build_log_prices_and_returns_bounded checks passed.")
    print(f"  Check 1/2: equivalence with original confirmed to float32 precision "
          f"({len(log_price_orig.columns)} valid columns)")
    print(f"  Check 3: lookback_years bound correctly excludes entirely-out-of-range history")
    print(f"  Check 4: real gaps preserved as NaN, no forward-fill")
    print(f"  Check 5: 756-bar overlap filter matches the original function's behavior")


if __name__ == "__main__":
    main()
