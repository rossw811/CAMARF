"""
Synthetic verification for research/data_contamination_scan.py (task #51).

Tests the pure detection/classification logic directly (no live network
calls — fetch_splits() itself is a thin, un-mockable-here yfinance wrapper,
same as BUG-D65's own verification approach of testing the decision logic
against synthetic split/event data rather than mocking the network).

Cases:
  1. Append-seam jump (first 1% of rows), no matching synthetic split/macro
     window -> flagged, shape=append_seam, unexplained.
  2. Mid-series jump that DOES match a synthetic injected split (checked via
     split_explains_event directly) -> explained=True.
  3. Jump whose date falls inside a known macro-crisis window -> explained
     via _macro_explained.
  4. Mid-series jump with no matching split and outside any macro window ->
     flagged, shape=mid_series, unexplained (the "second contamination
     mechanism" case this scan is also designed to catch).
  5. Ordinary small gap (<15%) -> not flagged at all.
"""
import os
import sys
import tempfile

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.data_contamination_scan import (
    scan_series_for_jumps,
    split_explains_event,
    _macro_explained,
)


def _make_series(dates, closes):
    return pd.DataFrame({"close": closes}, index=pd.to_datetime(dates))


def test_append_seam_unexplained():
    n = 500
    dates = pd.date_range("2023-01-01", periods=n, freq="h")
    closes = np.full(n, 100.0)
    # a stale fragment at the very start, on a different price basis
    closes[:3] = 40.0
    df = _make_series(dates, closes)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "TEST_1hr.parquet")
        df.to_parquet(path)
        events, err = scan_series_for_jumps(path)
    assert err is None, f"unexpected read error: {err}"
    assert len(events) == 1, f"expected 1 jump event, got {len(events)}: {events}"
    e = events[0]
    assert e["shape"] == "append_seam", f"expected append_seam shape, got {e['shape']}"
    assert e["position_frac"] < 0.02
    # no synthetic split/macro window supplied -> would be unexplained downstream
    explained, _, _ = split_explains_event(e["date"], e["magnitude"], splits=None)
    assert explained is False
    assert _macro_explained(e["date"]) is False
    print("[PASS] append-seam jump correctly detected and classified unexplained")


def test_matches_synthetic_split():
    # Observed ratio of a jump from 50 -> 100 is +1.0 (100%). A synthetic
    # 2-for-1 split (factor=2.0) recorded near that date should explain it.
    jump_date = pd.Timestamp("2024-06-15")
    magnitude = 1.0  # (100/50) - 1
    synthetic_splits = pd.Series([2.0], index=[jump_date])
    explained, matched_factor, rel_err = split_explains_event(jump_date, magnitude, synthetic_splits)
    assert explained is True, f"expected synthetic 2-for-1 split to explain a +100% jump, got rel_err={rel_err}"
    assert abs(matched_factor - 2.0) < 1e-9
    print("[PASS] jump matching a synthetic recorded split correctly explained")


def test_reverse_split_reciprocal_orientation():
    # A 1-for-3 reverse split recorded as factor=0.3333 should also explain
    # an observed ~3x jump via the reciprocal check (BUG-D65's own lesson:
    # yfinance's split-factor sign convention isn't reliable in one direction).
    jump_date = pd.Timestamp("2024-06-15")
    magnitude = 2.0  # (300/100) - 1, a 3x jump
    synthetic_splits = pd.Series([1.0 / 3.0], index=[jump_date])
    explained, matched_factor, rel_err = split_explains_event(jump_date, magnitude, synthetic_splits)
    assert explained is True, f"expected reciprocal-orientation match, got rel_err={rel_err}"
    print("[PASS] reverse-split (reciprocal orientation) jump correctly explained")


def test_macro_window_explained():
    covid_crash_date = pd.Timestamp("2020-03-16")
    assert _macro_explained(covid_crash_date) is True
    unrelated_date = pd.Timestamp("2021-05-01")
    assert _macro_explained(unrelated_date) is False
    print("[PASS] macro-crisis-window dates correctly classified")


def test_mid_series_unexplained_second_mechanism():
    n = 500
    dates = pd.date_range("2023-01-01", periods=n, freq="h")
    closes = np.full(n, 100.0)
    mid = n // 2
    closes[mid:] = 250.0  # an unexplained jump in the MIDDLE of the series
    df = _make_series(dates, closes)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "TEST2_1hr.parquet")
        df.to_parquet(path)
        events, err = scan_series_for_jumps(path)
    assert err is None
    assert len(events) == 1
    e = events[0]
    assert e["shape"] == "mid_series", f"expected mid_series shape, got {e['shape']}"
    assert not (e["position_frac"] < 0.02 or e["position_frac"] > 0.98)
    explained, _, _ = split_explains_event(e["date"], e["magnitude"], splits=None)
    assert explained is False
    assert _macro_explained(e["date"]) is False
    print("[PASS] mid-series unexplained jump (second contamination mechanism) correctly detected")


def test_ordinary_gap_not_flagged():
    n = 200
    dates = pd.date_range("2023-01-01", periods=n, freq="h")
    rng = np.random.default_rng(42)
    closes = 100.0 + np.cumsum(rng.normal(0, 0.3, n))
    closes[50] = closes[49] * 1.05  # a 5% gap, well under the 15% threshold
    df = _make_series(dates, closes)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "TEST3_1hr.parquet")
        df.to_parquet(path)
        events, err = scan_series_for_jumps(path)
    assert err is None
    assert len(events) == 0, f"expected no flagged events for an ordinary <15% gap, got {events}"
    print("[PASS] ordinary small gap correctly NOT flagged")


if __name__ == "__main__":
    test_append_seam_unexplained()
    test_matches_synthetic_split()
    test_reverse_split_reciprocal_orientation()
    test_macro_window_explained()
    test_mid_series_unexplained_second_mechanism()
    test_ordinary_gap_not_flagged()
    print("\nAll BUG-D65-adjacent (task #51) verification tests passed.")
