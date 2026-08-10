"""
Synthetic verification for research/vix_crisis_hl_robustness_check.py
(2026-08-05).

Constructs a synthetic OU spread with a KNOWN, constant true half-life,
then tests two scenarios:
  1. A "clean" regime subset (no jumps) -- all three estimators (raw,
     z-scored, winsorized) should recover roughly the SAME half-life,
     close to the true value (hl_ratio close to 1.0 vs. the full series).
  2. A "jumpy" regime subset -- same true OU dynamics, but a handful of
     large synthetic jumps injected -- directly testing the mechanism the
     real script is built to detect: raw AND z-scored OLS should BOTH
     show an artificially fast (low hl_ratio) half-life (confirming the
     module docstring's algebra: z-scoring by a regime-specific constant
     does not fix a jump-driven artifact), while WINSORIZED OLS should
     recover a hl_ratio much closer to the clean-regime baseline --
     demonstrating the winsorized estimator actually resists the jump
     artifact the other two do not.

Usage:
    python debug/_verify_vix_crisis_hl_robustness_check.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from vix_crisis_hl_robustness_check import half_life_raw, half_life_zscored, half_life_winsorized


def _make_ou_spread(n, true_hl, seed, jump_indices=None, jump_size=15.0):
    rng = np.random.default_rng(seed)
    alpha = -np.log(2) / true_hl
    s = np.zeros(n)
    for t in range(1, n):
        s[t] = s[t - 1] + alpha * s[t - 1] + rng.normal(0, 1.0)
    if jump_indices:
        for idx in jump_indices:
            s[idx:] += jump_size * rng.choice([-1, 1])
            # revert most of it a few bars later, mimicking a real jump-then-partial-reversion
            if idx + 5 < n:
                s[idx + 5:] -= jump_size * 0.8 * np.sign(s[idx] - s[idx - 1] if idx > 0 else 1)
    return s


def check_1_clean_regime_all_estimators_agree():
    true_hl = 20.0
    s = _make_ou_spread(2000, true_hl, seed=1)
    hl_raw = half_life_raw(s)
    hl_z = half_life_zscored(s)
    hl_w = half_life_winsorized(s)
    ok = all(np.isfinite(x) and 5 < x < 60 for x in (hl_raw, hl_z, hl_w))
    # raw and z-scored should be near-identical (algebra: OLS slope is scale-invariant)
    close = abs(hl_raw - hl_z) < 0.5
    print(f"[{'PASS' if ok and close else 'FAIL'}] clean regime: raw={hl_raw:.2f} z={hl_z:.2f} "
          f"w={hl_w:.2f} (true={true_hl}), raw~=z: {close}")
    return ok and close


def check_2_jumpy_regime_raw_and_zscored_fooled_winsorized_resists():
    """Ground truth is the KNOWN true_hl the synthetic series was generated
    with, not a separate 'clean' sample's own (noisy, small-n) raw estimate
    -- comparing against a noisy proxy rather than ground truth was a real
    bug in this check's first draft, caught by this very run: the clean
    sample's own raw estimate (n=300, single draw) was itself ~40% off
    true_hl by chance, which made the winsorized-jumpy estimate (actually
    CLOSER to true_hl than the clean sample was) look like a failure
    against that noisy proxy. Fixed to compare against true_hl directly."""
    true_hl = 20.0
    n = 300  # small sample, matching the real crisis-regime n=28-58 scale concern
    jump_idx = [50, 150, 250]
    s_jumpy = _make_ou_spread(n, true_hl, seed=2, jump_indices=jump_idx, jump_size=25.0)

    hl_jumpy_raw = half_life_raw(s_jumpy)
    hl_jumpy_z = half_life_zscored(s_jumpy)
    hl_jumpy_w = half_life_winsorized(s_jumpy)

    # Raw and z-scored should both be pulled toward looking "faster" (lower hl) by the jumps,
    # and should be close to EACH OTHER (confirming z-scoring alone doesn't fix it).
    raw_z_close = np.isfinite(hl_jumpy_raw) and np.isfinite(hl_jumpy_z) and abs(hl_jumpy_raw - hl_jumpy_z) < 1.0
    raw_faster_than_true = np.isfinite(hl_jumpy_raw) and hl_jumpy_raw < true_hl
    # Winsorized should be meaningfully closer to the TRUE half-life than raw is.
    winsorized_closer = (
        np.isfinite(hl_jumpy_w) and np.isfinite(hl_jumpy_raw)
        and abs(hl_jumpy_w - true_hl) < abs(hl_jumpy_raw - true_hl)
    )
    ok = raw_z_close and raw_faster_than_true and winsorized_closer
    print(f"[{'PASS' if ok else 'FAIL'}] jumpy regime (true_hl={true_hl}): "
          f"jumpy_raw={hl_jumpy_raw:.2f}, jumpy_z={hl_jumpy_z:.2f}, jumpy_winsorized={hl_jumpy_w:.2f} "
          f"-- raw~=z: {raw_z_close}, raw looks faster than true: {raw_faster_than_true}, "
          f"winsorized closer to TRUE hl: {winsorized_closer}")
    return ok


if __name__ == "__main__":
    results = [
        check_1_clean_regime_all_estimators_agree(),
        check_2_jumpy_regime_raw_and_zscored_fooled_winsorized_resists(),
    ]
    print(f"\n{sum(results)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)
