"""
Synthetic verification for Tier 2.3 (Grand Sweep 2026-07-20): the pooled-
window seam-contamination bug in research/earnings_lead_lag.py (same class
copied verbatim into research/big_move_lead_lag.py).

Constructs two independent white-noise return series over a long, evenly-
spaced 1h index, with two disjoint "earnings windows" separated by a large
real time gap. A strong artificial lagged relationship is planted ONLY
across the seam between window 1's tail and window 2's head — i.e. it only
appears if a shift/join treats the two windows as one contiguous positional
sequence. The pre-fix `_pooled_scan` (boolean-mask the combined windows into
one compacted array, then call lead_lag_scan.lagged_corr_scan positionally)
should pick up this planted seam artifact as a spurious "best lag". The
fixed version (per-window shift + join, pool only the resulting value pairs)
must NOT detect it, since it never treats the two windows as adjacent.

Run: python debug/_verify_earnings_lead_lag_seam_fix.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from lead_lag_scan import lagged_corr_scan, best_lag, _MIN_CORR_N
from earnings_lead_lag import _earnings_window_mask, _earnings_windows, _pooled_scan


def _old_buggy_pooled_scan(ret_a, ret_b, mask, max_lag):
    """Pre-fix implementation, reproduced here (not imported -- the fixed
    module no longer contains it) purely to demonstrate the bug it had."""
    if mask.sum() < 10:
        return None
    sub_a = ret_a[mask]
    sub_b = ret_b[mask]
    scan = lagged_corr_scan(sub_a, sub_b, max_lag)
    return best_lag(scan)


def main():
    rng = np.random.default_rng(7)
    n_per_window = 40
    max_lag = 40

    # Window 1: bars 0..39. Window 2: bars 0..39 of a SEPARATE block, placed
    # far away in real time (a ~90-day gap -- like two distant earnings
    # events for the same symbol). At exactly lag=n_per_window, a positional
    # shift/join over the NAIVELY CONCATENATED array pairs 100% of window1's
    # symbol-A bars with 100% of window2's symbol-B bars (a[i] with
    # b[i+40]) -- no noise dilution, so any planted cross-window
    # relationship shows up at full strength if (and only if) the seam bug
    # is present.
    idx1 = pd.date_range("2020-01-01", periods=n_per_window, freq="1h")
    idx2 = pd.date_range("2020-04-01", periods=n_per_window, freq="1h")
    full_idx = idx1.append(idx2)

    a1 = rng.normal(0, 1, n_per_window)
    b1 = rng.normal(0, 1, n_per_window)
    a2 = rng.normal(0, 1, n_per_window)
    # Plant a strong artificial dependency ACROSS the seam: window 2's
    # entire ret_b series is built from window 1's ret_a series -- this
    # relationship is semantically meaningless (symbol A's price action
    # during a DIFFERENT, unrelated earnings event) and must never surface
    # in a correct implementation, since the two windows share no real
    # temporal or causal link.
    b2 = a1 * 3.0 + rng.normal(0, 0.01, n_per_window)

    ret_a = pd.Series(np.concatenate([a1, a2]), index=full_idx)
    ret_b = pd.Series(np.concatenate([b1, b2]), index=full_idx)

    mask = np.ones(len(full_idx), dtype=bool)
    windows = [(idx1.min(), idx1.max()), (idx2.min(), idx2.max())]

    old_result = _old_buggy_pooled_scan(ret_a, ret_b, mask, max_lag)
    new_result = _pooled_scan(ret_a, ret_b, mask, windows, max_lag)

    print(f"Old (buggy, boolean-mask + positional shift) best_lag result: {old_result}")
    print(f"New (fixed, per-window shift, pooled value-pairs) best_lag result: {new_result}")

    old_lag = old_result[0] if old_result else None

    # The old (buggy) implementation must be fooled by the seam: it should
    # pick lag=+n_per_window (the exact planted cross-window relationship)
    # with a strong |corr|.
    assert old_lag == n_per_window, (
        f"Test setup failed to reproduce the seam artifact -- old implementation picked "
        f"lag={old_lag}, expected {n_per_window}"
    )
    assert abs(old_result[1]) > 0.9, f"Planted seam correlation too weak: {old_result[1]}"

    # The fixed implementation must NEVER surface the planted cross-window
    # relationship -- within either window alone, ret_a and ret_b are
    # genuinely independent noise, so no lag should show a strong |corr|.
    if new_result is not None and new_result[1] is not None:
        print(f"New implementation's reported |corr| at its best lag: {new_result[1]:.3f} (lag={new_result[0]})")
        assert abs(new_result[1]) < 0.5, (
            f"Fixed implementation still shows a suspiciously strong correlation "
            f"({new_result[1]:.3f}) -- seam contamination may not be fully eliminated."
        )
    else:
        print("New implementation found no usable lag at all (expected -- windows are too short "
              "individually to support the full +/-40 lag scan at _MIN_CORR_N=30).")

    print("\nPASS: seam-contamination fix verified -- old implementation was fooled by the "
          "planted cross-window relationship (lag=+40, |corr|>0.9), fixed implementation was not.")


if __name__ == "__main__":
    main()
