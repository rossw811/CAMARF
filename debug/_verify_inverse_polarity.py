"""
Synthetic verification for research/inverse_polarity.py (2026-08-03), before
trusting it on real pair data -- matching this project's verify-before-
trusting discipline.

Checks:
  1. zscore_tanh_polarity / percentile_rank_polarity are correctly BOUNDED
     to [-1, 1] and recover known extremes: a series pinned at its rolling
     max should read near +1, pinned at its rolling min near -1.
  2. polarity_anti_correlation gives HIGH POSITIVE correlation for two
     genuinely anti-phase polarity series (A near +1 exactly when B is near
     -1) and LOW correlation for two independent series -- checks
     direction, not just a plausible range. NOTE: "anti-correlation" here
     means the TWO POLARITY SERIES correlate near -1 with EACH OTHER when
     truly opposite, which shows up as polarity_anti_correlation returning
     values near -1 for a true opposite-extremes pair -- verified below.
  3. screen_anti_correlated_pair correctly identifies a KNOWN stationary,
     negative-hedge synthetic spread as cointegrated with a negative fitted
     hedge ratio, and correctly REJECTS a random-walk (non-cointegrated)
     synthetic pair with the same negative return correlation -- this is
     the exact "correlation alone is not enough" guard the module's own
     docstring exists to test for.
  4. CAUSALITY: all three metrics and polarity_anti_correlation are
     rolling-only -- perturbing values strictly AFTER time t must not
     change the value at t. Same class of check this project's causality
     audit (BUG-D99-103) already established as mandatory.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from inverse_polarity import (
    zscore_tanh_polarity,
    percentile_rank_polarity,
    eg_spread_zscore_polarity,
    polarity_anti_correlation,
    screen_anti_correlated_pair,
)


def test_zscore_tanh_bounded_and_extremes():
    rng = np.random.default_rng(0)
    n = 300
    log_price = np.log(100 + np.cumsum(rng.normal(0, 0.3, n)))
    pol = zscore_tanh_polarity(log_price, window=60)
    finite = pol[np.isfinite(pol)]
    assert finite.size > 0, "expected some finite polarity values"
    assert np.all(finite >= -1.0 - 1e-9) and np.all(finite <= 1.0 + 1e-9), \
        f"zscore_tanh_polarity must be bounded to [-1,1], got range [{finite.min()}, {finite.max()}]"

    # Force a clean spike well above the local rolling mean/std -> polarity near +1.
    spiked = log_price.copy()
    spiked[250] = log_price[190:250].mean() + 6 * log_price[190:250].std()
    pol_spike = zscore_tanh_polarity(spiked, window=60)
    print(f"spike-bar polarity={pol_spike[250]:.3f} (expect near +1)")
    assert pol_spike[250] > 0.9, f"expected spike bar polarity near +1, got {pol_spike[250]}"


def test_percentile_rank_bounded_and_extremes():
    rng = np.random.default_rng(1)
    n = 200
    price = 50 + np.cumsum(rng.normal(0, 0.5, n))
    price[150] = price[100:150].max() + 10  # new local max
    pol = percentile_rank_polarity(price, window=60)
    finite = pol[np.isfinite(pol)]
    assert np.all(finite >= -1.0 - 1e-9) and np.all(finite <= 1.0 + 1e-9), \
        f"percentile_rank_polarity must be bounded to [-1,1], got range [{finite.min()}, {finite.max()}]"
    print(f"new-max-bar percentile polarity={pol[150]:.3f} (expect == 1.0, it's the window max)")
    assert pol[150] > 0.95, f"expected the new max to rank near +1, got {pol[150]}"


def test_eg_spread_zscore_polarity_passthrough():
    z = np.array([0.0, 2.0, -2.0, np.nan, 10.0])
    pol = eg_spread_zscore_polarity(z)
    expected = np.tanh(z)
    assert np.allclose(pol[np.isfinite(pol)], expected[np.isfinite(expected)]), \
        "eg_spread_zscore_polarity must be a pure tanh passthrough of the input"
    print("eg_spread_zscore_polarity passthrough: OK")


def test_polarity_anti_correlation_high_for_true_opposite_pair():
    rng = np.random.default_rng(2)
    n = 400
    t = np.arange(n)
    a = np.tanh(np.sin(2 * np.pi * t / 50) + rng.normal(0, 0.05, n))
    b = -a + rng.normal(0, 0.02, n)  # deliberately the exact opposite of a
    corr = polarity_anti_correlation(a, b, window=60)
    mean_corr = np.nanmean(corr)
    print(f"true opposite-extremes pair: mean rolling polarity-correlation={mean_corr:.3f} (expect near -1)")
    assert mean_corr < -0.8, f"expected strong negative polarity correlation, got {mean_corr}"


def test_polarity_anti_correlation_low_for_independent_pair():
    rng = np.random.default_rng(3)
    n = 400
    a = np.tanh(rng.normal(0, 1, n))
    b = np.tanh(rng.normal(0, 1, n))
    corr = polarity_anti_correlation(a, b, window=60)
    mean_corr = np.nanmean(corr)
    print(f"independent pair: mean rolling polarity-correlation={mean_corr:.3f} (expect near 0)")
    assert abs(mean_corr) < 0.3, f"expected near-zero polarity correlation for independent series, got {mean_corr}"


def _make_df(close, gap_flag=None):
    n = len(close)
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    if gap_flag is None:
        gap_flag = np.zeros(n, dtype=int)
    return pd.DataFrame({"close": close, "gap_flag": gap_flag}, index=idx)


def test_screen_accepts_genuine_negative_hedge_cointegration():
    """Known stationary spread: log_a = -1.5 * log_b + OU-mean-reverting
    noise. Correlation of returns should be strongly negative AND the EG
    test should find cointegration with a negative fitted hedge ratio."""
    rng = np.random.default_rng(4)
    n = 800
    log_b = np.cumsum(rng.normal(0, 0.02, n))  # random walk leg
    ou_noise = np.zeros(n)
    for i in range(1, n):
        ou_noise[i] = 0.9 * ou_noise[i - 1] + rng.normal(0, 0.05)
    log_a = -1.5 * log_b + ou_noise  # stationary spread by construction
    close_a = np.exp(log_a) * 100
    close_b = np.exp(log_b) * 100
    df_a, df_b = _make_df(close_a), _make_df(close_b)

    result = screen_anti_correlated_pair(df_a, df_b, corr_threshold=-0.30)
    print(f"genuine negative-hedge synthetic pair: rho={result['rho']:.3f}, "
          f"candidate={result['candidate']}, coint_p={result.get('coint_pvalue')}, "
          f"hedge={result.get('hedge_ratio')}, neg_hedge={result.get('is_negative_hedge')}")
    assert result["candidate"], "expected the synthetic negative-hedge pair to pass the correlation screen"
    assert result["coint_pvalue"] < 0.05, \
        f"expected the genuinely cointegrated synthetic pair to reject the unit-root null, p={result.get('coint_pvalue')}"
    assert result["is_negative_hedge"], "expected a negative fitted hedge ratio for this construction"


def test_screen_rejects_anti_correlated_but_non_cointegrated_pair():
    """THE key guard this module exists for: two independent random walks
    with opposite drift can have strongly negative RETURN correlation
    (because one trends up, the other down) while having NO stable
    equilibrium at all -- coint() must correctly fail to reject the
    unit-root null here."""
    rng = np.random.default_rng(5)
    n = 800
    # IMPORTANT construction note, discovered while writing this test: naive
    # "opposite drift" does NOT work here, because Pearson correlation is
    # computed on DEMEANED returns -- a constant drift is entirely removed
    # by demeaning, so two series that merely trend in opposite directions
    # show ~0 return correlation, not negative (verified: an earlier draft
    # of this test used opposite constant drift and got rho=0.03, not
    # negative at all -- an actually informative near-miss, kept as the
    # reason this construction looks the way it does).
    #
    # The real "spurious negative correlation, no cointegration" case
    # (classic Granger-Newbold 1974 spurious-regression setup): two
    # INDEPENDENT random walks whose per-bar INNOVATIONS are correlated at
    # rho_shock (not -1, so no exact shared error-correction term exists),
    # each accumulated as its own random walk. Sample correlation of
    # returns matches rho_shock by construction; the cumulative sums are
    # each individually non-stationary and only cointegrated in the
    # degenerate case of perfectly-correlated innovations -- so at
    # rho_shock=-0.6 coint() should correctly find no cointegration.
    rho_shock = -0.6
    shock_a = rng.normal(0, 0.02, n)
    indep = rng.normal(0, 0.02, n)
    shock_b = rho_shock * shock_a + np.sqrt(1 - rho_shock ** 2) * indep
    log_a = np.cumsum(shock_a)
    log_b = np.cumsum(shock_b)
    close_a = np.exp(log_a) * 100
    close_b = np.exp(log_b) * 100
    df_a, df_b = _make_df(close_a), _make_df(close_b)

    result = screen_anti_correlated_pair(df_a, df_b, corr_threshold=-0.10)
    print(f"drift-only (non-cointegrated) synthetic pair: rho={result['rho']:.3f}, "
          f"candidate={result['candidate']}, coint_p={result.get('coint_pvalue')}")
    assert result["candidate"], \
        f"expected the strong opposite-drift construction to pass the correlation screen, rho={result['rho']}"
    assert result["coint_pvalue"] > 0.05, \
        (f"expected the non-cointegrated drift-only pair to FAIL to reject the unit-root "
         f"null (p > 0.05), got p={result.get('coint_pvalue')} -- a false positive here is "
         f"exactly the 'drifts apart forever' failure mode this module must guard against")


def test_causality_polarity_metrics_no_future_leakage():
    """Perturbing values strictly AFTER time t must not change the
    polarity value AT t, for all three metrics and for
    polarity_anti_correlation."""
    rng = np.random.default_rng(6)
    n = 300
    t_check = 150
    log_price = np.log(100 + np.cumsum(rng.normal(0, 0.3, n)))

    pol_before = zscore_tanh_polarity(log_price.copy(), window=60)
    perturbed = log_price.copy()
    perturbed[t_check + 1:] += 5.0  # large future shock, strictly after t_check
    pol_after = zscore_tanh_polarity(perturbed, window=60)
    assert np.isclose(pol_before[t_check], pol_after[t_check], equal_nan=True), \
        "zscore_tanh_polarity leaked future information"

    price = 100 + np.cumsum(rng.normal(0, 0.5, n))
    rank_before = percentile_rank_polarity(price.copy(), window=60)
    perturbed_price = price.copy()
    perturbed_price[t_check + 1:] += 1000.0
    rank_after = percentile_rank_polarity(perturbed_price, window=60)
    assert np.isclose(rank_before[t_check], rank_after[t_check], equal_nan=True), \
        "percentile_rank_polarity leaked future information"

    a = np.tanh(np.sin(2 * np.pi * np.arange(n) / 40))
    b = -a + rng.normal(0, 0.02, n)
    corr_before = polarity_anti_correlation(a.copy(), b.copy(), window=60)
    b_perturbed = b.copy()
    b_perturbed[t_check + 1:] = rng.normal(0, 1, n - t_check - 1)
    corr_after = polarity_anti_correlation(a, b_perturbed, window=60)
    assert np.isclose(corr_before[t_check], corr_after[t_check], equal_nan=True), \
        "polarity_anti_correlation leaked future information"

    print("causality check (all metrics): OK -- no future leakage at t=150")


if __name__ == "__main__":
    tests = [
        test_zscore_tanh_bounded_and_extremes,
        test_percentile_rank_bounded_and_extremes,
        test_eg_spread_zscore_polarity_passthrough,
        test_polarity_anti_correlation_high_for_true_opposite_pair,
        test_polarity_anti_correlation_low_for_independent_pair,
        test_screen_accepts_genuine_negative_hedge_cointegration,
        test_screen_rejects_anti_correlated_but_non_cointegrated_pair,
        test_causality_polarity_metrics_no_future_leakage,
    ]
    passed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"FAILED: {test.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} checks passed")
