"""
Synthetic verification for research/cross_timeframe_cointegration.py
(2026-08-04), before trusting it on real pair data -- matching this
project's verify-before-trusting discipline.

Construction: a shared latent trend generated at FINE frequency
(n_coarse * K points). The FINE leg tracks this trend closely (small
mean-reverting noise added). The COARSE leg is sampled from the SAME
trend at every K-th fine point, with its own noise and hedge ratio. This
makes the fine leg's MIDAS-aggregated recent history and the coarse
leg's level share a genuine long-run equilibrium -- a real cross-
frequency cointegrating relationship, by construction, not assumed.

For the null/spurious case (guarding against the same "correlation
without a real equilibrium" failure mode research/inverse_polarity.py's
own docstring warns about): coarse and fine legs use INDEPENDENT trends.

Checks:
  1. Method A (downsample EG) correctly rejects the unit-root null for
     the true cross-TF cointegrated case, and correctly fails to reject
     it for the independent-trends null case.
  2. Method B (MIDAS residual stationarity) same two directions.
  3. Method C (coarse-predicts-fine-cumret residual) same two directions.
  4. Causality: Method B's regression only uses fine-leg data STRICTLY
     BEFORE each coarse timestamp (inherited from midas_aggregate's own
     causal guarantee) -- perturbing fine-leg data strictly AFTER a given
     coarse timestamp must not change that timestamp's MIDAS-aggregated
     feature value.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from cross_timeframe_cointegration import (
    method_a_downsample_eg,
    method_b_midas_residual_stationarity,
    method_c_coarse_predicts_fine_cumret,
)
from midas_feature import midas_aggregate


def _make_synthetic_pair(n_coarse=300, K=5, seed=0, cointegrated=True):
    """Returns (coarse_df, fine_df) with 'close' + a datetime index,
    matching what DataStore.load returns closely enough for these
    functions' actual usage (they only read .index and 'close')."""
    rng = np.random.default_rng(seed)
    n_fine = n_coarse * K

    coarse_dates = pd.date_range("2020-01-01", periods=n_coarse, freq="D")
    fine_dates = pd.date_range("2020-01-01", periods=n_fine, freq=f"{24 * 60 // K}min")

    if cointegrated:
        trend_fine = np.cumsum(rng.normal(0, 0.01, n_fine))
        fine_noise = np.zeros(n_fine)
        for i in range(1, n_fine):
            fine_noise[i] = 0.5 * fine_noise[i - 1] + rng.normal(0, 0.003)
        fine_log_price = trend_fine + fine_noise

        coarse_noise = np.zeros(n_coarse)
        for i in range(1, n_coarse):
            coarse_noise[i] = 0.5 * coarse_noise[i - 1] + rng.normal(0, 0.01)
        hedge = 1.3
        coarse_log_price = hedge * trend_fine[::K][:n_coarse] + coarse_noise
    else:
        trend_fine = np.cumsum(rng.normal(0, 0.01, n_fine))
        trend_coarse_independent = np.cumsum(rng.normal(0, 0.01, n_coarse))
        fine_log_price = trend_fine
        coarse_log_price = trend_coarse_independent

    coarse_close = np.exp(coarse_log_price) * 100
    fine_close = np.exp(fine_log_price) * 100

    coarse_df = pd.DataFrame({"close": coarse_close, "gap_flag": np.zeros(n_coarse, dtype=int)}, index=coarse_dates)
    fine_df = pd.DataFrame({"close": fine_close, "gap_flag": np.zeros(n_fine, dtype=int)}, index=fine_dates)
    return coarse_df, fine_df


def test_method_a_recovers_true_and_rejects_null():
    coarse_df, fine_df = _make_synthetic_pair(cointegrated=True, seed=1)
    r_true = method_a_downsample_eg(coarse_df, fine_df)
    print(f"[A] true cross-TF cointegrated pair: p={r_true['coint_pvalue']:.4f} (expect < 0.05)")
    assert r_true["coint_pvalue"] < 0.05, f"Method A should reject unit-root null for the true case, got p={r_true['coint_pvalue']}"

    coarse_df_n, fine_df_n = _make_synthetic_pair(cointegrated=False, seed=2)
    r_null = method_a_downsample_eg(coarse_df_n, fine_df_n)
    print(f"[A] independent-trends null pair: p={r_null['coint_pvalue']:.4f} (expect > 0.05)")
    assert r_null["coint_pvalue"] > 0.05, f"Method A should fail to reject the null for independent trends, got p={r_null['coint_pvalue']}"


