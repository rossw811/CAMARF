"""
Synthetic verification for BUG-D95 (found 2026-07-21 during the filter-
relevance sweep, fixed same day): AnalysisPipeline._save_tf_results()
persisted `all_candidates.parquet` and `spread_series_*.parquet` (both keyed
off `pairs`, the EG+FDR+price-degeneracy survivor set) only when
`discovered_pairs` (the FINAL post-coint_frac/post-structural set) was also
non-empty. A timeframe whose funnel collapses to ZERO final confirmed pairs
-- 1h's real, confirmed case: 2 pairs in `pairs`, both cut by coint_frac/
structural, 0 in `discovered_pairs` -- persisted NOTHING, defeating
research/filter_ablation.py's whole purpose for exactly that case.

This test constructs a scenario matching 1h's real shape: 2 pairs that both
FAIL the coint_frac threshold (so discovered_pairs is empty), with real
per_bar_by_pair data for both. Confirms that after the fix,
all_candidates.parquet and both pairs' spread_series files are written even
though pairs.parquet itself is correctly NOT written (discovered_pairs is
genuinely empty, that part of the behavior is unchanged and correct).

Uses the same safe-test-directory + manifest_path_override conventions as
debug/_verify_save_tf_results_return.py (BUG-D63) -- never touches the real
production manifest or output/results/ directories.
"""
import os
import sys
import shutil

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import AnalysisPipeline, PairResult, _output_dir

_TF = "__TEST_D95__"


def _make_pair(symbol_a, symbol_b, coint_frac=0.30):
    """Deliberately BELOW MIN_COINT_FRAC (0.70) with a decaying half-life
    trend slope and no secondary-evidence override signals -- guaranteed to
    be cut by the coint_frac filter, landing in `pairs` but NOT
    `discovered_pairs`, matching 1h's real PNC/ZION and SPY/VOO shape."""
    return PairResult(
        symbol_a=symbol_a, symbol_b=symbol_b,
        asset_class_a="equity", asset_class_b="equity",
        tf_label=_TF, is_cross_asset=False,
        pearson_corr=0.8, coint_pvalue_raw=0.001, coint_pvalue_adjusted=0.002,
        coint_fraction_rolling=coint_frac,
        hedge_ratio_ols=1.0, hedge_ratio_tls=1.0, hedge_ratio_kalman_mean=1.0,
        half_life_rolling=20.0, half_life_expanding=20.0, mean_reversion_speed=0.05,
        half_life_trend_slope=0.5, zivot_andrews_break=None, cusum_first_excursion=None,
        hurst_rs=0.4, hurst_dfa=0.4, hurst_divergence=0.0, passes_ml_gate=True,
        hurst_interpretation="mean_reverting",
        eigenport_pvalue=0.02, passes_eigenportfolio=True, n_factors_removed=1,
        confidence_tier="silver",
        n_bars=500, n_overlap=500,
        source_a="yfinance", source_b="yfinance",
    )


def _make_per_bar(n=100):
    idx = pd.date_range("2020-01-01", periods=n, freq="1h")
    return {
        "index": idx,
        "spread": np.random.default_rng(0).normal(0, 1, n),
        "z_rolling": np.random.default_rng(1).normal(0, 1, n),
        "z_expanding": np.random.default_rng(2).normal(0, 1, n),
        "half_life_rolling_series": np.full(n, 20.0),
        "gap_flag_a": np.zeros(n, dtype=int),
        "gap_flag_b": np.zeros(n, dtype=int),
    }


def main():
    pairs_in = [_make_pair("PNCTEST", "ZIONTEST"), _make_pair("SPYTEST", "VOOTEST")]
    per_bar_by_pair = {
        ("PNCTEST", "ZIONTEST"): _make_per_bar(),
        ("SPYTEST", "VOOTEST"): _make_per_bar(),
    }

    out_dir = _output_dir(_TF)
    test_manifest_path = os.path.join(out_dir, "confirmed_pairs_manifest.json")

    try:
        returned = AnalysisPipeline._save_tf_results(
            _TF, pairs_in, [], [], [], {}, per_bar_by_pair,
            manifest_path_override=test_manifest_path,
        )

        print(f"discovered_pairs returned: {len(returned)} (expected 0 -- both pairs "
              f"fail coint_frac<0.70 with no secondary-evidence override)")
        assert len(returned) == 0, (
            f"Test setup failed: expected both synthetic pairs to be cut by the "
            f"coint_frac filter, got {len(returned)} surviving"
        )

        pairs_parquet_path = os.path.join(out_dir, "pairs.parquet")
        all_candidates_path = os.path.join(out_dir, "all_candidates.parquet")
        spread_series_paths = [
            os.path.join(out_dir, f"spread_series_{a}_{b}.parquet")
            for a, b in [("PNCTEST", "ZIONTEST"), ("SPYTEST", "VOOTEST")]
        ]

        pairs_parquet_exists = os.path.exists(pairs_parquet_path)
        all_candidates_exists = os.path.exists(all_candidates_path)
        spread_series_exist = [os.path.exists(p) for p in spread_series_paths]

        print(f"pairs.parquet exists: {pairs_parquet_exists} (expected False -- "
              f"discovered_pairs is genuinely empty, this part is correctly unchanged)")
        print(f"all_candidates.parquet exists: {all_candidates_exists} (expected True -- "
              f"THE FIX: this must persist even though discovered_pairs is empty)")
        print(f"spread_series_*.parquet exist: {spread_series_exist} (expected [True, True] -- "
              f"THE FIX: same reasoning)")

        failures = []
        if pairs_parquet_exists:
            failures.append("pairs.parquet should NOT exist (discovered_pairs is genuinely empty)")
        if not all_candidates_exists:
            failures.append("BUG-D95 NOT FIXED: all_candidates.parquet was not persisted")
        if not all(spread_series_exist):
            failures.append("BUG-D95 NOT FIXED: spread_series_*.parquet was not persisted for all pairs")

        if all_candidates_exists:
            cdf = pd.read_parquet(all_candidates_path)
            candidate_keys = set(zip(cdf["symbol_a"], cdf["symbol_b"]))
            expected_keys = {("PNCTEST", "ZIONTEST"), ("SPYTEST", "VOOTEST")}
            print(f"all_candidates.parquet contains: {candidate_keys}")
            if candidate_keys != expected_keys:
                failures.append(f"all_candidates.parquet has wrong contents: {candidate_keys}")

    finally:
        shutil.rmtree(out_dir, ignore_errors=True)

    if failures:
        print(f"\nFAILED: {failures}")
        sys.exit(1)
    print("\nPASS: BUG-D95 fixed -- all_candidates.parquet and spread_series_*.parquet "
          "persist even when discovered_pairs is empty, while pairs.parquet correctly "
          "still does not.")


if __name__ == "__main__":
    main()
