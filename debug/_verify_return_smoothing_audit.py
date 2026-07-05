"""
Synthetic verification for research/return_smoothing_audit.py.

Case 1: no smoothing (true theta=[1,0,0]) — sample returns are iid, so the
estimated smoothing index should come out close to 1.0.

Case 2: genuine smoothing injected — construct an OBSERVED return series
as a KNOWN MA(2) combination of an underlying iid "true return" series
(th0=0.5, th1=0.3, th2=0.2 — a real smoothing profile), and confirm the
estimated theta/index recovers something close to the true values, with
smoothing_index clearly below 1.0 and below Case 1's result.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from research.return_smoothing_audit import estimate_smoothing

failures = []

# --- Case 1: no smoothing ---
rng1 = np.random.default_rng(5)
returns_iid = rng1.normal(size=2000)
r1 = estimate_smoothing(returns_iid)
print(f"Case 1 (no smoothing): theta=({r1['theta0']:.2f},{r1['theta1']:.2f},{r1['theta2']:.2f}) "
      f"smoothing_index={r1['smoothing_index']:.3f}")
if not r1["ok"]:
    failures.append("Case 1: estimation failed to run")
elif r1["smoothing_index"] < 0.85:
    failures.append(f"Case 1: expected smoothing_index near 1.0 for iid data, got {r1['smoothing_index']:.3f}")

# --- Case 2: genuine smoothing, known true theta ---
rng2 = np.random.default_rng(6)
TRUE_THETA = (0.5, 0.3, 0.2)
n = 3000
true_returns = rng2.normal(size=n + 2)
observed = np.array([
    TRUE_THETA[0] * true_returns[t] + TRUE_THETA[1] * true_returns[t - 1] + TRUE_THETA[2] * true_returns[t - 2]
    for t in range(2, n + 2)
])
r2 = estimate_smoothing(observed)
print(f"Case 2 (true theta={TRUE_THETA}): estimated theta=({r2['theta0']:.2f},{r2['theta1']:.2f},{r2['theta2']:.2f}) "
      f"smoothing_index={r2['smoothing_index']:.3f} (true index={sum(t**2 for t in TRUE_THETA):.3f})")
if not r2["ok"]:
    failures.append("Case 2: estimation failed to run")
else:
    true_xi = sum(t ** 2 for t in TRUE_THETA)
    if r2["smoothing_index"] >= r1["smoothing_index"]:
        failures.append(
            f"Case 2: smoothed series' index ({r2['smoothing_index']:.3f}) should be clearly "
            f"BELOW the no-smoothing case's index ({r1['smoothing_index']:.3f})"
        )
    if abs(r2["smoothing_index"] - true_xi) > 0.15:
        failures.append(f"Case 2: estimated index ({r2['smoothing_index']:.3f}) too far from "
                        f"the true index ({true_xi:.3f})")

print()
if failures:
    print(f"FAILED ({len(failures)} issue(s)):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("ALL CHECKS PASSED")
    sys.exit(0)