def test_method_b_recovers_true_and_rejects_null():
    coarse_df, fine_df = _make_synthetic_pair(cointegrated=True, seed=1)
    coarse_log = pd.Series(np.log(coarse_df["close"].values), index=coarse_df.index)
    fine_log = pd.Series(np.log(fine_df["close"].values), index=fine_df.index)
    r_true = method_b_midas_residual_stationarity(coarse_log, fine_log, K=5)
    print(f"[B] true cross-TF cointegrated pair: adf_p={r_true['adf_pvalue']:.4f} (expect < 0.05)")
    assert r_true["adf_pvalue"] < 0.05, f"Method B should find a stationary residual for the true case, got p={r_true['adf_pvalue']}"

    coarse_df_n, fine_df_n = _make_synthetic_pair(cointegrated=False, seed=2)
    coarse_log_n = pd.Series(np.log(coarse_df_n["close"].values), index=coarse_df_n.index)
    fine_log_n = pd.Series(np.log(fine_df_n["close"].values), index=fine_df_n.index)
    r_null = method_b_midas_residual_stationarity(coarse_log_n, fine_log_n, K=5)
    print(f"[B] independent-trends null pair: adf_p={r_null['adf_pvalue']:.4f} (expect > 0.05)")
    assert r_null["adf_pvalue"] > 0.05, f"Method B should NOT find a stationary residual for independent trends, got p={r_null['adf_pvalue']}"


def _make_predictive_synthetic_pair(n_coarse=300, K=5, seed=0, predictive=True):
    """Dedicated construction for Method C, DISTINCT from
    _make_synthetic_pair above -- found necessary live, not assumed: the
    shared-trend construction used for Methods A/B (a contemporaneous
    equilibrium) does NOT guarantee the coarse level linearly predicts the
    fine leg's FUTURE return, which is the genuinely different hypothesis
    Method C actually tests (confirmed by running the shared-trend
    construction through the redesigned Method C first: it correctly
    found no significant discrimination, perm_p=0.094, rather than the
    tautological pass the old ADF-based version gave). This construction
    instead builds an EXPLICIT causal predictive link: the fine leg's
    return over each coarse period is directly, linearly driven by the
    PRIOR coarse period's level (plus noise), so Method C's regression has
    a real, findable target. Null case keeps the two fully independent,
    as before."""
    rng = np.random.default_rng(seed)
    n_fine = n_coarse * K
    coarse_dates = pd.date_range("2020-01-01", periods=n_coarse, freq="D")
    fine_dates = pd.date_range("2020-01-01", periods=n_fine, freq=f"{24 * 60 // K}min")

    coarse_level = np.cumsum(rng.normal(0, 0.02, n_coarse))  # arbitrary random-walk level, not price-like scale
    fine_log_price = np.zeros(n_fine)
    if predictive:
        # each coarse period's fine-leg return is directly driven by the
        # PRIOR coarse level (a real causal predictive link) plus noise
        signal_strength = 0.05
        for i in range(n_coarse):
            period_ret = signal_strength * coarse_level[max(0, i - 1)] + rng.normal(0, 0.01, K)
            start = i * K
            fine_log_price[start:start + K] = (fine_log_price[start - 1] if start > 0 else 0) + np.cumsum(period_ret)
    else:
        fine_log_price = np.cumsum(rng.normal(0, 0.02, n_fine))  # fully independent random walk

    coarse_close = np.exp(coarse_level) * 100
    fine_close = np.exp(fine_log_price) * 100
    coarse_df = pd.DataFrame({"close": coarse_close, "gap_flag": np.zeros(n_coarse, dtype=int)}, index=coarse_dates)
    fine_df = pd.DataFrame({"close": fine_close, "gap_flag": np.zeros(n_fine, dtype=int)}, index=fine_dates)
    return coarse_df, fine_df


