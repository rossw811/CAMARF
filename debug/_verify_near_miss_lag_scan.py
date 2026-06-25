"""
Synthetic verification for near_miss_lag_scan.py's find_lagged_near_misses
(2026-06-24).

Constructs a small, known returns matrix (4 symbols) with three
deliberately distinct cases, and confirms the near-miss filter +
lag-scan routes each one correctly:
  - Pair (0,1): near-miss at lag 0 (corr~0.3, contemporaneous loading
    a=0.3) but a real, strong relationship at a planted lag (loading
    b=0.6 on the k_true-lagged factor) — should be found AND flagged.
  - Pair (0,2): near-miss at lag 0 (corr~0.3, same a=0.3 contemporaneous
    loading) with NO lagged component at all — should be found in the
    near-miss band but NOT flagged (no real lift at any other lag,
    since the underlying factor is white noise with no autocorrelation
    to exploit).
  - Pair (0,3): already clears the near-miss band's upper bound at lag 0
    (corr~0.6) — should never even enter the near-miss set.

Uses analysis.py's own UniverseFilter.correlation_matrix for corr0, the
same production kernel near_miss_lag_scan.py itself uses — this test
exercises the real integration, not a hand-rolled correlation.

Run: python debug/_verify_near_miss_lag_scan.py
"""
import os
import sys

import numpy as np

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "research"))

from analysis import UniverseFilter
from near_miss_lag_scan import find_lagged_near_misses

SEED = 99
N = 4000
K_TRUE = 5


def build_synthetic_returns():
    rng = np.random.default_rng(SEED)
    factor = rng.normal(0.0, 1.0, size=N + K_TRUE)  # extra buffer for the lag

    def idio():
        return rng.normal(0.0, 1.0, size=N)

    ret_0 = factor[K_TRUE:K_TRUE + N]  # symbol 0 IS the factor, lag-aligned to the visible window

    # Pair (0,1): contemporaneous loading a=0.3 (near-miss) + lagged
    # loading b=0.6 on factor[t - k_true] (real, stronger relationship).
    a, b = 0.3, 0.6
    # factor index for visible t in [0,N) is t+K_TRUE; "t-K_TRUE" maps to factor index t.
    contemporaneous = factor[K_TRUE:K_TRUE + N]
    lagged = factor[0:N]
    ret_1 = a * contemporaneous + b * lagged + np.sqrt(max(1 - a ** 2 - b ** 2, 0.0)) * idio()

    # Pair (0,2): contemporaneous loading a=0.3 only, no lag structure.
    ret_2 = a * contemporaneous + np.sqrt(1 - a ** 2) * idio()

    # Pair (0,3): contemporaneous loading a2=0.6 — already clears the
    # near-miss band's upper bound, should never enter the near-miss set.
    a2 = 0.6
    ret_3 = a2 * contemporaneous + np.sqrt(1 - a2 ** 2) * idio()

    returns = np.stack([ret_0, ret_1, ret_2, ret_3])
    syms = ["S0", "S1", "S2", "S3"]
    return returns, syms


def main():
    returns, syms = build_synthetic_returns()
    corr0 = UniverseFilter.correlation_matrix(returns)

    print("Lag-0 correlation matrix:")
    print(corr0)

    c01 = corr0[0, 1]
    c02 = corr0[0, 2]
    c03 = corr0[0, 3]
    print(f"\ncorr(S0,S1)={c01:.3f} (expect ~0.3, near-miss)")
    print(f"corr(S0,S2)={c02:.3f} (expect ~0.3, near-miss)")
    print(f"corr(S0,S3)={c03:.3f} (expect ~0.6, already above 0.40 — excluded from near-miss set)")
    assert 0.20 <= abs(c01) < 0.40, f"FAILED: corr(S0,S1) not in expected near-miss range: {c01}"
    assert 0.20 <= abs(c02) < 0.40, f"FAILED: corr(S0,S2) not in expected near-miss range: {c02}"
    assert abs(c03) >= 0.40, f"FAILED: corr(S0,S3) unexpectedly in near-miss range: {c03}"

    result = find_lagged_near_misses(
        returns, syms, corr0, near_miss_low=0.25, near_miss_high=0.40, max_lag=10, min_lift=0.10
    )
    print(f"\nNear-miss pairs found: {len(result)}")
    print(result.to_string(index=False))

    pairs_found = set(zip(result["symbol_a"], result["symbol_b"]))
    assert ("S0", "S1") in pairs_found, "FAILED: (S0,S1) should be in the near-miss set"
    assert ("S0", "S2") in pairs_found, "FAILED: (S0,S2) should be in the near-miss set"
    assert ("S0", "S3") not in pairs_found, "FAILED: (S0,S3) should NOT be in the near-miss set (already above threshold)"
    print("PASS: near-miss band filter correctly includes (S0,S1)/(S0,S2), excludes (S0,S3).")

    row_01 = result[(result["symbol_a"] == "S0") & (result["symbol_b"] == "S1")].iloc[0]
    row_02 = result[(result["symbol_a"] == "S0") & (result["symbol_b"] == "S2")].iloc[0]

    print(f"\n(S0,S1): best_lag={row_01['best_lag']} lift={row_01['lift']:.3f} flagged={row_01['flagged']}")
    print(f"(S0,S2): best_lag={row_02['best_lag']} lift={row_02['lift']:.3f} flagged={row_02['flagged']}")

    assert row_01["flagged"], (
        f"FAILED: (S0,S1) has a real planted lag relationship and should be flagged "
        f"(lift={row_01['lift']})"
    )
    assert row_01["best_lag"] == -K_TRUE or row_01["best_lag"] == K_TRUE, (
        f"FAILED: (S0,S1) best_lag={row_01['best_lag']} doesn't match planted lag {K_TRUE} "
        f"(check sign convention)"
    )
    print("PASS: (S0,S1)'s planted lag relationship is correctly flagged.")

    assert not row_02["flagged"], (
        f"FAILED: (S0,S2) has no real lag structure and should NOT be flagged "
        f"(lift={row_02['lift']})"
    )
    print("PASS: (S0,S2)'s lack of real lag structure is correctly NOT flagged.")

    print("\nALL CHECKS PASSED.")


if __name__ == "__main__":
    main()
