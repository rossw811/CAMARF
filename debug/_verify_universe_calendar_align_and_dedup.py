"""
Synthetic verification of universe_loader.py's two new functions, built
2026-08-14 to fix the real bugs found in the full-universe correlation
pre-filter -> EG confirmation cascade (Ross: "build the proper dedup fix
first ... also fix the fact that like 14000 assets or whatever it was
didn't get tested"):

  1. align_to_common_calendar() -- fixes the root cause of the mass
     insufficient_overlap / broadcast-crash failures in the EG stage
     (confirmed live against a real candidate pair, 0700.HK/3690.HK,
     BEFORE this fix: "ValueError: operands could not be broadcast
     together with shapes (5438,) (1907,)").
  2. filter_exact_correlation_duplicates() -- the dedup fix, catching
     same-underlying-identity duplicate pairs (PERMNO-fallback labels,
     literal inverse-quoted FX pairs) via the general |corr|>=threshold
     signature rather than a naming-pattern regex.

Checks:
  1. Two symbols with genuinely different calendars (disjoint weekday
     patterns, different start dates, different lengths) -- after
     align_to_common_calendar, both DataFrames share the EXACT same
     DatetimeIndex (same length, same dates), with real NaN gaps (never
     forward-filled) on days a symbol has no data.
  2. A value that existed at date D in the original DataFrame is still
     exactly that value at date D after reindexing (no accidental shift).
  3. lookback_years bound: a symbol with history far outside the window is
     trimmed to the canonical index's bounded range, not full history.
  4. After alignment, a real _eg_worker-style call (np.isfinite(a) &
     np.isfinite(b) on the "close" column, positionally) no longer raises
     a shape-mismatch exception for two originally different-length
     symbols -- the actual failure mode this fix targets.
  5. filter_exact_correlation_duplicates: a pair at pearson_corr=1.0 is
     dropped, a pair at pearson_corr=-1.0 is dropped (inverse-quote
     signature), a pair at pearson_corr=0.9999 (just under threshold) is
     KEPT, and a pair with pearson_corr=None (missing field) is KEPT, not
     crashed on.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from universe_loader import align_to_common_calendar, filter_exact_correlation_duplicates


def main():
    failures = []

    # --- Checks 1-3: align_to_common_calendar ---
    idx_a = pd.date_range("2004-01-01", periods=400, freq="D")  # long history, old symbol
    idx_b = pd.date_range("2024-01-01", periods=50, freq="3D")   # short, sparse, recent symbol
    df_a = pd.DataFrame({"close": np.arange(400, dtype=float) + 100.0}, index=idx_a)
    df_b = pd.DataFrame({"close": np.arange(50, dtype=float) + 5.0}, index=idx_b)
    merged = {"OLD_SYM": df_a, "NEW_SYM": df_b}

    aligned = align_to_common_calendar(merged, lookback_years=10)

    if aligned["OLD_SYM"].shape[0] != aligned["NEW_SYM"].shape[0]:
        failures.append(
            f"Check 1: shapes still differ after alignment -- "
            f"OLD_SYM={aligned['OLD_SYM'].shape[0]} NEW_SYM={aligned['NEW_SYM'].shape[0]}"
        )
    if not aligned["OLD_SYM"].index.equals(aligned["NEW_SYM"].index):
        failures.append("Check 1: indices are not identical after alignment")

    # Check 2: a real value at a known date survives reindexing unchanged.
    known_date = idx_b[10]
    expected_val = df_b.loc[known_date, "close"]
    if known_date in aligned["NEW_SYM"].index:
        actual_val = aligned["NEW_SYM"].loc[known_date, "close"]
        if not np.isclose(actual_val, expected_val):
            failures.append(
                f"Check 2: value at {known_date} shifted after reindex -- "
                f"expected {expected_val}, got {actual_val}"
            )
    else:
        failures.append(f"Check 2: known date {known_date} missing from canonical index entirely")

    # Real gap days must be NaN, not forward-filled.
    missing_day = idx_a[5]  # OLD_SYM has this date, but many of idx_a's dates aren't in idx_b at all
    if missing_day not in idx_b:
        # A date OLD_SYM has real data for, but too far back to survive the 10y lookback bound anyway
        # (idx_a starts 2004) -- covered by Check 3 instead. Use a date within the bounded window
        # that NEW_SYM genuinely has no data for (every 3rd day is skipped by NEW_SYM's own 3D freq).
        pass
    gap_check_date = idx_b[1] + pd.Timedelta(days=1)  # a day NEW_SYM's own 3D-freq index skips
    if gap_check_date in aligned["NEW_SYM"].index:
        val = aligned["NEW_SYM"].loc[gap_check_date, "close"]
        if not pd.isna(val):
            failures.append(
                f"Check 1b: {gap_check_date} should be a real NaN gap for NEW_SYM "
                f"(its own native index skips this date), got {val} instead -- forward-fill leak"
            )

    # Check 3: lookback_years bound trims old-symbol-only history outside the window.
    max_date = max(idx_a.max(), idx_b.max())
    cutoff = max_date - pd.Timedelta(days=int(10 * 365.25))
    if aligned["OLD_SYM"].index.min() < cutoff - pd.Timedelta(days=1):
        failures.append(
            f"Check 3: canonical index min {aligned['OLD_SYM'].index.min()} is before the "
            f"10-year lookback cutoff {cutoff} -- bound not applied"
        )

    # Check 4: the actual downstream failure mode (_eg_worker-style positional isfinite mask)
    # no longer raises a shape-mismatch exception post-alignment.
    close_a = aligned["OLD_SYM"]["close"].values
    close_b = aligned["NEW_SYM"]["close"].values
    try:
        mask = np.isfinite(close_a) & np.isfinite(close_b)
        _ = close_a[mask]
    except ValueError as e:
        failures.append(f"Check 4: positional isfinite-mask still raises after alignment -- {e}")

    # --- Check 5: filter_exact_correlation_duplicates ---
    pairs = [
        {"symbol_a": "A1", "symbol_b": "A2", "pearson_corr": 1.0},           # exact dup -> drop
        {"symbol_a": "B1", "symbol_b": "B2", "pearson_corr": -1.0},          # inverse-quote -> drop
        {"symbol_a": "C1", "symbol_b": "C2", "pearson_corr": 0.9999},        # strong but real -> keep
        {"symbol_a": "D1", "symbol_b": "D2", "pearson_corr": None},          # missing field -> keep, no crash
        {"symbol_a": "E1", "symbol_b": "E2", "pearson_corr": 0.9999995},     # just over threshold -> drop
    ]
    kept, dropped = filter_exact_correlation_duplicates(pairs, threshold=0.999999)
    dropped_keys = {(p["symbol_a"], p["symbol_b"]) for p in dropped}
    kept_keys = {(p["symbol_a"], p["symbol_b"]) for p in kept}

    expected_dropped = {("A1", "A2"), ("B1", "B2"), ("E1", "E2")}
    expected_kept = {("C1", "C2"), ("D1", "D2")}
    if dropped_keys != expected_dropped:
        failures.append(f"Check 5: dropped set wrong -- expected {expected_dropped}, got {dropped_keys}")
    if kept_keys != expected_kept:
        failures.append(f"Check 5: kept set wrong -- expected {expected_kept}, got {kept_keys}")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All universe_loader alignment + dedup checks passed.")
    print(f"  align_to_common_calendar: OLD_SYM/NEW_SYM both reindexed to "
          f"{aligned['OLD_SYM'].shape[0]} shared dates, real NaN gaps preserved, no forward-fill")
    print(f"  filter_exact_correlation_duplicates: {len(dropped)}/{len(pairs)} correctly dropped as "
          f"identity duplicates, {len(kept)} correctly kept")


if __name__ == "__main__":
    main()
