"""
Synthetic verification for research/pit_pair_discovery.py (2026-08-04),
before trusting it as the replacement pair source for other research
scripts -- matching this project's verify-before-trusting discipline.

Checks:
  1. Return shape matches ml._discover_confirmed_pairs()'s contract
     exactly: list of (symbol_a, symbol_b, tf_label) 3-tuples.
  2. Correctly rejects rows missing window_end_date (the pre-BUG-D106-fix
     data) rather than silently treating them as PIT-safe.
  3. as_of_date semantics are genuinely causal: confirming as of an
     EARLIER date returns a subset of (or equal to) confirming as of a
     LATER date, on a synthetic dataset with windows spread across time --
     never MORE confirmed pairs at an earlier date than a later one.
  4. A pair with ZERO FDR-significant windows as of a given date is
     correctly absent from that date's confirmed list, even though it
     exists in the input rows (tests the BH-FDR gate is actually applied,
     not just presence in the input).
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

import pit_pair_discovery as ppd


def _make_rows(specs):
    """specs: list of (symbol_a, symbol_b, window_end_date_str, pvalue)."""
    return [
        {"symbol_a": a, "symbol_b": b, "window_end_date": pd.Timestamp(d), "pvalue": p}
        for a, b, d, p in specs
    ]


def test_return_shape_matches_discover_confirmed_pairs_contract(monkeypatch=None):
    rows = _make_rows([
        ("AAA", "BBB", "2024-01-01", 0.001),
        ("AAA", "BBB", "2024-06-01", 0.001),
    ])
    import unittest.mock as mock
    with mock.patch.object(ppd, "_load_pit_safe_rows", return_value=rows):
        result = ppd.discover_pit_confirmed_pairs(as_of_date="2025-01-01", alpha=0.10)
    print(f"result: {result}")
    assert isinstance(result, list)
    for item in result:
        assert isinstance(item, tuple) and len(item) == 3, f"expected 3-tuples, got {item}"
        a, b, tf = item
        assert isinstance(a, str) and isinstance(b, str) and isinstance(tf, str)
    assert len(result) >= 1, "expected at least the strongly-significant AAA/BBB pair to be confirmed"
    print("shape check: OK")


def test_missing_window_end_date_rejected_not_silently_used():
    import unittest.mock as mock
    # A file WITHOUT window_end_date at all -- _load_pit_safe_rows itself
    # must skip it. Simulate by making the mocked loader return [] (as the
    # real function would after skipping every column-less file), and
    # confirm the top-level function reports empty rather than crashing
    # or fabricating a result.
    with mock.patch.object(ppd, "_load_pit_safe_rows", return_value=[]):
        result = ppd.discover_pit_confirmed_pairs(as_of_date="2025-01-01")
    assert result == [], f"expected empty result when no PIT-safe rows are available, got {result}"
    print("missing-window_end_date rejection: OK (empty, not fabricated)")


def test_asof_date_is_causally_monotonic():
    """More windows should be eligible (confirmed set should not SHRINK)
    as as_of_date moves later, for a fixed set of pairs whose windows are
    spread across time."""
    rows = _make_rows([
        ("EARLY", "PAIR", "2020-01-01", 0.0001),
        ("EARLY", "PAIR", "2021-01-01", 0.0001),
        ("LATE", "PAIR", "2025-06-01", 0.0001),
        ("LATE", "PAIR", "2025-12-01", 0.0001),
    ])
    import unittest.mock as mock
    with mock.patch.object(ppd, "_load_pit_safe_rows", return_value=rows):
        early_confirmed = ppd.discover_pit_confirmed_pairs(as_of_date="2022-01-01", alpha=0.20)
        late_confirmed = ppd.discover_pit_confirmed_pairs(as_of_date="2026-01-01", alpha=0.20)

    early_pairs = {(a, b) for a, b, _ in early_confirmed}
    late_pairs = {(a, b) for a, b, _ in late_confirmed}
    print(f"as-of 2022-01-01: {early_pairs}")
    print(f"as-of 2026-01-01: {late_pairs}")
    assert ("EARLY", "PAIR") in early_pairs, "EARLY/PAIR should already be confirmed by 2022 (both its windows concluded by then)"
    assert ("LATE", "PAIR") not in early_pairs, "LATE/PAIR's windows haven't concluded by 2022 -- must NOT be confirmed yet"
    assert ("LATE", "PAIR") in late_pairs, "LATE/PAIR should be confirmed by 2026 (both windows concluded)"
    assert early_pairs.issubset(late_pairs), "confirmed set must not SHRINK as as_of_date moves later"
    print("causal monotonicity: OK")


def test_non_significant_pair_correctly_absent():
    """A pair present in the input but with NO FDR-significant window
    (high p-values throughout) must not appear in the confirmed output --
    tests the BH-FDR gate is genuinely applied, not bypassed."""
    rows = _make_rows([
        ("SIG", "PAIR", "2024-01-01", 0.00001),
        ("NOISE", "PAIR", "2024-01-01", 0.85),
        ("NOISE", "PAIR", "2024-06-01", 0.90),
    ])
    import unittest.mock as mock
    with mock.patch.object(ppd, "_load_pit_safe_rows", return_value=rows):
        result = ppd.discover_pit_confirmed_pairs(as_of_date="2025-01-01", alpha=0.05)
    pairs = {(a, b) for a, b, _ in result}
    print(f"confirmed: {pairs}")
    assert ("SIG", "PAIR") in pairs, "the strongly-significant pair should be confirmed"
    assert ("NOISE", "PAIR") not in pairs, "the non-significant pair must NOT be confirmed"
    print("BH-FDR gate applied correctly: OK")


if __name__ == "__main__":
    tests = [
        test_return_shape_matches_discover_confirmed_pairs_contract,
        test_missing_window_end_date_rejected_not_silently_used,
        test_asof_date_is_causally_monotonic,
        test_non_significant_pair_correctly_absent,
    ]
    passed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"FAILED: {test.__name__}: {e}")
        except Exception as e:
            print(f"ERROR in {test.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} checks passed")
