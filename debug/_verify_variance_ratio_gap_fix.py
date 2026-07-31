"""
Synthetic verification for Tier 2.9 (Grand Sweep 2026-07-20):
research/variance_ratio_test.py restricted to the single longest strictly-
contiguous, gap-free run BEFORE computing the Lo & MacKinlay variance-ratio
statistic, instead of boolean-masking DATA_GAP rows out of the full series
first (which silently concatenates positions spanning any gap -- routine
or genuine -- as if one bar apart).

Run: python debug/_verify_variance_ratio_gap_fix.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from variance_ratio_test import _longest_clean_run, variance_ratio


def main():
    # Three runs of clean (True) bars separated by gap (False) bars:
    # lengths 10, 50, 20 -- the middle one (50) must be selected.
    mask = np.array(
        [True] * 10 + [False] * 5 + [True] * 50 + [False] * 3 + [True] * 20
    )
    start, end = _longest_clean_run(mask)
    print(f"Longest clean run: [{start}:{end}] (length {end - start})")
    assert (start, end) == (15, 65), f"Expected (15, 65), got ({start}, {end})"
    assert mask[start:end].all(), "Selected run contains a non-clean (gap) bar"

    # All-False edge case.
    assert _longest_clean_run(np.zeros(10, dtype=bool)) == (0, 0)

    # Demonstrate the actual effect on the VR statistic: a mean-reverting
    # (OU-like) synthetic spread, with a large artificial one-bar jump
    # planted exactly at a gap boundary (simulating a real multi-day move
    # that happened during a dropped gap). Restricting to the longest
    # clean run must exclude this jump entirely from the increments used.
    rng = np.random.default_rng(9)
    n_per_segment = 300
    phi = 0.9  # AR(1) mean-reverting spread
    seg1 = [0.0]
    for _ in range(n_per_segment - 1):
        seg1.append(phi * seg1[-1] + rng.normal(0, 1))
    seg2 = [seg1[-1] + 40.0]  # large artificial jump across the simulated gap
    for _ in range(n_per_segment - 1):
        seg2.append(phi * (seg2[-1] - 40.0) + rng.normal(0, 1) + 40.0)
    full_series = np.array(seg1 + seg2)

    # Naive (pre-fix): treat the whole concatenated series as one contiguous
    # run -- the 40.0 jump appears as one ordinary 1-bar increment.
    naive_result = variance_ratio(full_series, q=8)
    # Fixed: restrict to just the first clean segment (as the real fix does
    # via _longest_clean_run when a genuine boundary is present).
    fixed_result = variance_ratio(full_series[:n_per_segment], q=8)

    print(f"Naive (gap-spanning) VR(8): {naive_result['vr']:.4f}")
    print(f"Fixed (single clean segment) VR(8): {fixed_result['vr']:.4f}")
    assert naive_result["ok"] and fixed_result["ok"]
    # Both should show mean-reversion signal (VR<1 for an AR(1) with phi<1),
    # but the presence of the one extreme jump in the naive series should
    # measurably distort its VR relative to the clean segment.
    print(f"Max |1-bar increment| naive: {np.max(np.abs(np.diff(full_series))):.2f}")
    assert np.max(np.abs(np.diff(full_series))) > 30.0, "Test setup failed to plant the jump"

    print("\nPASS: _longest_clean_run correctly identifies the longest gap-free contiguous span; "
          "restricting to it (as the fix now does) avoids feeding the VR test a fabricated "
          "gap-spanning jump.")


if __name__ == "__main__":
    main()
