"""
debug/_verify_cross_listing_lead_lag.py -- synthetic ground-truth
verification for research/cross_listing_lead_lag.py, BEFORE trusting it
against the real 36 multi-listed companies found in the fetched
international WRDS dataset.

Core claims verified:
  1. find_multi_listing_gvkeys correctly groups cached files by gvkey and
     only returns gvkeys with 2+ DISTINCT iid listings actually on disk
     (not the theoretical constituent list -- a listing that failed to
     fetch must not appear).
  2. build_cross_listing_pairs produces exactly C(k,2) unique pairs per
     gvkey (no double-counting, no missing combinations) for k>=2 listings.
  3. End-to-end: a synthetic pair of same-company listings with a real,
     known cross-time-zone lag (one listing's price leads the other's by a
     fixed number of bars) IS flagged by scan_pair (reused unmodified from
     wrds_lead_lag_scan.py), while a synthetic pair with pure
     arbitrage-enforced contemporaneous parity (no real lag, just
     near-identical prices) is NOT flagged -- confirming the script
     correctly distinguishes "genuine cross-time-zone information flow"
     from "same value, no lag" per its own stated hypothesis.

Run: python debug/_verify_cross_listing_lead_lag.py
(All checks are synthetic/offline -- no WRDS connection needed.)
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research.cross_listing_lead_lag as cll

_TEST_CACHE_DIR = cll._WRDS_CACHE_DIR


def check(name, cond):
    cond = bool(cond)
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}")
    return cond


def _write_test_symbol(label, close_values):
    idx = pd.date_range("2015-01-01", periods=len(close_values), freq="B")
    df = pd.DataFrame({"close": close_values}, index=idx)
    os.makedirs(_TEST_CACHE_DIR, exist_ok=True)
    path = os.path.join(_TEST_CACHE_DIR, f"{label}_1D.parquet")
    df.to_parquet(path)
    return path


def verify_find_multi_listing_gvkeys():
    print("\n=== 1. find_multi_listing_gvkeys: groups by gvkey, only gvkeys with 2+ listings ===")
    written = []
    written.append(_write_test_symbol("GVKEY900001_01W", np.linspace(100, 110, 50)))
    written.append(_write_test_symbol("GVKEY900001_02W", np.linspace(200, 210, 50)))
    written.append(_write_test_symbol("GVKEY900002_01W", np.linspace(50, 55, 50)))  # only 1 listing
    written.append(_write_test_symbol("GVKEY900003_01W", np.linspace(10, 12, 50)))
    written.append(_write_test_symbol("GVKEY900003_02W", np.linspace(20, 22, 50)))
    written.append(_write_test_symbol("GVKEY900003_03W", np.linspace(30, 32, 50)))

    multi = cll.find_multi_listing_gvkeys(cache_dir=_TEST_CACHE_DIR)

    ok = check("gvkey 900001 (2 listings) present", "900001" in multi)
    ok &= check("gvkey 900002 (1 listing only) absent", "900002" not in multi)
    ok &= check("gvkey 900003 (3 listings) present with all 3 labels",
                "900003" in multi and len(multi["900003"]) == 3)

    for p in written:
        os.remove(p)
    return ok


def verify_build_cross_listing_pairs():
    print("\n=== 2. build_cross_listing_pairs: exactly C(k,2) unique pairs, no double-counting ===")
    multi = {
        "A": ["GVKEYA_01W", "GVKEYA_02W"],
        "B": ["GVKEYB_01W", "GVKEYB_02W", "GVKEYB_03W"],
    }
    pairs = cll.build_cross_listing_pairs(multi)
    pairs_a = [p for p in pairs if p[0] == "A"]
    pairs_b = [p for p in pairs if p[0] == "B"]

    ok = check("gvkey A (2 listings) produces exactly 1 pair", len(pairs_a) == 1)
    ok &= check("gvkey B (3 listings) produces exactly 3 pairs (C(3,2)=3)", len(pairs_b) == 3)
    ok &= check("no pair appears twice (both directions)",
                len(set((p[1], p[2]) for p in pairs)) == len(pairs))
    return ok


def verify_end_to_end_scan_pair():
    print("\n=== 3. End-to-end: genuine cross-time-zone lag IS flagged; pure parity is NOT ===")
    n = 400
    rng = np.random.RandomState(11)

    # Pair 1: genuine lag -- listing 2's price today reflects listing 1's
    # price from `lag` sessions ago (simulating later-arriving information
    # from a different time zone), plus its own idiosyncratic noise.
    lag = 6
    log_1 = np.cumsum(rng.normal(0, 1.0, n))
    ret_1 = np.diff(log_1, prepend=log_1[0])
    ret_2 = np.roll(ret_1, lag) + rng.normal(0, 0.08, n)
    ret_2[:lag] = rng.normal(0, 1.0, lag)
    log_2 = np.cumsum(ret_2)
    _write_test_symbol("GVKEY910001_01W", np.exp(log_1))
    _write_test_symbol("GVKEY910001_02W", np.exp(log_2))

    # Pair 2: pure arbitrage-enforced parity -- same value, tiny idiosyncratic
    # noise, NO real lag. Should NOT be flagged.
    log_3 = np.cumsum(rng.normal(0, 1.0, n))
    log_4 = log_3 + rng.normal(0, 0.02, n)
    _write_test_symbol("GVKEY910002_01W", np.exp(log_3))
    _write_test_symbol("GVKEY910002_02W", np.exp(log_4))

    from config import Config
    result1 = cll.scan_pair("GVKEY910001_01W", "GVKEY910001_02W", max_lag=15, min_lift=0.05,
                             max_eg_lag=Config.ANALYSIS.EG_MAX_LAG)
    result2 = cll.scan_pair("GVKEY910002_01W", "GVKEY910002_02W", max_lag=15, min_lift=0.05,
                             max_eg_lag=Config.ANALYSIS.EG_MAX_LAG)

    ok = check("genuine cross-listing lag pair: no skip_reason", "skip_reason" not in result1)
    if "skip_reason" not in result1:
        ok &= check(f"genuine lag pair IS flagged (best_lag={result1['best_lag']}, expect {lag})",
                    result1["flagged_lag_worth_checking"] and result1["best_lag"] == lag)
    ok &= check("pure-parity pair: no skip_reason", "skip_reason" not in result2)
    if "skip_reason" not in result2:
        ok &= check(f"pure-parity pair NOT flagged (best_lag={result2['best_lag']}, expect 0)",
                    not result2["flagged_lag_worth_checking"])

    for lbl in ("GVKEY910001_01W", "GVKEY910001_02W", "GVKEY910002_01W", "GVKEY910002_02W"):
        p = os.path.join(_TEST_CACHE_DIR, f"{lbl}_1D.parquet")
        if os.path.exists(p):
            os.remove(p)
    return ok


def main():
    results = [
        verify_find_multi_listing_gvkeys(),
        verify_build_cross_listing_pairs(),
        verify_end_to_end_scan_pair(),
    ]
    print("\n" + "=" * 60)
    if all(results):
        print("ALL CHECKS PASSED")
    else:
        print(f"FAILURES: {results.count(False)}/{len(results)} check groups failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
