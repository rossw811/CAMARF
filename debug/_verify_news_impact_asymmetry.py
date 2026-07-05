"""
Synthetic verification for research/news_impact_asymmetry.py's permutation-
based two-group variance comparison.

Case 1: symmetric volatility (real GARCH(1,1), no directional asymmetry)
— rejection rate across repeated trials should track the nominal 5%,
not be systematically inflated.

Case 2: genuine asymmetry injected (variance after narrowing deliberately
3x variance after widening) — the test should reject clearly on a single
well-powered trial, with the ratio and direction correctly identified.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from research.news_impact_asymmetry import news_impact_asymmetry_test

failures = []

# --- Case 1: symmetric GARCH(1,1), repeated trials ---
N_TRIALS = 20
n_rejected = 0
for trial in range(N_TRIALS):
    rng = np.random.default_rng(1000 + trial)
    n = 1000
    z = np.zeros(n)
    vol2 = 1.0
    prev_dz = 0.0
    for t in range(1, n):
        vol2 = 0.9 * vol2 + 0.1 * prev_dz ** 2
        dz_t = rng.normal(scale=np.sqrt(max(vol2, 1e-6)))
        z[t] = z[t - 1] + dz_t
        prev_dz = dz_t
    r = news_impact_asymmetry_test(z, n_perm=300, rng=np.random.default_rng(2000 + trial))
    if not r["ok"]:
        failures.append(f"Case 1 trial {trial}: test failed to run ({r.get('error')})")
        continue
    if r["pvalue"] < 0.05:
        n_rejected += 1
rejection_rate = n_rejected / N_TRIALS
print(f"Case 1 (symmetric GARCH(1,1)): rejected {n_rejected}/{N_TRIALS} trials "
      f"(rate={rejection_rate:.2f}, nominal=0.05)")
if rejection_rate > 0.25:
    failures.append(f"Case 1: rejection rate {rejection_rate:.2f} too high for a symmetric process")

# --- Case 2: genuine asymmetry, single well-powered trial ---
rng2 = np.random.default_rng(42)
n2 = 3000
z2 = np.zeros(n2)
TRUE_STD_RATIO = 3.0     # narrow-group STD is 3x the widen-group STD...
TRUE_VAR_RATIO = TRUE_STD_RATIO ** 2  # ...so the true VARIANCE ratio is 9x
for t in range(1, n2):
    prev_dz = z2[t - 1] - (z2[t - 2] if t > 1 else 0.0)
    vol = TRUE_STD_RATIO if prev_dz < 0 else 1.0  # 3x higher STD after narrowing
    z2[t] = z2[t - 1] + rng2.normal(scale=vol)
r2 = news_impact_asymmetry_test(z2, n_perm=1000, rng=np.random.default_rng(43))
print(f"Case 2 (genuine asymmetry, narrowing->{TRUE_STD_RATIO}x std / {TRUE_VAR_RATIO}x variance): "
      f"var_ratio(narrow/widen)={r2['variance_ratio_narrow_over_widen']:.3f}, "
      f"narrow_higher_vol={r2['narrow_higher_vol']}, p={r2['pvalue']:.4f}")
if not r2["ok"]:
    failures.append("Case 2: test failed to run")
else:
    if r2["pvalue"] >= 0.05:
        failures.append(f"Case 2: failed to reject symmetric null on strongly asymmetric data (p={r2['pvalue']})")
    if not r2["narrow_higher_vol"]:
        failures.append(f"Case 2: expected narrow_higher_vol=True (narrowing deliberately set to {TRUE_VAR_RATIO}x variance)")
    if not (TRUE_VAR_RATIO * 0.6 < r2["variance_ratio_narrow_over_widen"] < TRUE_VAR_RATIO * 1.4):
        failures.append(f"Case 2: expected variance ratio near the true {TRUE_VAR_RATIO}x, "
                        f"got {r2['variance_ratio_narrow_over_widen']:.3f}")

print()
if failures:
    print(f"FAILED ({len(failures)} issue(s)):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("ALL CHECKS PASSED")
    sys.exit(0)
