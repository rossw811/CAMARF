"""
debug/_verify_wrds_lead_lag_scan.py -- synthetic ground-truth verification
for research/wrds_lead_lag_scan.py, BEFORE trusting it against real WRDS
data (which requires research/wrds_deep_history_episodic_scan.py to have
already produced confirmed-pair output -- not yet available when this test
was written, hence synthetic-only).

Core claims verified:
  1. load_price_series correctly prefers close_total_return when present,
     falls back to close otherwise (Compustat Global convention).
  2. lagged_corr_scan correctly recovers a KNOWN, engineered lead-lag
     relationship (B's return today = A's return from k days ago + noise).
  3. load_confirmed_pairs correctly parses BOTH the Tier 1 format (filters
     on fdr_confirmed==True) and the Tier 2/3 format (already-confirmed-only
     rows, no filter column).
  4. scan_pair end-to-end on synthetic WRDS-cache-shaped parquet files
     produces the expected flagged/not-flagged verdict for both a genuine
     lead-lag pair and a genuinely contemporaneous (lag-0) pair.

Run: python debug/_verify_wrds_lead_lag_scan.py
(All checks are synthetic/offline -- no WRDS connection needed.)
"""
import os
import shutil
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research.wrds_lead_lag_scan as wll


def check(name, cond):
    cond = bool(cond)
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}")
    return cond


_TEST_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "output", "cache", "wrds")


def _write_test_symbol(label, close_values, close_total_return_values=None):
    idx = pd.date_range("2015-01-01", periods=len(close_values), freq="B")
    data = {"close": close_values}
    if close_total_return_values is not None:
        data["close_total_return"] = close_total_return_values
    df = pd.DataFrame(data, index=idx)
    os.makedirs(_TEST_CACHE_DIR, exist_ok=True)
    path = os.path.join(_TEST_CACHE_DIR, f"{label}_1D.parquet")
    df.to_parquet(path)
    return path


def verify_load_price_series_prefers_total_return():
    print("\n=== 1. load_price_series: prefers close_total_return, falls back to close ===")
    n = 100
    close = np.linspace(100, 110, n)
    tr = np.linspace(100, 120, n)  # deliberately different from close
    path_with_tr = _write_test_symbol("TEST_WITH_TR", close, tr)
    path_without_tr = _write_test_symbol("TEST_WITHOUT_TR", close)

    series_with_tr = wll.load_price_series("TEST_WITH_TR")
    series_without_tr = wll.load_price_series("TEST_WITHOUT_TR")

    ok = check("with close_total_return present, uses IT (not close) -- last value matches log(120), not log(110)",
               series_with_tr is not None and abs(series_with_tr.iloc[-1] - np.log(120)) < 1e-6)
    ok &= check("with no close_total_return, falls back to close -- last value matches log(110)",
                series_without_tr is not None and abs(series_without_tr.iloc[-1] - np.log(110)) < 1e-6)

    ok &= check("missing symbol returns None, not a crash",
                wll.load_price_series("TOTALLY_NONEXISTENT_SYMBOL_XYZ") is None)

    for p in (path_with_tr, path_without_tr):
        os.remove(p)
    return ok


def verify_lagged_corr_scan_recovers_known_lag():
    print("\n=== 2. lagged_corr_scan: recovers a KNOWN, engineered lead-lag relationship ===")
    n = 500
    rng = np.random.RandomState(0)
    ret_a = pd.Series(rng.normal(0, 1.0, n))
    # B's return TODAY equals A's return from 5 days AGO, plus small noise --
    # i.e. A leads B by 5 bars. lag=5 should show corr(ret_a_t, ret_b_{t+5}) high.
    true_lag = 5
    ret_b = ret_a.shift(true_lag).fillna(0) + pd.Series(rng.normal(0, 0.2, n))

    scan = wll.lagged_corr_scan(ret_a, ret_b, max_lag=10)
    k_star, c_star, n_star = wll.best_lag(scan)

    ok = check(f"recovered lag ({k_star}) matches the true engineered lag ({true_lag})",
               k_star == true_lag)
    ok &= check(f"correlation at the true lag is strong (got {c_star:.3f}, expect > 0.8)",
                c_star is not None and c_star > 0.8)
    c0, n0 = scan.get(0, (None, 0))
    ok &= check(f"correlation at lag 0 is much weaker than at the true lag "
                f"(lag0={c0:.3f} vs lag5={c_star:.3f})",
                c0 is not None and abs(c0) < abs(c_star) - 0.2)
    return ok


