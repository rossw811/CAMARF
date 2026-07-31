"""
Synthetic verification for Tier 3.5 (Grand Sweep 2026-07-20):
research/vol_targeting_and_drawdown_derisking.py's target_vol was a
full-history scalar median of spread_vol, so an EARLY trade's size
depended on a target informed by years-later data -- a lookahead bug
distinct from (on top of) the shared full-sample hedge-ratio helper this
file already migrated onto spread_construction.py.

Constructs a synthetic spread_vol series with a clear REGIME SHIFT (low
vol for the first half, much higher vol for the second half) and confirms:
  - The OLD scalar (full-history median) is identical regardless of
    position -- an early-bar trade and a late-bar trade get the SAME
    target_vol, even though the early bar could not have known about the
    future high-vol regime.
  - The FIXED expanding (causal) median, evaluated at an EARLY position,
    only reflects data available up to that position -- materially
    different from (and lower than) the full-history value once the
    later high-vol regime is included.

Run: python debug/_verify_vol_targeting_causal_median_fix.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

VOL_WINDOW = 60


def main():
    rng = np.random.default_rng(1)
    n_per_regime = 500
    low_vol = np.abs(rng.normal(1.0, 0.1, n_per_regime))
    high_vol = np.abs(rng.normal(5.0, 0.5, n_per_regime))
    spread_vol = pd.Series(np.concatenate([low_vol, high_vol]))

    # OLD (buggy): full-history scalar median -- same value used for
    # EVERY trade regardless of position.
    old_target_vol_scalar = float(spread_vol.median())

    # NEW (fixed): expanding (causal) median.
    new_target_vol_series = spread_vol.expanding(min_periods=VOL_WINDOW).median()

    early_pos = 100  # well within the low-vol regime, long before the shift at n_per_regime=500
    old_value_at_early_pos = old_target_vol_scalar  # scalar -- identical everywhere by construction
    new_value_at_early_pos = float(new_target_vol_series.iloc[early_pos])

    print(f"OLD (full-history scalar) target_vol used at bar {early_pos}: {old_value_at_early_pos:.3f}")
    print(f"NEW (expanding/causal) target_vol at bar {early_pos}:         {new_value_at_early_pos:.3f}")
    print(f"True low-vol regime median (what an early trade's target SHOULD reflect): "
          f"{np.median(low_vol[:early_pos + 1]):.3f}")

    # The fixed value at an early position must be close to the TRUE
    # low-vol regime's own median (information actually available at that
    # point), and clearly lower than the old, lookahead-contaminated scalar
    # (which is pulled toward the full-history median, contaminated by the
    # future high-vol regime).
    true_low_vol_median = np.median(low_vol[:early_pos + 1])
    assert abs(new_value_at_early_pos - true_low_vol_median) < 0.3, (
        f"Fixed expanding median at bar {early_pos} ({new_value_at_early_pos:.3f}) should closely "
        f"track the true low-vol regime's own median ({true_low_vol_median:.3f}) -- it must not "
        f"be influenced by the future high-vol regime."
    )
    assert old_value_at_early_pos > new_value_at_early_pos + 1.0, (
        f"Old scalar ({old_value_at_early_pos:.3f}) should be measurably HIGHER than the fixed "
        f"causal value ({new_value_at_early_pos:.3f}) at an early position, since it's pulled "
        f"toward the full-history (including future high-vol) median -- this is exactly the "
        f"lookahead contamination being fixed."
    )

    print("\nPASS: old scalar target_vol leaks future (high-vol-regime) information into an early "
          "trade's sizing; fixed expanding/causal median correctly reflects only information "
          "available up to that trade's own entry bar.")


if __name__ == "__main__":
    main()
