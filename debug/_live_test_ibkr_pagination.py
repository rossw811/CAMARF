"""
Live (non-mocked) test of IBKRFeed.get_bars_paginated() (task #72,
2026-07-14). Synthetic mocks already verified the chunking/dedup/stop-
condition logic (debug/_verify_ibkr_pagination.py, 4/4 pass) — this
confirms the real IB Gateway round-trip actually accumulates more history
than the single-request ~21-30 day ceiling found in task #71.

Usage: python debug/_live_test_ibkr_pagination.py [target_duration]
Default target_duration="60 D" (a quick ~3-chunk smoke test); pass "2 Y"
for the full-depth run once the smoke test passes.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import IBKRFeed

target = sys.argv[1] if len(sys.argv) > 1 else "60 D"

feed = IBKRFeed()


def _on_error(reqId, errorCode, errorString, contract=None):
    print(f"IBKR ERROR EVENT: reqId={reqId} code={errorCode} msg={errorString!r}")


if not feed.connect():
    print("IBKR connect failed")
    sys.exit(1)
feed._ib.errorEvent += _on_error

result = feed.get_bars_paginated(
    "LNT", "equity", "1 hour", target_duration=target, chunk_duration="21 D", max_chunks=40
)

if result is None or result.empty:
    print("RESULT: None/empty — pagination returned nothing")
else:
    print(f"RESULT: {len(result)} bars, {result.index.min()} to {result.index.max()}")
    span_days = (result.index.max() - result.index.min()).days
    print(f"Real calendar span: {span_days} days (target was {target!r})")
    dupes = result.index.duplicated().sum()
    print(f"Duplicate timestamps: {dupes}")

feed.disconnect() if hasattr(feed, "disconnect") else None
