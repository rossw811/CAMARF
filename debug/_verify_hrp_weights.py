"""
Synthetic verification of the HRP building blocks in backtest.py
(_hrp_ivp, _hrp_quasi_diag, _hrp_recursive_bisection) BEFORE trusting
compute_hrp_weights() on real trade data.

Checks:
  1. _hrp_quasi_diag returns a valid permutation of 0..n-1 (same set, no
     duplicates/omissions) for a real linkage tree.
  2. _hrp_recursive_bisection's raw weights sum to 1.0 (a genuine portfolio
     allocation, before compute_hrp_weights' *n_pairs multiplier conversion).
  3. Equal-variance, zero-correlation case (identity covariance) -> HRP
     should allocate equally (1/N each) — no information to differentiate
     the assets, so equal-weight is the only defensible answer.
  4. Two clearly different-variance, zero-correlation assets -> HRP
     (which reduces to plain inverse-variance for exactly 2 leaves) should
     allocate MORE weight to the lower-variance asset, and the ratio should
     match the closed-form inverse-variance portfolio exactly.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from scipy.cluster.hierarchy import linkage
from scipy.spatial.distance import squareform

from backtest import _hrp_ivp, _hrp_quasi_diag, _hrp_recursive_bisection


def _run_hrp(cov: np.ndarray) -> np.ndarray:
    n = cov.shape[0]
    corr = cov / np.sqrt(np.outer(np.diag(cov), np.diag(cov)))
    dist = np.sqrt(np.clip(0.5 * (1 - corr), 0, None))
    np.fill_diagonal(dist, 0.0)
    condensed = squareform(dist, checks=False)
    link = linkage(condensed, method="single")
    sort_ix = _hrp_quasi_diag(link)
    w = _hrp_recursive_bisection(cov, sort_ix)
    return w.sort_index().values, sort_ix


def main():
    failures = []
    rng = np.random.default_rng(3)

    # --- 1 & 2: general random case ---
    n = 8
    A = rng.normal(size=(n, n))
    cov = A @ A.T + np.eye(n) * 0.1  # guaranteed positive-definite
    weights, sort_ix = _run_hrp(cov)
    if sorted(sort_ix) != list(range(n)):
        failures.append(f"_hrp_quasi_diag not a valid permutation: {sorted(sort_ix)}")
    if not np.isclose(weights.sum(), 1.0, atol=1e-8):
        failures.append(f"HRP weights should sum to 1.0, got {weights.sum()}")
    if np.any(weights < 0):
        failures.append(f"HRP weights should be non-negative: {weights}")

    # --- 3: equal-variance, zero-correlation -> equal weights ---
    cov_equal = np.eye(4) * 2.5
    weights_equal, _ = _run_hrp(cov_equal)
    if not np.allclose(weights_equal, 0.25, atol=1e-6):
        failures.append(f"Equal-variance/zero-correlation should give equal weights: {weights_equal}")

    # --- 4: two assets, different variance, zero correlation -> matches IVP exactly ---
    var_a, var_b = 1.0, 4.0
    cov_2 = np.array([[var_a, 0.0], [0.0, var_b]])
    weights_2, _ = _run_hrp(cov_2)
    expected_ivp = _hrp_ivp(cov_2)
    if not np.allclose(weights_2, expected_ivp, atol=1e-8):
        failures.append(
            f"2-asset HRP should match closed-form IVP exactly: {weights_2} vs {expected_ivp}"
        )
    if not weights_2[0] > weights_2[1]:
        failures.append(
            f"Lower-variance asset (var={var_a}) should get more weight than "
            f"higher-variance asset (var={var_b}): {weights_2}"
        )

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All HRP building-block checks passed.")
    print(f"  random 8-asset weights sum: {weights.sum():.10f}")
    print(f"  equal-variance case: {weights_equal}")
    print(f"  2-asset IVP match: {weights_2} == {expected_ivp}")


if __name__ == "__main__":
    main()
