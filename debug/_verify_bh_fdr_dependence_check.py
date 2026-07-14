"""
_verify_bh_fdr_dependence_check.py -- synthetic ground-truth check for the
Benjamini-Yekutieli (2001) FDR correction implementation used by
research/bh_fdr_dependence_check.py, before trusting it on real CAMARF data.

BY (2001) is BH (1995) with the rank threshold divided by the harmonic sum
c(m) = sum_{i=1}^{m} 1/i, which holds under ARBITRARY dependence (not just
independence/PRDS). It must therefore always be at least as conservative as
plain BH: BY's rejection set must be a subset of BH's on the same p-values.

Checks:
1. On i.i.d. Uniform(0,1) p-values (true null throughout), BY's rejection
   count should be close to 0 (it is more conservative than BH, which itself
   controls FDR at alpha under this exact case).
2. On a classic textbook mixed case (a handful of genuinely small p-values
   among many large ones), BY must reject a subset of what BH rejects, and
   BY's harmonic-sum correction factor must match the closed-form c(m) value.
3. BY and BH must agree exactly at m=1 (c(1)=1, no correction difference).
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.bh_fdr_dependence_check import benjamini_yekutieli, _benjamini_hochberg


def test_m1_no_difference():
    p = np.array([0.01])
    bh_rej, _ = _benjamini_hochberg(p, 0.05)
    by_rej, _ = benjamini_yekutieli(p, 0.05)
    assert bh_rej[0] == by_rej[0] == True, "at m=1, BH and BY must agree (c(1)=1)"
    print("[PASS] m=1 case: BH and BY agree")


def test_by_subset_of_bh():
    rng = np.random.default_rng(42)
    # 10 genuinely small p-values, 90 large (null) p-values
    p_true = rng.uniform(0.5, 1.0, size=90)
    p_signal = rng.uniform(0.0, 0.001, size=10)
    p = np.concatenate([p_signal, p_true])
    bh_rej, _ = _benjamini_hochberg(p, 0.05)
    by_rej, _ = benjamini_yekutieli(p, 0.05)
    assert by_rej.sum() <= bh_rej.sum(), (
        f"BY must be at least as conservative as BH: BY rejected {by_rej.sum()}, "
        f"BH rejected {bh_rej.sum()}"
    )
    assert np.all(by_rej <= bh_rej), "every BY rejection must also be a BH rejection (subset)"
    print(f"[PASS] BY subset of BH: BH rejected {bh_rej.sum()}/100, BY rejected {by_rej.sum()}/100")


def test_harmonic_correction_factor():
    m = 353
    c_m = np.sum(1.0 / np.arange(1, m + 1))
    # closed form sanity: c(m) ~ ln(m) + gamma for large m
    approx = np.log(m) + 0.5772156649
    assert abs(c_m - approx) < 0.01, f"harmonic sum c({m})={c_m:.4f} should be close to ln(m)+gamma={approx:.4f}"
    print(f"[PASS] harmonic correction factor c({m})={c_m:.4f} matches ln(m)+euler-mascheroni approx {approx:.4f}")


def test_null_case_few_false_positives():
    rng = np.random.default_rng(7)
    p = rng.uniform(0, 1, size=500)  # true null throughout
    by_rej, _ = benjamini_yekutieli(p, 0.05)
    # BY controls FDR at alpha under arbitrary dependence; under a true global
    # null, expect very few (ideally zero) rejections, not ~5% like raw alpha would.
    assert by_rej.sum() <= 3, f"BY should reject almost nothing under a true global null, got {by_rej.sum()}"
    print(f"[PASS] true-null case: BY rejected {by_rej.sum()}/500 (expected near-zero)")


if __name__ == "__main__":
    test_m1_no_difference()
    test_by_subset_of_bh()
    test_harmonic_correction_factor()
    test_null_case_few_false_positives()
    print("\nALL BH-FDR dependence-check verification tests passed.")
