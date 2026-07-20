"""
Synthetic verification for research/fdr_method_comparison.py's apply_all_methods()
(2026-07-16, Ross's request to compare step-up BH, Benjamini-Yekutieli, two-stage
TSBH, and fixed-threshold Bonferroni on the same raw p-value population).

Two checks, both against ground truth, not against each other in isolation:
1. Bit-for-bit cross-check of all 4 methods against statsmodels'
   multipletests() on the same textbook 15-value example already used
   earlier this session to verify _benjamini_hochberg and benjamini_yekutieli
   individually -- confirms apply_all_methods() wires each method up
   correctly (no transposed args, no alpha/m mixups) rather than re-proving
   each algorithm from scratch.
2. Known ordering property on a constructed 200-value array (5 genuinely
   small p-values ~1e-6, 195 uniform-random nulls): Bonferroni (fixed,
   no rank chain) must reject a SUBSET of what step-up BH rejects, and BY
   (safe under arbitrary dependence) must reject a SUBSET of what plain BH
   rejects. This is the exact property the real comparison is being run to
   exploit (whether a non-rank-chain-dependent method recovers pairs BH's
   chain drops) -- verifying the subset relationship holds is what makes
   trusting the real-data run's "method X recovers pair Y" claim honest.
"""
import os
import sys

import numpy as np
from statsmodels.stats.multitest import multipletests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from research.fdr_method_comparison import apply_all_methods

ALPHA = 0.05

# --- Check 1: textbook 15-value example (same one used earlier this session
# to verify _benjamini_hochberg and benjamini_yekutieli individually) ---
p15 = np.array([
    0.0001, 0.0004, 0.0019, 0.0095, 0.0201, 0.0278, 0.0298, 0.0344,
    0.0459, 0.3240, 0.4262, 0.5719, 0.6528, 0.7590, 1.0000,
])

rej = apply_all_methods(p15, ALPHA)

ref_bh, _, _, _ = multipletests(p15, alpha=ALPHA, method="fdr_bh")
ref_by, _, _, _ = multipletests(p15, alpha=ALPHA, method="fdr_by")
ref_tsbh, _, _, _ = multipletests(p15, alpha=ALPHA, method="fdr_tsbh")
ref_bonf, _, _, _ = multipletests(p15, alpha=ALPHA, method="bonferroni")

check1 = (
    np.array_equal(rej["step_up_bh"], ref_bh)
    and np.array_equal(rej["benjamini_yekutieli"], ref_by)
    and np.array_equal(rej["two_stage_tsbh"], ref_tsbh)
    and np.array_equal(rej["fixed_bonferroni"], ref_bonf)
)
print(f"Check 1 (textbook 15-value, all 4 methods vs statsmodels reference): "
      f"{'PASS' if check1 else 'FAIL'}")
if not check1:
    for name, r, ref in [
        ("step_up_bh", rej["step_up_bh"], ref_bh),
        ("benjamini_yekutieli", rej["benjamini_yekutieli"], ref_by),
        ("two_stage_tsbh", rej["two_stage_tsbh"], ref_tsbh),
        ("fixed_bonferroni", rej["fixed_bonferroni"], ref_bonf),
    ]:
        if not np.array_equal(r, ref):
            print(f"  MISMATCH {name}: got {r}, expected {ref}")

# --- Check 2: subset-relationship property on a larger constructed array ---
rng_seed_array = np.concatenate([
    np.array([1e-8, 5e-7, 2e-6, 8e-6, 3e-5]),  # 5 genuinely small p-values
    np.linspace(0.05, 0.999, 195),              # 195 "null-like" spread-out p-values
])

rej2 = apply_all_methods(rng_seed_array, ALPHA)
bh_set = set(np.where(rej2["step_up_bh"])[0])
by_set = set(np.where(rej2["benjamini_yekutieli"])[0])
bonf_set = set(np.where(rej2["fixed_bonferroni"])[0])

check2a = by_set.issubset(bh_set)
check2b = bonf_set.issubset(bh_set)
print(f"Check 2a (BY rejections subset-of BH rejections): "
      f"{'PASS' if check2a else 'FAIL'}  (BH={len(bh_set)}, BY={len(by_set)})")
print(f"Check 2b (Bonferroni rejections subset-of BH rejections): "
      f"{'PASS' if check2b else 'FAIL'}  (BH={len(bh_set)}, Bonferroni={len(bonf_set)})")

ok = check1 and check2a and check2b
print("\nPASS" if ok else "\nFAIL")
sys.exit(0 if ok else 1)
