"""
Synthetic verification for research/wavelet_hurst_comparison.py's
wavelet_hurst() (task #43, 2026-07-14). Confirms it recovers the expected
DIRECTION of H for two unambiguous synthetic cases before trusting it on
real spread data — matching this project's verify-before-trusting
discipline (analysis.py's own hurst_rs/hurst_dfa are checked the same way
elsewhere in Development.md).
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from wavelet_hurst_comparison import wavelet_hurst


def test_white_noise_gives_h_near_half():
    # Levels are white noise -> increments are white noise minus white
    # noise (still uncorrelated) -> H should land near 0.5 (random walk
    # increments), same expectation analysis.py's own estimators use.
    rng = np.random.default_rng(0)
    levels = np.cumsum(rng.normal(0, 1, 5000))  # random walk spread
    h = wavelet_hurst(levels)
    print(f"random-walk spread: H_wavelet={h:.3f} (expect near 0.5)")
    assert 0.35 < h < 0.65, f"expected H near 0.5 for a random walk, got {h}"


def test_strongly_mean_reverting_gives_low_h():
    # Strongly mean-reverting AR(1) spread (low phi) -> increments have
    # strong negative lag-1 autocorrelation -> H should be well below 0.5,
    # same relationship analysis.py's docstring derives for hurst_rs/hurst_dfa.
    rng = np.random.default_rng(1)
    n = 5000
    phi = 0.3  # strong mean reversion
    levels = np.zeros(n)
    for t in range(1, n):
        levels[t] = phi * levels[t - 1] + rng.normal(0, 1)
    h = wavelet_hurst(levels)
    print(f"strongly mean-reverting AR(1) (phi=0.3) spread: H_wavelet={h:.3f} (expect well below 0.5)")
    assert h < 0.42, f"expected H well below 0.5 for strong mean reversion, got {h}"


def test_ordering_consistent_with_persistence():
    # A near-random-walk (phi close to 1) spread should have HIGHER
    # wavelet-H than a strongly mean-reverting one — checks the estimator
    # responds in the right DIRECTION as persistence increases, not just
    # that any one case lands in a plausible range.
    rng = np.random.default_rng(2)
    n = 5000

    def ar1_spread(phi, seed):
        r = np.random.default_rng(seed)
        s = np.zeros(n)
        for t in range(1, n):
            s[t] = phi * s[t - 1] + r.normal(0, 1)
        return s

    h_low_phi = wavelet_hurst(ar1_spread(0.2, 10))
    h_high_phi = wavelet_hurst(ar1_spread(0.9, 11))
    print(f"phi=0.2: H_wavelet={h_low_phi:.3f}; phi=0.9: H_wavelet={h_high_phi:.3f}")
    assert h_high_phi > h_low_phi, (
        f"expected H to increase with persistence (phi 0.2->0.9), "
        f"got {h_low_phi:.3f} -> {h_high_phi:.3f}"
    )


if __name__ == "__main__":
    test_white_noise_gives_h_near_half()
    test_strongly_mean_reverting_gives_low_h()
    test_ordering_consistent_with_persistence()
    print("\nAll cases passed.")
