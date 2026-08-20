"""
Synthetic verification of international_liquidity_filter.py::fetch_currency_
codes -- rewritten 2026-08-13 to SEQUENTIAL per-pair queries after real,
measured evidence (see the function's own docstring) that batched (gvkey,
iid) IN (...) / JOIN-VALUES queries all hit the SAME ~0.55-0.65s/pair wall
against comp_global_daily.g_secd regardless of query shape, while a bare
single-pair equality lookup resolved in 0.11s -- the batched approach was
both the cause of the original 2026-08-12 hang AND, even after a date-bound
fix, still too slow to ever complete a single 500-pair batch within any
sane statement_timeout. This test replaces the prior batched-interface
version (which mocked IN-clause tuple parsing) entirely.

Checks:
  1. A db whose .raw_sql() raises on exactly ONE pair's query (simulating a
     transient drop mid-loop), then succeeds on retry -- that pair is still
     resolved, not silently skipped, and no OTHER pair is re-queried.
  2. Pairs already resolved before the failing pair are NOT re-queried after
     the reconnect (the per-pair loop naturally only retries the pair that
     was mid-flight when it failed, not the whole list from scratch).
  3. Giving up after max_retries interrupted attempts on the SAME pair
     raises, not silently returns partial results as if complete.
  4. A pair with no rows in the trailing window (empty result) resolves to
     simply ABSENT from the output dict, not a crash or a None-valued entry.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re

import pandas as pd

from research.international_liquidity_filter import fetch_currency_codes


class _FakeDB:
    """Each raw_sql call answers exactly ONE pair's single-pair query (the
    new interface's shape: `where gvkey = 'X' and iid = 'Y' ... limit 1`)."""

    def __init__(self, fail_on_pairs=None, empty_pairs=None):
        self.fail_on_pairs = set(fail_on_pairs or [])
        self.empty_pairs = set(empty_pairs or [])
        self.queried_pairs = []

    def raw_sql(self, q):
        m = re.search(r"gvkey = '(\w+)' and iid = '(\w+)'", q)
        g, iid = m.group(1), m.group(2)
        if (g, iid) in self.fail_on_pairs:
            self.fail_on_pairs.discard((g, iid))  # fail only ONCE per pair, then succeed on retry
            raise ConnectionError("simulated mid-loop drop")
        self.queried_pairs.append((g, iid))
        if (g, iid) in self.empty_pairs:
            return pd.DataFrame({"curcdd": []})
        return pd.DataFrame({"curcdd": ["USD"]})


def main():
    failures = []
    pairs = [(f"G{i:04d}", "01W") for i in range(50)]

    # --- Check 1+2: one pair (the 30th) fails once, then succeeds on retry ---
    dbs = []
    failing_pair = pairs[29]

    def db_getter():
        db = _FakeDB(fail_on_pairs=[failing_pair] if not dbs else [])
        dbs.append(db)
        return db

    result = fetch_currency_codes(db_getter, pairs, max_retries=5)
    if len(result) != len(pairs):
        failures.append(f"Check 1: expected all {len(pairs)} pairs resolved, got {len(result)}")
    if failing_pair not in result:
        failures.append(f"Check 1: the pair that failed once ({failing_pair}) should still be "
                         f"resolved after retry, was not found in result")
    if len(dbs) != 2:
        failures.append(f"Check 1: expected exactly 1 reconnect (2 db_getter calls), got {len(dbs)}")

    # Check 2: pairs BEFORE the failing one should be queried exactly once,
    # on the FIRST db (not re-queried after reconnect); pairs at/after the
    # failing one are queried on the SECOND db (the failing pair retried,
    # everything after it continuing normally on the new connection).
    pairs_before = pairs[:29]
    if dbs[0].queried_pairs != pairs_before:
        failures.append(f"Check 2: first db should have resolved exactly the 29 pairs before the "
                         f"failure, got {len(dbs[0].queried_pairs)} pairs: {dbs[0].queried_pairs[:3]}...")
    if failing_pair not in dbs[1].queried_pairs:
        failures.append(f"Check 2: second db (post-reconnect) should have retried the failing pair")
    total_queried = len(dbs[0].queried_pairs) + len(dbs[1].queried_pairs)
    if total_queried != len(pairs):
        failures.append(f"Check 2: total pairs queried across both connections should equal "
                         f"{len(pairs)} (no duplicate re-querying of already-resolved pairs), "
                         f"got {total_queried}")

    # --- Check 3: gives up after max_retries on a pair that NEVER succeeds ---
    class _AlwaysFailDB(_FakeDB):
        def raw_sql(self, q):
            m = re.search(r"gvkey = '(\w+)' and iid = '(\w+)'", q)
            g, iid = m.group(1), m.group(2)
            if (g, iid) == pairs[0]:
                raise ConnectionError("simulated permanent failure")
            return super().raw_sql(q)

    try:
        fetch_currency_codes(lambda: _AlwaysFailDB(), pairs[:3], max_retries=2)
        failures.append("Check 3: should have raised after exhausting max_retries, did not")
    except Exception:
        pass  # expected

    # --- Check 4: empty result (no rows in trailing window) -> pair absent, not crashed ---
    empty_pair = ("G9999", "01W")
    db4 = _FakeDB(empty_pairs=[empty_pair])
    result4 = fetch_currency_codes(lambda: db4, [empty_pair], max_retries=2)
    if empty_pair in result4:
        failures.append(f"Check 4: a pair with no rows in the trailing window should be ABSENT "
                         f"from the result dict, got {result4}")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All currency-lookup (sequential per-pair) retry checks passed.")
    print(f"  Check 1: {len(result)}/{len(pairs)} resolved after 1 simulated single-pair drop")
    print(f"  Check 2: no duplicate re-querying across reconnect ({total_queried} total)")
    print(f"  Check 3: correctly raised after exhausting max_retries on a permanently-failing pair")
    print(f"  Check 4: empty-result pair correctly absent from output, not crashed")


if __name__ == "__main__":
    main()
