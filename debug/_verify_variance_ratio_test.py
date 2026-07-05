"""
Synthetic verification for research/variance_ratio_test.py before trusting
it on real confirmed-pair spreads.

Case 1: pure random walk (iid increments) — VR(q) should be close to 1.0
for every q, and the robust test should reject at close to its nominal 5%
rate across repeated trials, not systematically.

Case 2: a genuinely mean-reverting AR(1) series (known negative
autocorrelation in increments) — VR(q) should be clearly below 1 and the
robust test should reject on a single well-powered trial.

Case 3: a trending/momentum series (positive-autocorrelation increments)
— VR(q) should be clearly ABOVE 1, the opposite direction from Case 2,
confirming the test distinguishes the two rather than just "always
rejects."
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from research.variance_ratio_test import variance_ratio

failures = []

# --- Case 1: pure random walk, repeated trials ---
N_TRIALS = 20
n_rejected = 0
vr_values = []
for trial in range(N_TRIALS):
    rng = np.random.default_rng(1000 + trial)
    increments = rng.normal(scale=1.0, size=2000)
    series = np.concatenate([[0.0], np.cumsum(increments)])
    r = variance_ratio(series, q=4)
    if not r["ok"]:
        failures.append(f"Case 1 trial {trial}: test failed to run ({r.get('error')})")
        continue
    vr_values.append(r["vr"])
    if r["p2"] is not None and r["p2"] < 0.05:
        n_rejected += 1

mean_vr = np.mean(vr_values)
print(f"Case 1 (random walk): mean VR(4) across {N_TRIALS} trials = {mean_vr:.3f} "
      f"(expected ~1.0), rejected {n_rejected}/{N_TRIALS} at p<0.05 (nominal 0.05)")
if abs(mean_vr - 1.0) > 0.1:
    failures.append(f"Case 1: mean VR={mean_vr:.3f} too far from 1.0 for a true random walk")
if n_rejected / N_TRIALS > 0.30:
    failures.append(f"Case 1: rejection rate {n_rejected/N_TRIALS:.2f} too high for a true random walk")

# --- Case 2: genuinely mean-reverting AR(1) ---
rng2 = np.random.default_rng(42)
n2 = 3000
z = np.zeros(n2)
for t in range(1, n2):
    z[t] = z[t - 1] - 0.3 * z[t - 1] + rng2.normal(scale=1.0)
r2 = variance_ratio(z, q=4)
print(f"Case 2 (mean-reverting AR(1), alpha=-0.3): VR(4)={r2['vr']:.3f} "
      f"z2_robust={r2['z2']:.2f} p={r2['p2']:.4f}")
if not r2["ok"]:
    failures.append("Case 2: test failed to run")
else:
    if r2["vr"] >= 1.0:
        failures.append(f"Case 2: VR={r2['vr']:.3f} should be < 1.0 for mean-reverting data")
    if r2["p2"] is None or r2["p2"] >= 0.05:
        failures.append(f"Case 2: failed to reject random-walk null on strongly mean-reverting data (p={r2['p2']})")

# --- Case 3: trending/momentum series (positive autocorrelation) ---
rng3 = np.random.default_rng(43)
n3 = 3000
trend_incr = np.zeros(n3)
prev = 0.0
for t in range(n3):
    prev = 0.3 * prev + rng3.normal(scale=1.0)  # positively autocorrelated increments
    trend_incr[t] = prev
series3 = np.concatenate([[0.0], np.cumsum(trend_incr)])
r3 = variance_ratio(series3, q=4)
print(f"Case 3 (trending, positive-autocorr increments): VR(4)={r3['vr']:.3f} "
      f"z2_robust={r3['z2']:.2f} p={r3['p2']:.4f}")
if not r3["ok"]:
    failures.append("Case 3: test failed to run")
else:
    if r3["vr"] <= 1.0:
        failures.append(f"Case 3: VR={r3['vr']:.3f} should be > 1.0 for trending/positively-autocorrelated data")
    if r3["p2"] is None or r3["p2"] >= 0.05:
        failures.append(f"Case 3: failed to reject random-walk null on strongly trending data (p={r3['p2']})")

print()
if failures:
    print(f"FAILED ({len(failures)} issue(s)):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("ALL CHECKS PASSED")
    sys.exit(0)
