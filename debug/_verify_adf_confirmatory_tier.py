"""
Synthetic verification for research/adf_confirmatory_tier.py's standalone ADF test,
before trusting it on real confirmed-pair spread data.

ADF null hypothesis: unit root present (series is NON-stationary). Rejecting the null
(p < threshold) means the series IS stationary. This is the SAME direction as PO/PP
(also a unit-root test) and the OPPOSITE direction from KPSS (whose null is "stationary" --
failing to reject KPSS is what supports stationarity there). Getting this backwards is
the single most common way to misuse ADF, so this is checked explicitly, not assumed.

Two cases:
  1. Known-stationary series (AR(1) with |phi|<1, mean-reverting by construction) -- ADF
     should REJECT the unit-root null (low p-value), i.e. adf_confirms=True.
  2. Known-unit-root series (pure random walk, cumulative sum of iid noise) -- ADF should
     FAIL to reject (high p-value), i.e. adf_confirms=False.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from adf_confirmatory_tier import run_adf_test  # noqa: E402


def main():
    rng = np.random.default_rng(42)
    failures = []

    # Case 1: known-stationary AR(1), phi=0.5, n=1000. Should reject unit-root null.
    n = 1000
    phi = 0.5
    eps = rng.normal(0, 1, n)
    stationary = np.zeros(n)
    for t in range(1, n):
        stationary[t] = phi * stationary[t - 1] + eps[t]
    r1 = run_adf_test(stationary)
    print(f"Case 1 (stationary AR(1), phi={phi}): adf_pval={r1['adf_pval']:.4f} "
          f"adf_confirms={r1['adf_confirms']} (expect True, low p-value)")
    if not r1["adf_confirms"]:
        failures.append("case1: stationary series not confirmed by ADF")

    # Case 2: known unit-root, pure random walk. Should fail to reject.
    walk = np.cumsum(rng.normal(0, 1, n))
    r2 = run_adf_test(walk)
    print(f"Case 2 (random walk / unit root): adf_pval={r2['adf_pval']:.4f} "
          f"adf_confirms={r2['adf_confirms']} (expect False, high p-value)")
    if r2["adf_confirms"]:
        failures.append("case2: unit-root series incorrectly confirmed by ADF")

    # Case 3: null-direction sanity -- confirm the convention matches PO's convention
    # (both reject unit-root null to confirm), not KPSS's (opposite direction).
    # A strongly stationary series should give ADF p << 0.10 (matches PO's threshold
    # in stats.py's _run_coint_tests), not p > 0.90 (which would indicate the
    # direction got flipped to match KPSS's convention by mistake).
    very_stationary = rng.normal(0, 1, n)  # white noise, phi=0, maximally stationary
    r3 = run_adf_test(very_stationary)
    print(f"Case 3 (white noise, direction sanity check): adf_pval={r3['adf_pval']:.6f} "
          f"(expect << 0.10, confirming reject-null-means-stationary convention)")
    if r3["adf_pval"] > 0.10:
        failures.append("case3: ADF p-value direction looks flipped (should be << 0.10 for white noise)")

    if failures:
        print(f"\nFAILED: {failures}")
        sys.exit(1)
    print("\nAll cases match expected behavior. ADF null-hypothesis direction confirmed correct.")


if __name__ == "__main__":
    main()
