"""
Synthetic verification for IBKRFeed.get_bars_paginated() (BUG-D70/task
#72, 2026-07-14). Mocks the IBKR connection and reqHistoricalData so the
PAGINATION LOGIC (chunking, dedup, stop conditions) is tested without a
real network dependency — real-data confirmation is a separate,
necessarily-live follow-up step, not a substitute for this.

Mocks both self._ib.reqHistoricalData (returns a scripted sequence of
chunk results) and ibi.util.df (bypassed — we control the DataFrame
shape directly, since constructing real ib_insync BarData objects isn't
needed to test the pagination logic itself). reqHistoricalData's mock
returns a LIST wrapping each chunk DataFrame (matching the real API,
which returns a list of BarData objects — production code's `if not
bars:` check needs a real list, not a DataFrame directly, to be
well-defined; caught by the first test run raising "truth value of a
DataFrame is ambiguous" when the mock skipped the list-wrapping step).
"""
import os
import sys
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data as data_module
from data import IBKRFeed


def _make_chunk(start_date, n_bars, freq="h"):
    idx = pd.date_range(end=start_date, periods=n_bars, freq=freq)
    return pd.DataFrame({
        "date": idx, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000,
    })


def test_stops_at_target_duration():
    """3 chunks of 21 days each = 63 days, target='60 D' -> should stop
    after chunk 3 (60 <= 63), not run to max_chunks."""
    feed = IBKRFeed()
    call_log = []

    def fake_req(contract, endDateTime, durationStr, **kwargs):
        call_log.append(endDateTime)
        chunk_end = pd.Timestamp("2026-01-01") if not endDateTime else pd.Timestamp(endDateTime)
        return [_make_chunk(chunk_end, n_bars=21 * 24)]  # 21 days of hourly bars, list-wrapped

    with patch.object(feed, "ensure_connected", return_value=True), \
         patch.object(feed, "_build_contract", return_value=object()), \
         patch.object(feed, "_wait_rate_limit", return_value=None), \
         patch.object(data_module.ibi.util, "df", side_effect=lambda bars: bars[0]):
        feed._ib = type("FakeIB", (), {"reqHistoricalData": staticmethod(fake_req), "RequestTimeout": 20})()
        result = feed.get_bars_paginated("TEST", "equity", "1 hour",
                                          target_duration="60 D", chunk_duration="21 D", max_chunks=40)

    assert result is not None, "expected a non-None result"
    assert len(call_log) == 3, f"expected exactly 3 chunks (63>=60 days), got {len(call_log)}"
    print(f"PASS: stopped at {len(call_log)} chunks for a 60-day target with 21-day chunks")


def test_stops_at_empty_chunk():
    """First 2 chunks succeed, 3rd returns empty (real historical
    boundary) -> should stop there, not treat it as an error, and still
    return the 2 real chunks' data."""
    feed = IBKRFeed()
    call_count = [0]

    def fake_req(contract, endDateTime, durationStr, **kwargs):
        call_count[0] += 1
        if call_count[0] >= 3:
            return []  # empty -> real boundary
        chunk_end = pd.Timestamp("2026-01-01") if not endDateTime else pd.Timestamp(endDateTime)
        return [_make_chunk(chunk_end, n_bars=21 * 24)]

    with patch.object(feed, "ensure_connected", return_value=True), \
         patch.object(feed, "_build_contract", return_value=object()), \
         patch.object(feed, "_wait_rate_limit", return_value=None), \
         patch.object(data_module.ibi.util, "df", side_effect=lambda bars: bars[0]):
        feed._ib = type("FakeIB", (), {"reqHistoricalData": staticmethod(fake_req), "RequestTimeout": 20})()
        result = feed.get_bars_paginated("TEST", "equity", "1 hour",
                                          target_duration="10 Y", chunk_duration="21 D", max_chunks=40)

    assert result is not None, "expected data from the 2 successful chunks"
    assert call_count[0] == 3, f"expected exactly 3 calls (2 success + 1 empty stop), got {call_count[0]}"
    print(f"PASS: stopped cleanly at the empty chunk (call {call_count[0]}), "
          f"returned {len(result)} bars from the 2 real chunks")


def test_respects_max_chunks_safety_cap():
    """Every chunk succeeds forever (simulates a symbol that never hits
    a real boundary) -> must stop at max_chunks, not loop forever."""
    feed = IBKRFeed()
    call_count = [0]

    def fake_req(contract, endDateTime, durationStr, **kwargs):
        call_count[0] += 1
        chunk_end = pd.Timestamp("2026-01-01") if not endDateTime else pd.Timestamp(endDateTime)
        return [_make_chunk(chunk_end, n_bars=21 * 24)]

    with patch.object(feed, "ensure_connected", return_value=True), \
         patch.object(feed, "_build_contract", return_value=object()), \
         patch.object(feed, "_wait_rate_limit", return_value=None), \
         patch.object(data_module.ibi.util, "df", side_effect=lambda bars: bars[0]):
        feed._ib = type("FakeIB", (), {"reqHistoricalData": staticmethod(fake_req), "RequestTimeout": 20})()
        result = feed.get_bars_paginated("TEST", "equity", "1 hour",
                                          target_duration="100 Y", chunk_duration="21 D", max_chunks=5)

    assert call_count[0] == 5, f"expected exactly max_chunks=5 calls, got {call_count[0]}"
    print(f"PASS: respected max_chunks safety cap ({call_count[0]} calls, no infinite loop)")


def test_dedups_overlapping_bars():
    """Two chunks with a deliberately overlapping timestamp -> combined
    result must not contain the duplicate."""
    feed = IBKRFeed()
    chunks = [
        _make_chunk(pd.Timestamp("2026-01-10"), n_bars=5),
        _make_chunk(pd.Timestamp("2026-01-08"), n_bars=5),  # overlaps chunk 1's range
    ]
    call_count = [0]

    def fake_req(contract, endDateTime, durationStr, **kwargs):
        c = [chunks[call_count[0]]] if call_count[0] < len(chunks) else []
        call_count[0] += 1
        return c

    with patch.object(feed, "ensure_connected", return_value=True), \
         patch.object(feed, "_build_contract", return_value=object()), \
         patch.object(feed, "_wait_rate_limit", return_value=None), \
         patch.object(data_module.ibi.util, "df", side_effect=lambda bars: bars[0]):
        feed._ib = type("FakeIB", (), {"reqHistoricalData": staticmethod(fake_req), "RequestTimeout": 20})()
        result = feed.get_bars_paginated("TEST", "equity", "1 hour",
                                          target_duration="2 D", chunk_duration="1 D", max_chunks=2)

    n_unique_expected = len(chunks[0].set_index("date").index.union(chunks[1].set_index("date").index))
    assert len(result) == n_unique_expected, (
        f"expected {n_unique_expected} deduped bars, got {len(result)}"
    )
    assert not result.index.duplicated().any(), "result contains duplicate timestamps"
    print(f"PASS: deduped overlapping chunks correctly ({len(result)} unique bars)")


if __name__ == "__main__":
    test_stops_at_target_duration()
    test_stops_at_empty_chunk()
    test_respects_max_chunks_safety_cap()
    test_dedups_overlapping_bars()
    print("\nAll pagination logic tests passed.")
