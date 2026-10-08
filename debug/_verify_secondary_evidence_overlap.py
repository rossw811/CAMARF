"""
Regression test for code review A5 (verified 2026-10-07, fixed the same day): the coint_frac secondary-evidence
override (AnalysisPipeline.passes_coint_frac_secondary_evidence) required n_bars >= 3*252 before trusting "no break"
from Zivot-Andrews/CUSUM, but n_bars = log_a.size counts the dense aligned grid INCLUDING bars where either leg is
NaN. The break tests run on finite spread values only (ZA returns None below 200, CUSUM below 100) and None is read
as "no break", so a pair with a long grid but little real overlap could be rescued by tests that had too little
data (BUG-D68's own failure mode). Real data: output/results/1day/pairs.parquet had 2 below-threshold pairs eligible
by n_bars but with n_overlap < 756. Fix: eligibility counts n_overlap (both legs finite).
Checks: n_bars 1000 / n_overlap 300 -> NOT eligible; n_overlap 800 -> eligible (clean tests, falling half-life);
an object without n_overlap falls back to refusing (no silent pass).
Run: python debug/_verify_secondary_evidence_overlap.py
"""
import os
import sys
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import AnalysisPipeline

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def p(**kw):
    base = dict(n_bars=1000, n_overlap=800, half_life_trend_slope=-0.01, zivot_andrews_break=None,
                cusum_first_excursion=None)
    base.update(kw)
    return SimpleNamespace(**base)


def main():
    f = AnalysisPipeline.passes_coint_frac_secondary_evidence
    check("long_grid_short_overlap_refused", f(p(n_overlap=300)) is False)
    check("enough_overlap_passes", f(p(n_overlap=800)) is True)
    q = p(); del q.n_overlap
    check("missing_overlap_refused", f(q) is False)
    check("break_found_refused", f(p(zivot_andrews_break="2020-01-01")) is False)
    check("nan_overlap_refused", f(p(n_overlap=np.nan)) is False)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
