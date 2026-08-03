"""
Synthetic verification for research/levy_jump_diffusion.py's Lee & Mykland
(2008) jump test, before trusting it on real pair data.

Checks:
  1. Pure diffusion (no injected jumps): false-positive rate should land
     near the test's nominal alpha, not wildly off.
  2. Jump-diffusion with large injected jumps: the test should recover
     MOST of the injected jump locations (recall check, not just a count).
  3. continuous_vol should be LOWER than total_vol once real jumps are
     excluded, on the jump-diffusion series specifically.
  4. lee_mykland_critical_value increases with n (higher bar for more
     multiple-testing) and decreases as alpha increases (less strict) --
     sanity checks on the formula itself, not just the end-to-end test.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from levy_jump_diffusion import lee_mykland_jump_test, lee_mykland_critical_value, continuous_vs_total_vol


def test_critical_value_sanity():
    cv_n_small = lee_mykland_critical_value(500, alpha=0.01)
    cv_n_large = lee_mykland_critical_value(50000, alpha=0.01)
    print(f"critical value: n=500 -> {cv_n_small:.3f}, n=50000 -> {cv_n_large:.3f} (expect n=50000 higher)")
    assert cv_n_large > cv_n_small, "critical value should increase with n (multiple-testing correction)"

    cv_strict = lee_mykland_critical_value(5000, alpha=0.001)
    cv_loose = lee_mykland_critical_value(5000, alpha=0.05)
    print(f"critical value: alpha=0.001 -> {cv_strict:.3f}, alpha=0.05 -> {cv_loose:.3f} (expect stricter alpha higher)")
    assert cv_strict > cv_loose, "smaller alpha (stricter test) should give a higher critical value"


def test_false_positive_rate_near_nominal_on_pure_diffusion():
    rng = np.random.default_rng(0)
    n = 5000
    r = rng.normal(0, 0.01, n)  # pure diffusion, no jumps at all
    result = lee_mykland_jump_test(r, alpha=0.01)
    print(f"pure diffusion: {result['n_jumps']} flagged jumps out of {n} bars "
          f"({result['jump_frac']*100:.3f}%, nominal alpha=1%)")
    # Not an exact match (finite-sample, bipower-variation estimation noise),
    # but should be in the right ballpark -- not flagging a huge fraction as
    # jumps when there are none.
    assert result["jump_frac"] < 0.05, f"false-positive rate too high for pure diffusion: {result['jump_frac']}"


def test_recovers_injected_jumps():
    rng = np.random.default_rng(1)
    n = 3000
    r = rng.normal(0, 0.01, n)
    jump_locs = [500, 1000, 1500, 2000, 2500]
    for loc in jump_locs:
        r[loc] += 0.5  # huge jump relative to the 0.01 diffusion scale

    result = lee_mykland_jump_test(r, alpha=0.01)
    recovered = set(np.where(result["is_jump"])[0])
    hits = sum(1 for loc in jump_locs if loc in recovered)
    print(f"injected {len(jump_locs)} large jumps at {jump_locs}, recovered {hits}/{len(jump_locs)}, "
          f"total flagged={result['n_jumps']}")
    assert hits >= 4, f"expected to recover at least 4/5 large injected jumps, got {hits}"


def test_continuous_vol_lower_than_total_on_jumpy_series():
    rng = np.random.default_rng(2)
    n = 3000
    r = rng.normal(0, 0.01, n)
    for loc in [400, 900, 1400, 1900, 2400]:
        r[loc] += rng.choice([-1, 1]) * 0.6

    result = lee_mykland_jump_test(r, alpha=0.01)
    vol = continuous_vs_total_vol(r, result["is_jump"])
    print(f"total_vol={vol['total_vol']:.5f}  continuous_vol={vol['continuous_vol']:.5f}  "
          f"({vol['pct_change']:+.2f}%)")
    assert vol["continuous_vol"] < vol["total_vol"], (
        "excluding detected jumps should lower realized vol on a series with real large jumps"
    )


if __name__ == "__main__":
    test_critical_value_sanity()
    test_false_positive_rate_near_nominal_on_pure_diffusion()
    test_recovers_injected_jumps()
    test_continuous_vol_lower_than_total_on_jumpy_series()
    print("\nAll levy_jump_diffusion.py synthetic checks passed.")
