"""
Regression test (A1 follow-up, 2026-09-27): research/pit_wfa_wrds_daily.py and research/threshold_relevance_pit_test.py
pass DataAligner.align_universe's per-symbol spans straight into CointScanner.scan / rolling_fraction, skipping the
align_to_common_index step analysis.py and pit_wfa use. EG pairs arrays by position, so any pair whose legs list on
different dates hit the A1 broadcast error and was silently never tested.
Fix: scan and rolling_fraction reindex their candidate symbols onto one shared index themselves (no-op when the index
is already shared).
Checks (cointegrated synthetic pair, B listed 300 bars after A, called exactly as the research scripts do):
  1. scan tests the pair (ok, p < 0.01) and confirms it;
  2. rolling_fraction returns a finite fraction for it;
  3. align_to_common_index returns the same objects when the index is already shared (no copy).
Run: python debug/_verify_scan_guard_direct_callers.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from analysis import CointScanner, align_to_common_index
from data import DataAligner

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def _ohlcv(idx, close):
    return pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": 1e6}, index=idx)


def main():
    idx = pd.bdate_range("2015-01-01", periods=1800)
    rng = np.random.default_rng(3)
    x = np.cumsum(rng.normal(0, 0.01, len(idx))) + 4.0
    spread = np.zeros(len(idx))
    for t in range(1, len(idx)):
        spread[t] = 0.9 * spread[t - 1] + rng.normal(0, 0.005)
    a = _ohlcv(idx, np.exp(x))
    b = _ohlcv(idx[300:], np.exp(0.8 * x[300:] + 0.5 + spread[300:]))
    aligned = DataAligner.align_universe({"AAA_1D": a, "BBB_1D": b}, "1D")
    check("precondition_different_spans", len(aligned["AAA"]) != len(aligned["BBB"]),
          f"{len(aligned['AAA'])} vs {len(aligned['BBB'])}")
    cands = [{"symbol_a": "AAA", "symbol_b": "BBB", "pearson_r": 0.9}]
    confirmed, stats = CointScanner.scan(cands, aligned, ["AAA", "BBB"], "1D", n_workers=1)
    pv = confirmed[0].get("eg_pvalue", confirmed[0].get("p_value")) if confirmed else None
    check("scan_tests_and_confirms", len(confirmed) == 1, f"confirmed={len(confirmed)} stats={stats} p={pv}")
    if confirmed:
        rf = CointScanner.rolling_fraction(confirmed, aligned, "1D", n_workers=1)
        frac = rf[0].get("coint_fraction_rolling")
        check("rolling_fraction_finite", frac is not None and np.isfinite(frac), f"fraction={frac}")
    common = align_to_common_index(aligned)
    again = align_to_common_index(common)
    check("fast_path_no_copy", all(again[k] is common[k] for k in common))
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
