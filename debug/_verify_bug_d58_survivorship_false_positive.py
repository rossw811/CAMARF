"""
Verifies the BUG-D58 fix in backtest.py: resolve_survivorship_oos_end() must distinguish a
symbol that was merely demoted out of the S&P 500 index (still trading, real data continues
long after the "removed" date) from a symbol that was genuinely delisted (real data actually
stops at/near the "removed" date).

Real-data motivation (Development.md, 2026-07-12): DD's survivorship exclusion entry claims
"removed" 2017-09-01, but DD has real, continuous spread_series data through 2026 -- it was
demoted from the S&P 500, never delisted. The pre-fix code truncated its OOS window to before
this project's data even starts, silently zeroing out every DD pair (5/24 confirmed 1h pairs).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from backtest import resolve_survivorship_oos_end

CASES = [
    # (label, candidate_oos_end, data_last_seen, expect_truncation)
    (
        "No exclusion entry at all",
        None, pd.Timestamp("2026-01-01"), False,
    ),
    (
        "DD-like: 'removed' 2017, real data continues to 2026 (false positive, demoted not delisted)",
        pd.Timestamp("2017-09-01"), pd.Timestamp("2026-07-01"), False,
    ),
    (
        "Genuine delisting: 'removed' date, data stops right around it (within slack)",
        pd.Timestamp("2023-06-01"), pd.Timestamp("2023-06-15"), True,
    ),
    (
        "Genuine delisting: data stops slightly BEFORE the removed date (normal, still truncate)",
        pd.Timestamp("2023-06-01"), pd.Timestamp("2023-05-20"), True,
    ),
    (
        "Borderline: data extends exactly at the 90-day slack boundary (should NOT trigger false-positive)",
        pd.Timestamp("2023-01-01"), pd.Timestamp("2023-01-01") + pd.Timedelta(days=89), True,
    ),
    (
        "Just past the slack boundary (SHOULD trigger false-positive, no truncation)",
        pd.Timestamp("2023-01-01"), pd.Timestamp("2023-01-01") + pd.Timedelta(days=91), False,
    ),
]


def main():
    failures = []
    for label, candidate, last_seen, expect_truncation in CASES:
        result = resolve_survivorship_oos_end(candidate, last_seen)
        actually_truncated = result is not None
        status = "OK" if actually_truncated == expect_truncation else "MISMATCH"
        if actually_truncated != expect_truncation:
            failures.append(f"{label}: expected truncation={expect_truncation}, got {actually_truncated} (result={result})")
        print(f"{status}  {label}  ->  oos_end={result}")

    print()
    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("BUG-D58 fix verified: false-positive 'demoted not delisted' symbols are no longer "
          "truncated, while genuine delistings still are.")


if __name__ == "__main__":
    main()