def verify_load_confirmed_pairs_both_formats():
    print("\n=== 3. load_confirmed_pairs: parses Tier 1 (fdr_confirmed filter) and Tier 2/3 (pre-filtered) formats ===")
    research_dir = wll._RESEARCH_DIR
    os.makedirs(research_dir, exist_ok=True)

    tier1_path = os.path.join(research_dir, "wrds_deep_history_episodic_scan_tier1.parquet")
    tier1_df = pd.DataFrame([
        {"symbol_a": "A", "symbol_b": "B", "fdr_confirmed": True},
        {"symbol_a": "C", "symbol_b": "D", "fdr_confirmed": False},
        {"symbol_a": "E", "symbol_b": "F", "fdr_confirmed": True},
    ])
    tier1_df.to_parquet(tier1_path, index=False)

    tier2_path = os.path.join(research_dir, "wrds_deep_history_episodic_scan_tier2_confirmed.parquet")
    tier2_df = pd.DataFrame([
        {"symbol_a": "X", "symbol_b": "Y", "n_windows_fdr_rejected": 3},
    ])
    tier2_df.to_parquet(tier2_path, index=False)

    tier1_pairs = wll.load_confirmed_pairs(1)
    tier2_pairs = wll.load_confirmed_pairs(2)
    tier3_pairs_missing = wll.load_confirmed_pairs(3)  # file doesn't exist -- must not crash

    ok = check("Tier 1: only fdr_confirmed==True rows included (2 of 3)",
               set(tier1_pairs) == {("A", "B"), ("E", "F")})
    ok &= check("Tier 2: all rows included (no filter column expected)",
                tier2_pairs == [("X", "Y")])
    ok &= check("Tier 3 with no file present returns empty list, not a crash",
                tier3_pairs_missing == [])

    os.remove(tier1_path)
    os.remove(tier2_path)
    return ok


def verify_scan_pair_end_to_end():
    print("\n=== 4. scan_pair: end-to-end on synthetic WRDS-cache-shaped data ===")
    n = 400
    rng = np.random.RandomState(1)

    # Pair 1: genuine lead-lag (A leads B by 8 bars) -- should FLAG.
    log_a1 = np.cumsum(rng.normal(0, 1.0, n))
    ret_a1 = np.diff(log_a1, prepend=log_a1[0])
    lag = 8
    ret_b1 = np.roll(ret_a1, lag) + rng.normal(0, 0.05, n)
    ret_b1[:lag] = rng.normal(0, 1.0, lag)
    log_b1 = np.cumsum(ret_b1)
    _write_test_symbol("LLTEST_A1", np.exp(log_a1))
    _write_test_symbol("LLTEST_B1", np.exp(log_b1))

    # Pair 2: genuinely contemporaneous (lag 0) -- should NOT flag.
    log_a2 = np.cumsum(rng.normal(0, 1.0, n))
    log_b2 = log_a2 + rng.normal(0, 0.05, n)
    _write_test_symbol("LLTEST_A2", np.exp(log_a2))
    _write_test_symbol("LLTEST_B2", np.exp(log_b2))

    from config import Config
    result1 = wll.scan_pair("LLTEST_A1", "LLTEST_B1", max_lag=15, min_lift=0.05,
                             max_eg_lag=Config.ANALYSIS.EG_MAX_LAG)
    result2 = wll.scan_pair("LLTEST_A2", "LLTEST_B2", max_lag=15, min_lift=0.05,
                             max_eg_lag=Config.ANALYSIS.EG_MAX_LAG)

    ok = check("genuine lead-lag pair: no skip_reason (enough data)", "skip_reason" not in result1)
    if "skip_reason" not in result1:
        ok &= check(f"genuine lead-lag pair IS flagged (best_lag={result1['best_lag']}, expect {lag})",
                    result1["flagged_lag_worth_checking"] and result1["best_lag"] == lag)
    ok &= check("contemporaneous pair: no skip_reason (enough data)", "skip_reason" not in result2)
    if "skip_reason" not in result2:
        ok &= check(f"contemporaneous pair is NOT flagged (best_lag={result2['best_lag']}, expect 0)",
                    not result2["flagged_lag_worth_checking"] and result2["best_lag"] == 0)

    for lbl in ("LLTEST_A1", "LLTEST_B1", "LLTEST_A2", "LLTEST_B2"):
        p = os.path.join(_TEST_CACHE_DIR, f"{lbl}_1D.parquet")
        if os.path.exists(p):
            os.remove(p)
    return ok


def main():
    results = [
        verify_load_price_series_prefers_total_return(),
        verify_lagged_corr_scan_recovers_known_lag(),
        verify_load_confirmed_pairs_both_formats(),
        verify_scan_pair_end_to_end(),
    ]
    print("\n" + "=" * 60)
    if all(results):
        print("ALL CHECKS PASSED")
    else:
        print(f"FAILURES: {results.count(False)}/{len(results)} check groups failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
