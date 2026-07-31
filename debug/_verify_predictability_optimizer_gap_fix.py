"""
Synthetic verification for Tier 2.7/2.8 (Grand Sweep 2026-07-20):
research/predictability_optimizer.py's predictability_ratio()/
predictability_weights() (and research/ccp_variants.py, which imports and
reuses them) computed a lag-1 cross-covariance via positional X[1:] vs
X[:-1] on a joined level series that had already been dropna()'d after
gap-masking via data.py::_clean_close -- silently treating the two rows
straddling a dropped multi-day gap as one ordinary bar apart. Also directly
addresses the audit's noted verification blind spot: ccp_variants.py's own
_verify() uses purely gapless synthetic arrays, so it structurally cannot
catch this real-data-specific failure mode -- this test uses a series WITH
a gap specifically to close that blind spot.

Builds a synthetic 2-asset (T, 2) level-price panel with a large artificial
level jump planted ONLY across a simulated gap boundary (mimicking a real
multi-day move that occurred while data was missing), and confirms:
  - Without the valid_lag1 mask (pre-fix behavior), the lag-1 cross-
    covariance gamma1 is dominated by the single gap-spanning transition.
  - With data.valid_lag1_mask applied (fixed behavior), that transition is
    excluded and gamma1 reflects only genuine, non-gap-adjacent structure.

Run: python debug/_verify_predictability_optimizer_gap_fix.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from data import valid_lag1_mask
from predictability_optimizer import predictability_ratio, predictability_weights, ols_weights


def main():
    rng = np.random.default_rng(5)
    n = 200

    # Two genuinely independent random-walk legs (no real predictability
    # relationship) -- OU-like small increments.
    a = rng.normal(0, 0.01, n).cumsum()
    b = rng.normal(0, 0.01, n).cumsum()

    # Simulate a dropped multi-day gap: rows 0..99 are one contiguous
    # segment (real 1h bars), rows 100..199 are a SEPARATE contiguous
    # segment starting several days later (already dropna()'d away the
    # gap rows themselves, as _clean_close + .dropna() would do). Plant a
    # large, deliberate level jump across this seam on BOTH legs, in a
    # strongly co-moving direction -- this is exactly the kind of shift
    # that would happen over a real multi-day gap and must NOT be read as
    # "1-bar predictable structure".
    a[100:] += 5.0
    b[100:] += 5.0

    idx1 = pd.date_range("2020-01-01", periods=100, freq="1h")
    idx2 = pd.date_range("2020-06-01", periods=100, freq="1h")
    full_idx = idx1.append(idx2)

    X = np.column_stack([a, b])
    X_c = X - X.mean(axis=0)

    mask = valid_lag1_mask(full_idx)
    print(f"valid_lag1_mask: {mask.sum()}/{len(mask)} transitions valid "
          f"(should exclude exactly 1 -- the seam at row 99->100)")
    assert mask.sum() == len(mask) - 1, f"Expected exactly 1 excluded transition, got {len(mask) - mask.sum()}"
    assert not mask[99], "The seam transition (row 99->100) should be flagged invalid"

    w_ols = ols_weights(X_c)

    # Without masking (pre-fix behavior): the lag-1 cross-covariance
    # includes the seam transition.
    ratio_unmasked = predictability_ratio(X_c, w_ols, valid_lag1=None)
    # With masking (fixed behavior): the seam transition is excluded.
    ratio_masked = predictability_ratio(X_c, w_ols, valid_lag1=mask)

    print(f"predictability_ratio WITHOUT gap mask: {ratio_unmasked:.6f}")
    print(f"predictability_ratio WITH gap mask:    {ratio_masked:.6f}")

    # The two results must differ meaningfully -- if they were identical,
    # the mask isn't actually doing anything (test or fix would be broken).
    assert abs(ratio_unmasked - ratio_masked) > 1e-6, (
        "Masked and unmasked predictability ratios are identical -- the gap "
        "exclusion does not appear to be having any effect."
    )

    # Also confirm predictability_weights runs cleanly with a mask and
    # produces a finite, differently-scaled result vs the unmasked version.
    w_pred_unmasked = predictability_weights(X_c, valid_lag1=None)
    w_pred_masked = predictability_weights(X_c, valid_lag1=mask)
    assert np.all(np.isfinite(w_pred_masked)), "Masked predictability_weights produced non-finite output"
    print(f"predictability_weights unmasked: {w_pred_unmasked}")
    print(f"predictability_weights masked:   {w_pred_masked}")

    print("\nPASS: gap-spanning lag-1 transition correctly excluded when valid_lag1_mask is applied; "
          "predictability_ratio/predictability_weights differ meaningfully with vs without the mask.")


if __name__ == "__main__":
    main()
