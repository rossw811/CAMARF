"""
Synthetic verification of research/event_study_framework.py -- run BEFORE
trusting it against real spread_series/earnings data.

Checks:
  1. frame_series_around_events correctly re-indexes a window to RELATIVE
     offset (0 = event bar), for a single known event with an exact,
     hand-computed expected window.
  2. Multiple events produce one column per event, correctly aligned
     independently (no cross-event leakage).
  3. An event falling PAST the end of the series is silently excluded (not
     a crash, not a spuriously truncated/misaligned column).
  4. macro_regime_transition_dates correctly identifies ONLY the dates where
     the label actually changes, not every date, and not the first date
     (which has no "prior" to compare against).
  5. frame_pair_around_earnings correctly unions BOTH legs' earnings dates
     (an event date known only for leg B still frames the pair's spread).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from research.event_study_framework import (
    frame_series_around_events, macro_regime_transition_dates, frame_pair_around_earnings,
)


def main():
    failures = []

    # --- Check 1: exact known window for a single event ---
    idx = pd.date_range("2024-01-01", periods=30, freq="D")
    series = pd.Series(np.arange(30, dtype=float), index=idx)  # series[i] == i, trivial to verify
    event_date = idx[15]
    framed1 = frame_series_around_events(series, [event_date], window_before=3, window_after=3)
    expected = {off: 15 + off for off in range(-3, 4)}
    for off, exp_val in expected.items():
        got = framed1[event_date].loc[off]
        if got != exp_val:
            failures.append(f"Check 1: offset {off} expected {exp_val}, got {got}")

    # --- Check 2: multiple independent events, no cross-leakage ---
    event2 = idx[20]
    framed2 = frame_series_around_events(series, [event_date, event2], window_before=2, window_after=2)
    if framed2.shape[1] != 2:
        failures.append(f"Check 2: expected 2 event columns, got {framed2.shape[1]}")
    if framed2[event2].loc[0] != 20:
        failures.append(f"Check 2: event2's offset-0 value should be 20, got {framed2[event2].loc[0]}")
    if framed2[event_date].loc[0] != 15:
        failures.append(f"Check 2: event1's offset-0 value should still be 15 (no leakage from "
                         f"event2), got {framed2[event_date].loc[0]}")

    # --- Check 3: event past the series' end is excluded, not crashed ---
    far_future_event = pd.Timestamp("2030-01-01")
    framed3 = frame_series_around_events(series, [event_date, far_future_event],
                                          window_before=2, window_after=2)
    if far_future_event in framed3.columns:
        failures.append(f"Check 3: an event past the series' end should be excluded, "
                         f"got it in columns: {framed3.columns.tolist()}")
    if event_date not in framed3.columns:
        failures.append(f"Check 3: the valid event should still be present alongside the "
                         f"excluded one")

    # --- Check 4: regime transition dates ---
    regime = pd.Series(
        ["low", "low", "low", "elevated", "elevated", "high", "low", "low"],
        index=pd.date_range("2024-01-01", periods=8, freq="D"),
    )
    transitions = macro_regime_transition_dates(regime)
    expected_transitions = [regime.index[3], regime.index[5], regime.index[6]]
    if transitions != expected_transitions:
        failures.append(f"Check 4: expected transitions at indices 3,5,6, got {transitions}")
    if regime.index[0] in transitions:
        failures.append(f"Check 4: the FIRST date should never be a transition, got it included")

    # --- Check 5: frame_pair_around_earnings unions both legs' dates ---
    class _FakeCal:
        dates_by_symbol = {"AAA": [idx[10]], "BBB": [idx[18]]}  # disjoint sets

    framed5 = frame_pair_around_earnings(series, "AAA", "BBB", _FakeCal(),
                                          window_before=1, window_after=1)
    if framed5.shape[1] != 2:
        failures.append(f"Check 5: expected 2 event columns (one per leg's earnings date, disjoint "
                         f"sets), got {framed5.shape[1]}")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All event-study framework checks passed.")
    print(f"  Check 1: exact window recovery -> {dict(framed1[event_date])}")
    print(f"  Check 2: {framed2.shape[1]} independent events, no leakage")
    print(f"  Check 3: far-future event correctly excluded")
    print(f"  Check 4: transitions correctly identified at {transitions}")
    print(f"  Check 5: {framed5.shape[1]} events from both legs' disjoint earnings dates")


if __name__ == "__main__":
    main()
