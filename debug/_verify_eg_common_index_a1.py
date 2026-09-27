"""
Regression test for code-review finding A1 (2026-09-26): DataAligner.align_universe trims each asset to
its own first valid date, so symbols end up with arrays of DIFFERENT lengths; analysis.py's positional
consumers (CointScanner._build_log_price_map -> _eg_worker's isfinite(a) & isfinite(b) mask, rolling
coint, Johansen, _build_pair_result) then raised a broadcast ValueError that _eg_worker swallowed as
ok=False -- every pair whose histories start on different dates was never EG-tested (and excluded from
BH's m). Reproduced on real AAPL/MSFT/ABNB. Fix: analysis.align_to_common_index() reindexes every
aligned frame onto the union timestamp index (NO forward-fill: missing bars stay NaN) right after
alignment, so positional arrays are date-aligned by construction.

Checks, through the real production path (align_universe -> align_to_common_index ->
_build_log_price_map -> _eg_worker):
  1. two COINTEGRATED synthetic daily series with different start dates: ok=True, p < 0.01, and
     n_overlap equals the true overlap (not the longer series' length);
  2. every aligned array has the same length and the same row -> same date;
  3. no values are invented: rows before an asset's first date are NaN.

Run: python debug/_verify_eg_common_index_a1.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from analysis import CointScanner, _eg_worker, align_to_common_index
from data import DataAligner

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    rng = np.random.default_rng(3)
    days = pd.bdate_range("2012-01-02", "2019-12-31")
    common = np.cumsum(rng.normal(0, 0.01, len(days)))            # shared stochastic trend
    a = np.exp(4.0 + common + rng.normal(0, 0.005, len(days)))
    b = np.exp(3.0 + 0.8 * common + rng.normal(0, 0.005, len(days)))
    start_b = 800                                                  # B lists ~3 years later
    mk = lambda px, idx: pd.DataFrame({"open": px, "high": px * 1.001, "low": px * 0.999, "close": px,
                                       "volume": 1e6}, index=idx)
    raw = {"AAA_1D": mk(a, days), "BBB_1D": mk(b[start_b:], days[start_b:])}
    aligned = DataAligner.align_universe(raw, "1D")
    common_al = align_to_common_index(aligned)
    lens = {k: len(v) for k, v in common_al.items()}
    check("equal_lengths", len(set(lens.values())) == 1, f"{lens}")
    k0, k1 = sorted(common_al)
    check("same_dates_per_row", common_al[k0].index.equals(common_al[k1].index))
    pre = common_al[k1].loc[:days[start_b - 1], "close"]
    check("no_invented_values_before_listing", len(pre) > 0 and pre.isna().all(), f"non-NaN before listing: {pre.notna().sum()}")

    lp = CointScanner._build_log_price_map(common_al, list(common_al))
    r = _eg_worker((k0, k1, lp[k0], lp[k1], 1, "1D"))
    check("eg_runs", bool(r.get("ok")), f"{ {k: r.get(k) for k in ('ok', 'error', 'pvalue', 'n_overlap')} }")
    check("eg_detects_cointegration", r.get("ok") and r.get("pvalue", 1) < 0.01, f"p={r.get('pvalue')}")
    # Exact ground truth: rows where BOTH aligned series have a price. (First draft used
    # len(bdate_range) - start_b with a +-15 tolerance, but the NYSE calendar drops ~9 holidays a
    # year -- ~45 over this span -- so that expectation, not the module, was wrong.)
    exp_overlap = int((common_al[k0]["close"].notna() & common_al[k1]["close"].notna()).sum())
    check("n_overlap_is_true_overlap", r.get("ok") and r.get("n_overlap", 0) == exp_overlap,
          f"n_overlap={r.get('n_overlap')} expected={exp_overlap}")
    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
