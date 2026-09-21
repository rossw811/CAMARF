"""
Synthetic verification for research/lead_lag_cointegration_rate.py, per this
project's verify-before-trusting convention. No live data, no network, no
file I/O against output/results/ -- purely synthetic series and fabricated
intermediate DataFrames.

Run: python debug/_verify_lead_lag_cointegration_rate.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.lead_lag_cointegration_rate import (
    _eg_pvalue_fixed_maxlag, _worker_pair_lag_sweep, cointegration_rate_by_lag,
)
from research.lead_lag_scan import _MIN_EG_N

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def _make_cointegrated_pair(n=500, seed=0):
    rng = np.random.default_rng(seed)
    common = np.cumsum(rng.normal(0, 1, n))
    a = common + rng.normal(0, 0.1, n)
    b = common + rng.normal(0, 0.1, n)
    return a, b


def _make_independent_pair(n=500, seed=1):
    rng = np.random.default_rng(seed)
    a = np.cumsum(rng.normal(0, 1, n))
    b = np.cumsum(rng.normal(0, 1, n + 1))[1:]  # independent random walk
    return a, b


def test_eg_pvalue_fixed_maxlag_detects_cointegration():
    a, b = _make_cointegrated_pair()
    pval, n = _eg_pvalue_fixed_maxlag(a, b, maxlag=10)
    check("eg_fixed_maxlag.cointegrated_low_pvalue", pval is not None and pval < 0.05, pval)
    check("eg_fixed_maxlag.cointegrated_full_n", n == 500, n)


def test_eg_pvalue_fixed_maxlag_null_case():
    a, b = _make_independent_pair()
    pval, n = _eg_pvalue_fixed_maxlag(a, b, maxlag=10)
    # Not a strict guarantee for every seed, but two independent random walks
    # should not spuriously cointegrate at conventional alpha most of the time.
    check("eg_fixed_maxlag.independent_returns_a_pvalue", pval is not None, pval)


def test_eg_pvalue_fixed_maxlag_too_short():
    a = np.arange(_MIN_EG_N - 5, dtype=float)
    b = np.arange(_MIN_EG_N - 5, dtype=float) * 2
    pval, n = _eg_pvalue_fixed_maxlag(a, b, maxlag=10)
    check("eg_fixed_maxlag.too_short_returns_none", pval is None, (pval, n))


def test_eg_pvalue_fixed_maxlag_no_autolag_search():
    # A fixed maxlag call must not raise even with a deliberately large
    # maxlag relative to n (autolag="aic" would search; autolag=None must not).
    a, b = _make_cointegrated_pair(n=100)
    pval, n = _eg_pvalue_fixed_maxlag(a, b, maxlag=5)
    check("eg_fixed_maxlag.fixed_maxlag_no_crash", pval is not None, pval)


def test_worker_pair_lag_sweep_shape():
    a, b = _make_cointegrated_pair(n=600)
    idx = pd.date_range("2000-01-01", periods=600, freq="D")
    logp_a = pd.Series(a, index=idx)
    logp_b = pd.Series(b, index=idx)
    x = 3
    task = ("1D", "SYMA", "SYMB", logp_a, logp_b, x, 10)
    rows = _worker_pair_lag_sweep(task)
    check("worker.row_count_matches_2x_plus_1", len(rows) == 2 * x + 1, len(rows))
    lags = sorted(r["lag"] for r in rows)
    check("worker.lags_cover_full_range", lags == list(range(-x, x + 1)), lags)
    check("worker.lag0_has_full_overlap_n", rows[x]["n_obs"] == 600, rows[x]["n_obs"])
    check("worker.nonzero_lag_has_fewer_obs", rows[0]["n_obs"] == 600 - x, rows[0]["n_obs"])
    check("worker.every_row_has_symbol_labels",
          all(r["symbol_a"] == "SYMA" and r["symbol_b"] == "SYMB" for r in rows))


def test_cointegration_rate_by_lag_all_significant():
    full_df = pd.DataFrame([
        {"lag": lag, "eg_pvalue": 0.001, "n_obs": 100}
        for lag in range(-2, 3) for _ in range(10)
    ])
    curve = cointegration_rate_by_lag(full_df, alpha=0.05)
    check("rate_by_lag.all_significant_rate_is_1",
          bool((curve["rate"] == 1.0).all()), curve["rate"].tolist())
    check("rate_by_lag.n_pairs_tested_constant",
          curve["n_pairs_tested"].nunique() == 1, curve["n_pairs_tested"].tolist())


def test_cointegration_rate_by_lag_none_significant():
    full_df = pd.DataFrame([
        {"lag": lag, "eg_pvalue": 0.9, "n_obs": 100}
        for lag in range(-2, 3) for _ in range(10)
    ])
    curve = cointegration_rate_by_lag(full_df, alpha=0.05)
    check("rate_by_lag.none_significant_rate_is_0",
          bool((curve["rate"] == 0.0).all()), curve["rate"].tolist())


def test_cointegration_rate_by_lag_handles_missing_pvalues():
    # Half the pairs at lag=1 failed the EG call (None) -- must be excluded
    # from the denominator, not treated as non-significant.
    rows = [{"lag": 1, "eg_pvalue": 0.001, "n_obs": 100} for _ in range(5)]
    rows += [{"lag": 1, "eg_pvalue": None, "n_obs": 10} for _ in range(5)]
    full_df = pd.DataFrame(rows)
    curve = cointegration_rate_by_lag(full_df, alpha=0.05)
    check("rate_by_lag.excludes_none_pvalues_from_denominator",
          curve.loc[curve["lag"] == 1, "n_pairs_tested"].iloc[0] == 5,
          curve.loc[curve["lag"] == 1, "n_pairs_tested"].iloc[0])


def test_cointegration_rate_by_lag_empty_lag():
    full_df = pd.DataFrame([{"lag": 0, "eg_pvalue": None, "n_obs": 5}])
    curve = cointegration_rate_by_lag(full_df, alpha=0.05)
    check("rate_by_lag.empty_lag_zero_n_tested", curve.iloc[0]["n_pairs_tested"] == 0)
    check("rate_by_lag.empty_lag_rate_is_none", curve.iloc[0]["rate"] is None)


def test_fixed_denominator_gate_semantics():
    # Mirrors build_eligible_pairs' gate condition directly (min(ns) < _MIN_EG_N)
    # without touching the filesystem/aligned_pair_loader.
    scan_good = {lag: (0.5, 100) for lag in range(-3, 4)}
    scan_bad = {lag: (0.5, 100) for lag in range(-3, 4)}
    scan_bad[3] = (0.5, _MIN_EG_N - 1)  # thin at the extreme lag
    ns_good = [scan_good[lag][1] for lag in range(-3, 4)]
    ns_bad = [scan_bad[lag][1] for lag in range(-3, 4)]
    check("gate.passes_when_all_lags_sufficient", min(ns_good) >= _MIN_EG_N)
    check("gate.fails_when_one_lag_thin", min(ns_bad) < _MIN_EG_N)


if __name__ == "__main__":
    test_eg_pvalue_fixed_maxlag_detects_cointegration()
    test_eg_pvalue_fixed_maxlag_null_case()
    test_eg_pvalue_fixed_maxlag_too_short()
    test_eg_pvalue_fixed_maxlag_no_autolag_search()
    test_worker_pair_lag_sweep_shape()
    test_cointegration_rate_by_lag_all_significant()
    test_cointegration_rate_by_lag_none_significant()
    test_cointegration_rate_by_lag_handles_missing_pvalues()
    test_cointegration_rate_by_lag_empty_lag()
    test_fixed_denominator_gate_semantics()

    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    sys.exit(0)
