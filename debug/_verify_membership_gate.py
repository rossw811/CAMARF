"""
Synthetic verification of the point-in-time S&P 500 membership gate wired
into build_rolling_eg_tasks (2026-08-11, Ross's direct observation) BEFORE
trusting it on the real re-scan.

Checks:
  1. A pair where one symbol was NOT yet an S&P 500 member at an early
     window's end date, but became a member before a later window, must
     NOT get EG-tested on the early window (the actual gap this closes) --
     but MUST get tested on the later window once it's a genuine member.
  2. A symbol with NO permno resolution (absent from permno_by_symbol) is
     NOT gated at all -- "unresolved" must never be silently treated as
     "ineligible" (would be a false exclusion, not a fix).
  3. membership_df=None (gate not loaded) reproduces the exact pre-fix
     behavior -- every window tested regardless of membership.
  4. A multi-spell membership (removed then re-added) is handled correctly:
     a window whose end date falls in the GAP between two spells is
     excluded, even though the symbol has SOME membership record.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from research.wrds_deep_history_episodic_scan import build_rolling_eg_tasks


def main():
    failures = []

    window, step = 40, 20
    n_bars = 200
    dates = pd.date_range("2020-01-01", periods=n_bars, freq="24h")

    # A/B: fully correlated throughout (correlation isn't under test here --
    # only the membership gate). C is a THIRD symbol used for the gap-spell
    # check.
    rng = np.random.default_rng(3)
    shared = rng.normal(size=n_bars) * 0.02
    log_price_df = pd.DataFrame(
        {
            "A": np.cumsum(shared) + 100,
            "B": np.cumsum(shared * 0.98 + rng.normal(size=n_bars) * 0.0005) + 100,
            "C": np.cumsum(shared * 0.97 + rng.normal(size=n_bars) * 0.0005) + 100,
        },
        index=dates,
    )
    array_cache = {s: log_price_df[s].to_numpy() for s in log_price_df.columns}

    # Windows: [0:40] end=dates[39], [20:60] end=dates[59], [40:80] end=dates[79], ...
    # B becomes a member partway through (window covering dates[79] onward).
    membership_df = pd.DataFrame([
        {"permno": 1, "mbrstartdt": dates[0], "mbrenddt": pd.NaT, "is_current": True},        # A: always
        {"permno": 2, "mbrstartdt": dates[70], "mbrenddt": pd.NaT, "is_current": True},        # B: joins late
        # C: two spells with a GAP -- member early, removed, re-added late.
        {"permno": 3, "mbrstartdt": dates[0], "mbrenddt": dates[59], "is_current": False},
        {"permno": 3, "mbrstartdt": dates[140], "mbrenddt": pd.NaT, "is_current": True},
    ])
    permno_by_symbol = {"A": 1, "B": 2, "C": 3}

    pairs_ab = [{"symbol_a": "A", "symbol_b": "B"}]
    pairs_ac = [{"symbol_a": "A", "symbol_b": "C"}]

    # --- 1: A/B gated correctly (B joins late) ---
    tasks_ab, meta_ab = build_rolling_eg_tasks(
        pairs_ab, log_price_df, max_lag=1, window=window, step=step, array_cache=array_cache,
        membership_df=membership_df, permno_by_symbol=permno_by_symbol,
    )
    early_windows_ab = [m for m in meta_ab if m[5] < dates[70]]
    late_windows_ab = [m for m in meta_ab if m[5] >= dates[70]]
    if early_windows_ab:
        failures.append(f"A/B: {len(early_windows_ab)} window(s) tested before B joined "
                         f"the index (dates[70]={dates[70]}) -- membership gate not working")
    if not late_windows_ab:
        failures.append("A/B: no windows tested after B legitimately joined -- gate may be "
                         "overly conservative")

    # --- 2: unresolved symbol (no permno) is NOT gated ---
    permno_by_symbol_missing_b = {"A": 1}  # B has no permno resolution
    tasks_ab2, meta_ab2 = build_rolling_eg_tasks(
        pairs_ab, log_price_df, max_lag=1, window=window, step=step, array_cache=array_cache,
        membership_df=membership_df, permno_by_symbol=permno_by_symbol_missing_b,
    )
    if len(meta_ab2) != len(meta_ab) + len(early_windows_ab):
        # Should behave like NO gate at all for this pair (unresolved -> untouched)
        expected_total = ((n_bars - window) // step + 1) * 2  # both directions
        if len(meta_ab2) < expected_total - 2:  # allow off-by-one boundary
            failures.append(f"A/B with B unresolved: expected ~{expected_total} windows tested "
                             f"(no gating for unresolved symbols), got {len(meta_ab2)}")

    # --- 3: membership_df=None reproduces pre-fix behavior (no gating at all) ---
    tasks_nogate, meta_nogate = build_rolling_eg_tasks(
        pairs_ab, log_price_df, max_lag=1, window=window, step=step, array_cache=array_cache,
        membership_df=None, permno_by_symbol=None,
    )
    if len(meta_nogate) != len(meta_ab2):
        failures.append(f"membership_df=None should test the same window count as the "
                         f"unresolved-symbol case ({len(meta_ab2)}), got {len(meta_nogate)}")

    # --- 4: gap-spell handling for C ---
    tasks_ac, meta_ac = build_rolling_eg_tasks(
        pairs_ac, log_price_df, max_lag=1, window=window, step=step, array_cache=array_cache,
        membership_df=membership_df, permno_by_symbol=permno_by_symbol,
    )
    gap_windows = [m for m in meta_ac if dates[59] < m[5] < dates[140]]
    if gap_windows:
        failures.append(f"A/C: {len(gap_windows)} window(s) tested during C's membership GAP "
                         f"(dates[59]={dates[59]} to dates[140]={dates[140]}) -- multi-spell "
                         f"membership not handled correctly")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All membership-gate checks passed.")
    print(f"  A/B: {len(meta_ab)} windows tested (0 before B joined), "
          f"{len(early_windows_ab)} early excluded")
    print(f"  A/B unresolved-B: {len(meta_ab2)} windows tested (ungated)")
    print(f"  A/B membership_df=None: {len(meta_nogate)} windows tested (ungated)")
    print(f"  A/C: {len(meta_ac)} windows tested, {len(gap_windows)} gap-window(s) excluded")


if __name__ == "__main__":
    main()
