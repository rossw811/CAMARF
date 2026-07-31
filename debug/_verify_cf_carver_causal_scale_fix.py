"""
Synthetic verification for Tier 3.6 (Grand Sweep 2026-07-20):
backtest.py's `_cf_carver` (continuous-forecast Carver scaling, a STORM
comparison-arm-only feature, not gated behind any production default)
computed its `_avg_abs_entry_z` scale-factor input ONCE from the ENTIRE
z_arr passed to run() -- a full-sample average applied as a constant
multiplier throughout the whole backtest, so an early bar's position size
was informed by every future entry-z observation in the series.

This test reproduces just the scale-factor computation (old scalar vs new
expanding/causal array) on a synthetic z_arr with a clear regime shift
(modest entry-z magnitudes early, much larger ones later), confirming the
fixed expanding version at an EARLY bar reflects only the early, modest
regime -- not the full-series average pulled up by the later large-z
regime.

Run: python debug/_verify_cf_carver_causal_scale_fix.py
"""
import numpy as np

ENTRY_ZSCORE = 2.0


def old_scalar_scale_factor(z_arr):
    entry_z_pop = np.abs(z_arr[np.abs(z_arr) >= ENTRY_ZSCORE])
    avg_abs_entry_z = float(np.mean(entry_z_pop)) if len(entry_z_pop) > 0 else ENTRY_ZSCORE
    return 10.0 / avg_abs_entry_z if avg_abs_entry_z > 0 else 1.0


def new_expanding_scale_factor_arr(z_arr):
    entry_mask = np.abs(z_arr) >= ENTRY_ZSCORE
    abs_z_at_entries = np.where(entry_mask, np.abs(z_arr), 0.0)
    cum_sum = np.cumsum(abs_z_at_entries)
    cum_count = np.cumsum(entry_mask.astype(float))
    with np.errstate(invalid="ignore", divide="ignore"):
        expanding_avg = np.where(cum_count > 0, cum_sum / np.maximum(cum_count, 1.0), ENTRY_ZSCORE)
    return 10.0 / np.where(expanding_avg > 0, expanding_avg, 1.0)


def main():
    rng = np.random.default_rng(2)
    n_per_regime = 400
    # Early regime: entry-z magnitudes clustered near 2.0-3.0 (modest).
    early = rng.uniform(2.0, 3.0, n_per_regime) * rng.choice([-1, 1], n_per_regime)
    # Late regime: much larger entry-z magnitudes (8.0-10.0).
    late = rng.uniform(8.0, 10.0, n_per_regime) * rng.choice([-1, 1], n_per_regime)
    z_arr = np.concatenate([early, late])

    old_factor = old_scalar_scale_factor(z_arr)  # constant, uses BOTH regimes
    new_factor_arr = new_expanding_scale_factor_arr(z_arr)

    early_bar = 200  # well within the early, modest-z regime
    new_factor_at_early_bar = new_factor_arr[early_bar]

    print(f"OLD (full-sample scalar) scale factor, used at EVERY bar: {old_factor:.4f}")
    print(f"NEW (expanding/causal) scale factor at bar {early_bar} (early regime only): "
          f"{new_factor_at_early_bar:.4f}")

    # The old scalar (informed by the whole series, including the later
    # large-z regime) pulls the average |entry z| UP, making its scale
    # factor SMALLER (10/avg) than what an early-regime-only average would
    # give. The fixed expanding value at an early bar should be
    # meaningfully LARGER (since the early regime's avg |z| ~2.5 is much
    # smaller than the blended full-sample average).
    assert new_factor_at_early_bar > old_factor * 1.5, (
        f"Expected the fixed early-bar scale factor ({new_factor_at_early_bar:.4f}) to be "
        f"substantially larger than the old full-sample scalar ({old_factor:.4f}) -- if not, "
        f"the causal fix isn't actually excluding future data from the early bar's calculation."
    )

    # Confirm a LATE bar's expanding value converges toward the old full-
    # sample scalar (since by the end, "expanding up to this bar" ~=
    # "the full sample") -- this proves the fix isn't just producing
    # arbitrary results, it converges to the old (correct-for-a-full-
    # sample-question) answer once genuinely all data is included.
    late_bar = len(z_arr) - 1
    new_factor_at_late_bar = new_factor_arr[late_bar]
    print(f"NEW (expanding/causal) scale factor at the LAST bar: {new_factor_at_late_bar:.4f}")
    assert abs(new_factor_at_late_bar - old_factor) < 1e-6, (
        f"Expanding value at the final bar ({new_factor_at_late_bar:.6f}) should exactly equal "
        f"the old full-sample scalar ({old_factor:.6f}) -- expanding-to-the-end must equal "
        f"the full-sample computation."
    )

    print("\nPASS: fixed expanding scale factor at an early bar correctly reflects only the early "
          "regime's own (modest) entry-z magnitudes, not a lookahead-contaminated full-sample blend; "
          "at the final bar it converges exactly to the old full-sample value, as expected.")


if __name__ == "__main__":
    main()
