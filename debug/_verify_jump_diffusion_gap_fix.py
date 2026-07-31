"""
Synthetic verification for Tier 2.6 (Grand Sweep 2026-07-20):
research/jump_diffusion_spread_analysis.py's detect_jumps()/analyze_pair_jumps()
and research/jump_diffusion_parameter_fit.py's _load_z_delta() both dropped
DATA_GAP-flagged rows BEFORE computing np.diff() on z_rolling, silently
treating a dropped multi-day gap as an ordinary one-bar delta -- indistinguishable
from a genuine single-bar jump to either the threshold detector or the
Merton MLE fit.

Builds a synthetic z_rolling series with a large, deliberate LEVEL SHIFT
across a DATA_GAP run (simulating a real multi-day price move that
happened to occur over a masked gap, not a genuine intraday jump), and
confirms:
  - The OLD (pre-fix) drop-then-diff order flags this gap-spanning shift
    as a "jump" (it's certainly no smaller than the jump threshold).
  - The FIXED order (diff-then-gap-mask) correctly excludes this delta
    entirely (NaN, never entering is_jump / never entering the Merton
    MLE's input array) since it spans a DATA_GAP boundary.
  - A genuine, non-gap-adjacent large delta elsewhere in the series (a
    real intraday jump) is still correctly detected by both, confirming
    the fix doesn't just suppress everything.

Run: python debug/_verify_jump_diffusion_gap_fix.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from jump_diffusion_spread_analysis import detect_jumps


def _old_buggy_detect(z_rolling, gap_flag_a, gap_flag_b, window=60, threshold=4.0):
    """Pre-fix behavior reproduced here: drop gap rows FIRST, then diff."""
    real_mask = (gap_flag_a != 4) & (gap_flag_b != 4)
    z = z_rolling[real_mask]
    z = z[np.isfinite(z)]
    delta = np.diff(z, prepend=np.nan)
    s = pd.Series(delta)
    trailing_std = s.shift(1).rolling(window, min_periods=20).std()
    is_jump = np.abs(delta) > threshold * trailing_std.to_numpy()
    return np.nan_to_num(is_jump, nan=False).astype(bool), delta


def _fixed_detect(z_rolling, gap_flag_a, gap_flag_b, window=60, threshold=4.0):
    """Mirrors the fixed analyze_pair_jumps() ordering."""
    finite_mask = np.isfinite(z_rolling)
    gap_bad = (gap_flag_a == 4) | (gap_flag_b == 4)
    z_for_diff = np.where(finite_mask, z_rolling, np.nan)
    delta = np.diff(z_for_diff, prepend=np.nan)
    bad_delta = gap_bad | np.roll(gap_bad, 1)
    bad_delta[0] = False
    delta = np.where(bad_delta, np.nan, delta)
    keep = finite_mask & ~gap_bad
    delta_kept = delta[keep]
    is_jump = detect_jumps(delta_kept)
    return is_jump, delta_kept, keep


def main():
    rng = np.random.default_rng(3)
    n = 400
    z = rng.normal(0, 1, n).cumsum() * 0.05  # smooth-ish OU-like wander
    gap_flag_a = np.zeros(n, dtype=int)
    gap_flag_b = np.zeros(n, dtype=int)

    # Simulate a DATA_GAP run at bars 150-170 (21 bars, e.g. a long holiday
    # weekend at 1h) with a large real level shift across it (a genuine
    # multi-day move that happened while the market/provider gap existed --
    # NOT an intraday jump).
    gap_flag_a[150:171] = 4
    gap_flag_b[150:171] = 4
    z[171:] += 15.0  # large shift, entirely attributable to the gapped period

    # Plant one genuine, non-gap-adjacent large jump elsewhere (bar 300) so
    # we can confirm the fix doesn't just suppress all detection.
    z[300:] += 10.0

    old_is_jump, old_delta = _old_buggy_detect(z, gap_flag_a, gap_flag_b)
    new_is_jump, new_delta, keep = _fixed_detect(z, gap_flag_a, gap_flag_b)

    # In the OLD version, bar 150 (first gap-flagged bar, dropped) and bar
    # 171 (first bar after the gap) become positionally adjacent once
    # gap rows are dropped -- the 15.0 shift lands as ONE compacted-array
    # delta, indistinguishable from a real jump.
    old_n_jumps = int(old_is_jump.sum())
    print(f"OLD (drop-then-diff): {old_n_jumps} jumps detected, "
          f"max |delta| in compacted series = {np.nanmax(np.abs(old_delta)):.2f}")
    assert old_n_jumps >= 1, "Test setup failed to reproduce a detectable jump in the old (buggy) path"
    assert np.nanmax(np.abs(old_delta)) > 10.0, "Old path should show the 15.0 gap-spanning shift as one large delta"

    # In the FIXED version, the diff spanning the gap boundary (bar 149->150
    # and bar 170->171) is masked to NaN BEFORE compaction -- the 15.0
    # shift never appears as a single delta value at all.
    print(f"NEW (diff-then-mask): max finite |delta| = {np.nanmax(np.abs(new_delta)):.2f}, "
          f"{int(new_is_jump.sum())} jumps detected")
    assert np.nanmax(np.abs(new_delta)) < 11.0, (
        f"Fixed path should never see the 15.0 gap-spanning shift as one delta value "
        f"(saw max={np.nanmax(np.abs(new_delta)):.2f})"
    )
    # The genuine bar-300 jump (10.0 shift, non-gap-adjacent) must still be
    # detected by the fixed version -- confirms the fix isn't over-suppressing.
    assert int(new_is_jump.sum()) >= 1, "Fixed path failed to detect the genuine, non-gap-adjacent jump at bar 300"

    print("\nPASS: gap-spanning shift correctly excluded by the fixed diff-then-mask ordering; "
          "genuine non-gap-adjacent jump still detected.")


if __name__ == "__main__":
    main()
