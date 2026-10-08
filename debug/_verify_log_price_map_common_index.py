"""
Regression test for the A1 residual found by the 2026-10-07 independent check: research scripts (17 call
DataAligner.align_universe without analysis.align_to_common_index -- e.g. research/bh_vs_by_full_universe.py:79-104)
pass per-symbol-span frames into CointScanner._build_log_price_map and then _eg_worker, which needs row i to be the
same timestamp for both legs: a symbol starting 300 bars later gave "operands could not be broadcast together"
(the checker's repro) -- the pair silently never tested. Fix at the shared point: _build_log_price_map aligns its
inputs onto one union index (no fill) itself, so every caller gets row-aligned arrays.
Checks: two frames with different spans -> equal-length arrays whose finite rows line up on the same timestamps;
_eg_worker on them returns ok=True; frames already on one index are unchanged.
Run: python debug/_verify_log_price_map_common_index.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import analysis

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    idx = pd.bdate_range("2015-01-01", periods=800)
    rng = np.random.default_rng(1)
    common = 50 * np.exp(np.cumsum(rng.normal(0, .01, 800)))
    a = pd.DataFrame({"close": common}, index=idx)
    b = pd.DataFrame({"close": common[300:] * 1.5}, index=idx[300:])     # B starts 300 bars later
    lp = analysis.CointScanner._build_log_price_map({"A": a, "B": b}, ["A", "B"])
    la, lb = lp["A"], lp["B"]
    check("equal_lengths", len(la) == len(lb), f"{len(la)} vs {len(lb)}")
    both = np.isfinite(la) & np.isfinite(lb)
    check("rows_line_up", both.sum() == 500 and np.allclose((la - lb)[both], -np.log(1.5)), int(both.sum()))
    r = analysis._eg_worker(("A", "B", la, lb, 1, "1day"))
    check("eg_worker_ok", bool(r.get("ok")), r.get("error"))
    same = analysis.CointScanner._build_log_price_map({"A": a, "C": a * 2}, ["A", "C"])
    check("already_aligned_unchanged", len(same["A"]) == 800 and len(same["C"]) == 800)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
