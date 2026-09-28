"""
Regression test (A1 follow-up, 2026-09-27): UniverseFilter.build_returns_matrix stacked each symbol's returns by
LEFT-padding to a common width -- which assumes every symbol ENDS on the same bar. DataAligner.align_universe
returns per-symbol frames with their own spans, so a symbol that ends earlier (a delisted WRDS name, a stale cache
file) was shifted against every other symbol and its correlations were computed across mismatched dates. analysis.py
and pit_wfa reindex to a common index first (A1 fix), but ~20 research scripts call align_universe ->
build_returns_matrix directly.
Fix: build_returns_matrix aligns on the frames' real timestamps (union index, no fill; last _MAX_COLS timestamps kept)
and returns that index.
Checks:
  1. B = same returns as A but ends 10 bars earlier (delisted): corr(A, B) == 1 (was ~0 with left-padding);
  2. inputs that already share one index give exactly the same matrix as before (the post-A1 production path);
  3. the returned index is the timestamp of each column.
Run: python debug/_verify_returns_matrix_timestamp_aligned.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from analysis import UniverseFilter, align_to_common_index

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def _frame(idx, close):
    return pd.DataFrame({"close": close, "gap_flag": np.zeros(len(idx), dtype=np.int8), "is_gap": False}, index=idx)


def main():
    idx = pd.bdate_range("2020-01-01", periods=600)
    px = 100 * np.exp(np.cumsum(np.random.default_rng(0).normal(0, 0.01, len(idx))))
    a = _frame(idx, px)
    b = _frame(idx[:-10], px[:-10] * 3.0)              # identical returns, delisted 10 bars earlier
    R, syms, ridx = UniverseFilter.build_returns_matrix({"A": a, "B": b}, min_overlap=100)
    m = np.isfinite(R[0]) & np.isfinite(R[1])
    c = np.corrcoef(R[0][m], R[1][m])[0, 1]
    check("delisted_leg_aligned_by_timestamp", abs(c - 1) < 1e-12, f"corr={c:.4f}")
    check("returned_index_is_columns", len(ridx) == R.shape[1] and ridx[-1] == idx[-1], f"len={len(ridx)} cols={R.shape[1]}")

    common = align_to_common_index({"A": a, "B": _frame(idx[5:], px[5:] * 2)})
    R2, _, _ = UniverseFilter.build_returns_matrix(common, min_overlap=100)
    from analysis import gap_aware_returns
    exp = np.vstack([gap_aware_returns(common["A"]), gap_aware_returns(common["B"])])
    check("common_index_input_unchanged", R2.shape == exp.shape and np.array_equal(np.isnan(R2), np.isnan(exp))
          and np.allclose(R2[np.isfinite(R2)], exp[np.isfinite(exp)]))
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
