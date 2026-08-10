"""
Synthetic verification for research/trig_convergence.py (2026-08-03), before
trusting it on real pair data -- matching this project's verify-before-
trusting discipline.

Checks:
  1. to_angle(): arccos maps [-1,1] -> [0,pi], arcsin maps [-1,1] ->
     [-pi/2,pi/2], both exactly at the domain endpoints (p=+1,-1,0).
  2. A true "polar opposite" polarity pair (p_A = -p_B always) produces
     theta_A + theta_B CONSTANT (pi for arccos, 0 for arcsin) across the
     WHOLE oscillating cycle -- this is the corrected invariant (an
     earlier draft wrongly claimed theta_A - theta_B was the invariant;
     verification caught that it is NOT constant for an oscillating pair,
     only at the exact +/-1 extremes -- see module docstring's "design
     error" section for the full story).
  3. trig_decompose() is an EXACT algebraic identity, not an approximation:
     co_movement * divergence (with the right constant) must reconstruct
     the original polarity difference (p_A - p_B) to floating-point
     precision, for both mappings.
  4. opposite_equilibrium_break_signal() is CAUSAL: perturbing co_movement
     strictly AFTER time t must not change the signal value AT t.
  5. opposite_equilibrium_break_signal() actually flags a genuine break: a
     pair that holds the true polar-opposite relationship (co_movement
     pinned at its theoretical extreme) and then breaks it should show
     |z| spike at the break, not before.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from trig_convergence import to_angle, trig_decompose, opposite_equilibrium_break_signal


def test_to_angle_domain_endpoints():
    p = np.array([-1.0, 0.0, 1.0])
    arccos_theta = to_angle(p, "arccos")
    arcsin_theta = to_angle(p, "arcsin")
    print(f"arccos([-1,0,1]) = {arccos_theta} (expect [pi, pi/2, 0])")
    print(f"arcsin([-1,0,1]) = {arcsin_theta} (expect [-pi/2, 0, pi/2])")
    assert np.allclose(arccos_theta, [np.pi, np.pi / 2, 0.0])
    assert np.allclose(arcsin_theta, [-np.pi / 2, 0.0, np.pi / 2])


def test_true_opposite_pair_angle_sum_is_the_real_invariant():
    """The corrected claim: theta_A + theta_B (not theta_A - theta_B) is
    constant for a true opposite pair, across the FULL oscillating cycle,
    not just at the +/-1 extremes."""
    rng = np.random.default_rng(0)
    n = 500
    pol_a = np.tanh(np.sin(2 * np.pi * np.arange(n) / 40) + rng.normal(0, 0.05, n))
    pol_b = -pol_a  # exact polar opposite by construction, oscillates through the full range

    for mapping, expected_sum in (("arccos", np.pi), ("arcsin", 0.0)):
        theta_a = to_angle(pol_a, mapping)
        theta_b = to_angle(pol_b, mapping)
        angle_sum = theta_a + theta_b
        max_dev = np.max(np.abs(angle_sum - expected_sum))
        print(f"[{mapping}] true opposite pair: max |theta_A+theta_B - {expected_sum:.4f}| = {max_dev:.2e} (expect ~0)")
        assert max_dev < 1e-9, \
            f"[{mapping}] expected theta_A+theta_B to be exactly constant at {expected_sum} for a true opposite pair, max deviation={max_dev}"

    # And confirm the ORIGINAL wrong hypothesis (angle_diff constant) is
    # indeed false in general -- guards against silently reintroducing it.
    theta_a = to_angle(pol_a, "arccos")
    theta_b = to_angle(pol_b, "arccos")
    angle_diff = theta_a - theta_b
    diff_range = np.ptp(angle_diff)
    print(f"[arccos] angle_diff range = {diff_range:.3f} (expect LARGE, confirming it is NOT the invariant)")
    assert diff_range > 1.0, "angle_diff should swing widely for an oscillating opposite pair, not stay constant"


def test_decomposition_is_exact_identity():
    rng = np.random.default_rng(1)
    n = 300
    pol_a = np.tanh(rng.normal(0, 1, n))
    pol_b = np.tanh(rng.normal(0, 1, n))
    for mapping in ("arccos", "arcsin"):
        theta_a = to_angle(pol_a, mapping)
        theta_b = to_angle(pol_b, mapping)
        decomp = trig_decompose(theta_a, theta_b, mapping)
        true_diff = pol_a - pol_b
        max_err = np.max(np.abs(decomp["reconstructed_diff"] - true_diff))
        print(f"[{mapping}] reconstruction max abs error = {max_err:.2e} (expect ~1e-10 or smaller)")
        assert max_err < 1e-9, \
            f"[{mapping}] sum-to-product decomposition must exactly reconstruct p_A - p_B, max err={max_err}"


def test_causality_no_future_leakage():
    rng = np.random.default_rng(2)
    n = 300
    t_check = 150
    co_movement = 1.0 - rng.normal(0, 0.02, n) ** 2  # roughly pinned near 1, small noise
    sig_before = opposite_equilibrium_break_signal(co_movement.copy(), "arccos", window=60)
    perturbed = co_movement.copy()
    perturbed[t_check + 1:] -= 0.5
    sig_after = opposite_equilibrium_break_signal(perturbed, "arccos", window=60)
    assert np.isclose(sig_before[t_check], sig_after[t_check], equal_nan=True), \
        "opposite_equilibrium_break_signal leaked future information"
    print("causality check: OK -- no future leakage at t=150")


def test_arccos_arcsin_break_signal_agree_near_pinned_regime():
    """The real bug found comparing real KVUE/KMB output (2026-08-03): near
    a genuinely pinned co_movement (the true polar-opposite regime), the
    rolling std denominator's near-zero value flips sign of "is this
    exactly zero" between mappings due to co_movement's ~5e-16 rounding
    difference, producing a different NaN pattern (and thus a different
    aggregate mean) per mapping even though the underlying series is
    mathematically identical. After the _MIN_STD_FLOOR fix, both mappings'
    break signals must agree closely, bar for bar, including their NaN
    patterns, for a near-perfectly-pinned synthetic co_movement series."""
    rng = np.random.default_rng(7)
    n = 400
    # Pinned near 1.0 with only floating-point-scale noise -- the exact
    # degenerate regime that exposed the bug.
    co_movement_true = 1.0 - 1e-14 * rng.normal(0, 1, n) ** 2

    sig_a = opposite_equilibrium_break_signal(co_movement_true.copy(), "arccos", window=60)
    sig_b = opposite_equilibrium_break_signal(co_movement_true.copy() + 5e-16, "arcsin", window=60)
    # both finite everywhere (no NaN blowup from near-zero variance)
    n_finite_a, n_finite_b = np.isfinite(sig_a).sum(), np.isfinite(sig_b).sum()
    print(f"finite counts: arccos={n_finite_a}, arcsin={n_finite_b} (expect equal, both > 0)")
    assert n_finite_a == n_finite_b, \
        f"expected identical NaN patterns after the floor fix, got {n_finite_a} vs {n_finite_b}"
    max_diff = np.nanmax(np.abs(sig_a - sig_b))
    print(f"max break-signal diff between mappings (pinned regime): {max_diff:.2e} (expect small, bounded)")
    assert max_diff < 1.0, f"expected the two mappings to closely agree after the floor fix, max diff={max_diff}"


def test_break_signal_flags_a_genuine_equilibrium_collapse():
    """Construct a true opposite pair that holds for a while (co_movement
    pinned near its theoretical constant), then genuinely breaks (one leg
    stops tracking the opposite of the other) -- the break signal should
    spike AT the break, not before."""
    rng = np.random.default_rng(3)
    n = 400
    break_point = 300

    t_pre = np.arange(break_point)
    pol_a_pre = np.tanh(np.sin(2 * np.pi * t_pre / 40) + rng.normal(0, 0.03, break_point))
    # Near-perfect (not bit-exact) opposite regime -- a small independent
    # wobble on the b leg so co_movement has nonzero variance pre-break
    # (an exact -pol_a_pre makes co_movement bit-constant, dividing by a
    # zero rolling std in the z-score and producing NaN -- caught here,
    # not a flaw in the signal itself, just this test's first draft).
    pol_b_pre = -pol_a_pre + rng.normal(0, 0.01, break_point)

    t_post = np.arange(n - break_point)
    pol_a_post = np.tanh(np.sin(2 * np.pi * t_post / 40) + rng.normal(0, 0.03, n - break_point))
    pol_b_post = np.tanh(rng.normal(0, 1, n - break_point))  # relationship collapses -- independent noise

    pol_a = np.concatenate([pol_a_pre, pol_a_post])
    pol_b = np.concatenate([pol_b_pre, pol_b_post])

    theta_a = to_angle(pol_a, "arccos")
    theta_b = to_angle(pol_b, "arccos")
    decomp = trig_decompose(theta_a, theta_b, "arccos")
    sig = opposite_equilibrium_break_signal(decomp["co_movement"], "arccos", window=60)

    pre_break_abs_z = np.nanmean(np.abs(sig[break_point - 30:break_point]))
    at_break_abs_z = np.nanmean(np.abs(sig[break_point:break_point + 20]))
    print(f"pre-break mean|z|={pre_break_abs_z:.2f}, at-break mean|z|={at_break_abs_z:.2f} (expect at-break notably higher)")
    assert at_break_abs_z > pre_break_abs_z + 0.5, \
        f"expected the break signal to spike at a genuine equilibrium collapse, pre={pre_break_abs_z}, at={at_break_abs_z}"


if __name__ == "__main__":
    tests = [
        test_to_angle_domain_endpoints,
        test_true_opposite_pair_angle_sum_is_the_real_invariant,
        test_decomposition_is_exact_identity,
        test_causality_no_future_leakage,
        test_arccos_arcsin_break_signal_agree_near_pinned_regime,
        test_break_signal_flags_a_genuine_equilibrium_collapse,
    ]
    passed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"FAILED: {test.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} checks passed")
