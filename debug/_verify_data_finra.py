"""Synthetic proof for data_finra.py's caching behavior -- confirms
cache_short_interest reads from disk on a repeat call rather than
re-fetching, using a mocked fetch so this doesn't depend on network
access. The real endpoint itself was already confirmed working manually
(2026-08-14 settlement date, 22,482 securities, real NYSE-listed names
like Agilent/Alcoa present -- not OTC-only despite the URL's
'otcmarket' path component)."""
import os
import shutil
import sys
import tempfile
from unittest import mock

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data_finra

n_checks = 0
n_passed = 0


def check(name, cond):
    global n_checks, n_passed
    n_checks += 1
    status = "PASS" if cond else "FAIL"
    if cond:
        n_passed += 1
    print(f"[{status}] {name}")


tmp_dir = tempfile.mkdtemp()
try:
    with mock.patch.object(data_finra, "_OUT_DIR", tmp_dir):
        fake_df = pd.DataFrame({"symbolCode": ["A", "AA"], "currentShortPositionQuantity": [100, 200]})
        call_count = [0]

        def fake_fetch(date):
            call_count[0] += 1
            return fake_df

        with mock.patch.object(data_finra, "fetch_short_interest", side_effect=fake_fetch):
            result1 = data_finra.cache_short_interest("2026-08-14")
            check("first call returns the real data", result1.equals(fake_df))
            check("first call actually fetched (network mock called once)", call_count[0] == 1)

            result2 = data_finra.cache_short_interest("2026-08-14")
            check("second call for the SAME date reads from cache, does not re-fetch",
                  call_count[0] == 1)
            check("cached result matches the original", result2.equals(fake_df))

    # --- A settlement date with no published file returns None, not a crash ---
    with mock.patch.object(data_finra, "_OUT_DIR", tmp_dir):
        with mock.patch.object(data_finra, "fetch_short_interest", return_value=None):
            result3 = data_finra.cache_short_interest("2026-01-01")
            check("a date with no published file returns None, not a crash", result3 is None)
finally:
    shutil.rmtree(tmp_dir, ignore_errors=True)

print(f"\n{n_passed}/{n_checks} checks passed")
sys.exit(0 if n_passed == n_checks else 1)
