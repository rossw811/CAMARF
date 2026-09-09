"""
debug/_verify_decoupling_meta_analysis.py -- synthetic checks for
research/decoupling_meta_analysis.py, BEFORE trusting it against the real (n=4-5) decoupling
chain output.

Run: python debug/_verify_decoupling_meta_analysis.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.decoupling_meta_analysis import fisher_combined_pvalue, combine_total_pnl

passed = 0
failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}")
        failed += 1


print("Check 1: fisher_combined_pvalue -- matches a hand-computed chi2 statistic for a simple case")
pvals = [0.05, 0.05, 0.05, 0.05]
result = fisher_combined_pvalue(pvals)
expected_chi2 = -2 * sum(np.log(p) for p in pvals)
check(f"chi2 statistic matches hand computation ({result['chi2_stat']:.4f} vs {expected_chi2:.4f})",
      abs(result["chi2_stat"] - expected_chi2) < 1e-9)
check("k (number of tests combined) is 4", result["k"] == 4)

print("Check 2: fisher_combined_pvalue -- combining several individually-marginal p-values "
      "(each just barely below 0.05) produces a MUCH smaller combined p-value than any individual "
      "one -- the whole point of the meta-analytic combination")
marginal_pvals = [0.04, 0.045, 0.048, 0.042]
result2 = fisher_combined_pvalue(marginal_pvals)
check(f"combined p-value ({result2['combined_pvalue']:.2e}) is smaller than the largest "
      f"individual p-value (0.048)", result2["combined_pvalue"] < 0.01)

print("Check 3: fisher_combined_pvalue -- ignores non-finite/out-of-range p-values rather than "
      "crashing or silently corrupting the combination")
result3 = fisher_combined_pvalue([0.05, np.nan, 0.05, -1.0, 1.5])
check("only the 2 genuinely valid p-values are combined (k=2)", result3["k"] == 2)

print("Check 4: fisher_combined_pvalue -- empty input returns None, not a crash or fabricated value")
result4 = fisher_combined_pvalue([])
check("empty list -> combined_pvalue is None", result4["combined_pvalue"] is None)

print("Check 5: combine_total_pnl -- detects a KNOWN, clearly nonzero mean P&L with the correct "
      "sign and a small n_positive count for a mostly-negative synthetic sample")
pnls = [-300.0, -50.0, -80.0, 100.0]  # 1 of 4 positive, mean is negative (-330/4 = -82.5)
r5 = combine_total_pnl(pnls)
check(f"mean_pnl ({r5['mean_pnl']:.2f}) is negative, matching the synthetic sample", r5["mean_pnl"] < 0)
check("n_positive correctly counted as 1 of 4", r5["n_positive"] == 1 and r5["n"] == 4)
check("sign-test p-value is a real float in [0,1]", 0 <= r5["sign_pvalue"] <= 1)

print("Check 6: combine_total_pnl -- a sample with an obvious, large, uniformly positive edge "
      "is correctly flagged as significant by the sign test")
pnls_all_positive = [500.0, 600.0, 550.0, 700.0, 620.0, 480.0]
r6 = combine_total_pnl(pnls_all_positive)
check(f"sign-test p-value ({r6['sign_pvalue']:.4f}) correctly flags 6/6 positive as significant",
      r6["sign_pvalue"] < 0.05)

print("Check 7: combine_total_pnl -- fewer than 2 valid values returns None stats rather than a "
      "fabricated t-statistic from an undefined sample")
r7 = combine_total_pnl([42.0])
check("n=1 -> t_stat is None (can't estimate variance from one point)", r7["t_stat"] is None)

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
