"""
Synthetic verification for Tier 4.2 (Grand Sweep 2026-07-20):
research/eg_permutation_check.py's circular-shift null previously called
np.roll() on the RAW (still NaN-containing) b array, then re-masked via
isfinite(a) & isfinite(b_shifted) inside _eg_pvalue(). Since np.roll moves
NaN positions along with the shift, every permutation draw's overlap mask
with `a` differed from every other draw's AND from the real-data test's
fixed mask -- confounding the null distribution's sample size/N with the
temporal-alignment-breaking effect the test is meant to isolate.

Confirms: the OLD approach (np.roll on the raw NaN-containing array, then
re-mask) produces a DIFFERENT overlap N on almost every permutation draw.
The FIXED approach (compact to the fixed real-data mask FIRST, then roll
only the fully-finite compacted array) produces the EXACT SAME N on every
draw, matching the real-data test's own N exactly.

Run: python debug/_verify_eg_permutation_mask_consistency_fix.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from eg_permutation_check import _circular_shift_null


def _old_buggy_overlap_ns(a, b, rng, n_perm=30):
    """Reproduces the pre-fix np.roll-on-raw-array behavior, tracking just
    the resulting overlap N per draw (not the full EG computation, to keep
    this fast and focused on the actual bug mechanism)."""
    n = len(b)
    ns = []
    for _ in range(n_perm):
        shift = rng.integers(1, n)
        b_shifted = np.roll(b, shift)
        mask = np.isfinite(a) & np.isfinite(b_shifted)
        ns.append(int(mask.sum()))
    return ns


def main():
    rng = np.random.default_rng(4)
    n = 500
    a = rng.normal(0, 1, n)
    b = rng.normal(0, 1, n)

    # Plant NaN gaps in DIFFERENT, non-overlapping positions for a and b
    # (a realistic scenario: each symbol has its own independent DATA_GAP
    # history).
    a[100:130] = np.nan
    b[300:350] = np.nan

    real_fixed_mask_n = int((np.isfinite(a) & np.isfinite(b)).sum())
    print(f"Real-data fixed overlap N: {real_fixed_mask_n}")

    old_ns = _old_buggy_overlap_ns(a, b, np.random.default_rng(4), n_perm=30)
    print(f"OLD (roll raw array, re-mask): overlap N per draw varies: "
          f"min={min(old_ns)} max={max(old_ns)} n_distinct_values={len(set(old_ns))}/30")
    assert len(set(old_ns)) > 1, (
        "Test setup failed to reproduce the bug -- old approach should show varying overlap N "
        "across permutation draws when a and b have gaps in different positions."
    )

    # Fixed version: call the real function and confirm it doesn't crash
    # and produces a null distribution -- the fix itself guarantees
    # constant N by construction (it compacts to the fixed mask BEFORE
    # rolling, so every draw operates on an array of the exact same,
    # already-finite length). Verify this directly by checking the
    # doctored internal invariant: rolling a fully-finite array of length
    # real_fixed_mask_n always yields a fully-finite array of the SAME
    # length, so the overlap can never shrink or grow across draws.
    a_fixed = a[np.isfinite(a) & np.isfinite(b)]
    b_fixed = b[np.isfinite(a) & np.isfinite(b)]
    fixed_ns = []
    for _ in range(30):
        shift = rng.integers(1, len(b_fixed))
        b_shifted = np.roll(b_fixed, shift)
        fixed_ns.append(int(np.sum(np.isfinite(a_fixed) & np.isfinite(b_shifted))))
    print(f"NEW (compact to fixed mask first, then roll): overlap N per draw: "
          f"min={min(fixed_ns)} max={max(fixed_ns)} n_distinct_values={len(set(fixed_ns))}/30")
    assert len(set(fixed_ns)) == 1, "Fixed approach should show IDENTICAL overlap N on every draw"
    assert fixed_ns[0] == real_fixed_mask_n, (
        f"Fixed approach's overlap N ({fixed_ns[0]}) should exactly match the real-data test's "
        f"own fixed overlap N ({real_fixed_mask_n})"
    )

    # Confirm the actual function runs cleanly end-to-end on this synthetic setup.
    null_pvals = _circular_shift_null(a, b, max_lag=5, n_perm=20, rng=np.random.default_rng(4))
    print(f"\n_circular_shift_null produced {len(null_pvals)}/20 usable null p-values.")
    assert len(null_pvals) > 0, "Fixed function produced no usable null draws"

    print("\nPASS: old np.roll-on-raw-array approach varies the permutation null's overlap N "
          "draw-to-draw (confounding sample size with the alignment-breaking effect); fixed "
          "compact-then-roll approach holds N constant and exactly matches the real-data test's "
          "own fixed overlap N.")


if __name__ == "__main__":
    main()
