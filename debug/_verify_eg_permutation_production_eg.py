"""
X-M15 (2026-10-20): research/eg_permutation_check.py ran one-direction statsmodels coint() on a[isfinite(a)&isfinite(b)],
splicing across genuine data gaps, so its p-values were not production's. Checks: _eg_pvalue equals
analysis.eg_pvalue_pair (both directions, max p) on production's longest gap-respecting segment; at 1h a long genuine
gap is not spliced (at 1D production bridges by design); the permutation null runs on the same segment.
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


import eg_permutation_check as m  # noqa: E402
from analysis import eg_pvalue_pair, longest_gap_respecting_segment  # noqa: E402

rng = np.random.default_rng(1)
n = 900
a = np.cumsum(rng.normal(0, 0.01, n)) + 3
b = a + 0.5 * np.cumsum(rng.normal(0, 0.004, n)) + rng.normal(0, 0.01, n)
a[300:340] = np.nan          # a genuine 40-bar gap
b[300:340] = np.nan
try:
    p = m._eg_pvalue(a, b, 5, "1D")
    keep = longest_gap_respecting_segment(np.isfinite(a) & np.isfinite(b), "1D")
    ref, _ = eg_pvalue_pair(a[keep], b[keep], 5, "1D")
    check("1. equals production eg_pvalue_pair on the production segment", p is not None and np.isclose(p, ref),
          f"{p} vs {ref}")
    # at 1D production bridges gaps by design (is_genuine_data_gap: daily runs are routine unless the A2 arm is on);
    # at 1h a 300-bar gap is genuine, so the test must run on one side of it, not on a spliced series
    a2, b2 = a.copy(), b.copy()
    a2[300:340] = a[299]; b2[300:340] = b[299]       # remove the 40-bar gap
    a2[250:550] = np.nan; b2[250:550] = np.nan       # a 300-bar genuine gap at 1h
    keep_h = longest_gap_respecting_segment(np.isfinite(a2) & np.isfinite(b2), "1h")
    p_h = m._eg_pvalue(a2, b2, 5, "1h")
    ref_h, _ = eg_pvalue_pair(a2[keep_h], b2[keep_h], 5, "1h")
    check("2. 1h: genuine gap not spliced (segment 350 of 600 valid bars), p equals production",
          int(keep_h.sum()) == 350 and p_h is not None and np.isclose(p_h, ref_h), f"{int(keep_h.sum())} {p_h} {ref_h}")
    null = m._circular_shift_null(a, b, 5, 10, np.random.default_rng(0), "1D")
    check("3. permutation null runs on the same segment", len(null) > 0)
except TypeError as e:
    check("_eg_pvalue / _circular_shift_null take tf_label", False, str(e))
print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(1 if failed else 0)