def test_method_c_recovers_true_and_rejects_null():
    """Method C was REDESIGNED after this exact test caught it having zero
    discriminating power (ADF-on-residual found adf_p=0.0000 for BOTH the
    true and null cases -- see module docstring / Development.md). Now
    uses a circular-shift permutation test on the regression correlation,
    matching this project's established lead-lag permutation convention.

    Uses ITS OWN dedicated synthetic construction (_make_predictive_
    synthetic_pair), not the shared-trend one Methods A/B use -- a real,
    live finding: running the shared-trend construction through the fixed
    Method C found NO significant discrimination (perm_p=0.094), because
    a contemporaneous equilibrium does not imply the coarse level linearly
    predicts the fine leg's FUTURE return -- a genuinely different
    hypothesis, confirmed empirically, not just argued."""
    coarse_df, fine_df = _make_predictive_synthetic_pair(predictive=True, seed=1)
    coarse_log = pd.Series(np.log(coarse_df["close"].values), index=coarse_df.index)
    fine_ret = pd.Series(fine_df["close"].values, index=fine_df.index)
    fine_ret = np.log(fine_ret).diff().dropna()
    r_true = method_c_coarse_predicts_fine_cumret(coarse_log, fine_ret, n_perm=500, seed=10)
    print(f"[C] genuine predictive-link pair: perm_p={r_true['perm_pvalue']:.4f}, "
          f"observed_corr={r_true['observed_corr']:.3f} (expect perm_p < 0.05)")
    assert r_true["perm_pvalue"] < 0.05, \
        f"Method C should find significant predictive correlation for a genuine causal-predictive construction, got perm_p={r_true['perm_pvalue']}"

    coarse_df_n, fine_df_n = _make_predictive_synthetic_pair(predictive=False, seed=2)
    coarse_log_n = pd.Series(np.log(coarse_df_n["close"].values), index=coarse_df_n.index)
    fine_ret_n = np.log(pd.Series(fine_df_n["close"].values, index=fine_df_n.index)).diff().dropna()
    r_null = method_c_coarse_predicts_fine_cumret(coarse_log_n, fine_ret_n, n_perm=500, seed=11)
    print(f"[C] independent-trends null pair: perm_p={r_null['perm_pvalue']:.4f}, "
          f"observed_corr={r_null['observed_corr']:.3f} (expect perm_p > 0.05)")
    assert r_null["perm_pvalue"] > 0.05, \
        f"Method C should NOT find significant predictive correlation for independent trends, got perm_p={r_null['perm_pvalue']}"


def test_midas_aggregate_causality_inherited():
    """Confirms the causality guarantee Method B depends on (inherited
    from midas_feature.midas_aggregate, not re-derived) actually holds
    for this module's own usage pattern."""
    rng = np.random.default_rng(3)
    n_coarse, K = 50, 5
    n_fine = n_coarse * K
    coarse_dates = pd.date_range("2020-01-01", periods=n_coarse, freq="D")
    fine_dates = pd.date_range("2020-01-01", periods=n_fine, freq="288min")
    fine_series = pd.Series(rng.normal(0, 1, n_fine), index=fine_dates)

    t_check = 25
    check_ts = coarse_dates[t_check]
    agg_before = midas_aggregate(fine_series.copy(), coarse_dates, K, 1.0, 3.0)

    perturbed = fine_series.copy()
    perturbed[perturbed.index > check_ts] += 1000.0
    agg_after = midas_aggregate(perturbed, coarse_dates, K, 1.0, 3.0)

    assert np.isclose(agg_before[check_ts], agg_after[check_ts], equal_nan=True), \
        "midas_aggregate leaked future information for this module's usage pattern"
    print(f"causality check: OK -- MIDAS aggregate at t={t_check} unaffected by a future perturbation")


if __name__ == "__main__":
    tests = [
        test_method_a_recovers_true_and_rejects_null,
        test_method_b_recovers_true_and_rejects_null,
        test_method_c_recovers_true_and_rejects_null,
        test_midas_aggregate_causality_inherited,
    ]
    passed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"FAILED: {test.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} checks passed")
