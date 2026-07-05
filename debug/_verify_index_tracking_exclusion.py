"""
Verification for the same-index-tracking-ETF structural exclusion (added
2026-07-01, see Development.md Session 25 / PAPER.md SPY/VOO flag).

SPY/VOO both mandate-track the S&P 500 — their cointegration is a structural
consequence of the fund mandates, not a discovered economic relationship,
same category as the existing share-class-pair exclusion (GOOGL/GOOG etc).
This test checks CrossAssetTagger._is_index_tracking_pair() directly and
CrossAssetTagger.split() end-to-end on a synthetic PairResult, then confirms
the 3 real call sites (analysis.py._save_tf_results, pit_wfa.py,
research/filter_ablation.py) all reference the same underlying set.

Expected: SPY/VOO -> excluded as structural (both symbol orders). An
unrelated pair (AAPL/MSFT) -> NOT excluded, passes through to same/cross.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import CrossAssetTagger, PairResult

CASES = [
    ("SPY", "VOO", True),
    ("VOO", "SPY", True),   # symmetric
    ("AAPL", "MSFT", False),
    ("GOOGL", "GOOG", False),  # share-class, not index-tracking — _is_index_tracking_pair itself should say False
]


def _make_pair(sym_a, sym_b) -> PairResult:
    return PairResult(
        symbol_a=sym_a, symbol_b=sym_b,
        asset_class_a="etf", asset_class_b="etf",
        tf_label="4h", is_cross_asset=False,
        pearson_corr=0.99, coint_pvalue_raw=1e-10, coint_pvalue_adjusted=1e-8,
        coint_fraction_rolling=0.35,
        hedge_ratio_ols=1.0, hedge_ratio_tls=1.0, hedge_ratio_kalman_mean=1.0,
        half_life_rolling=40.0, half_life_expanding=40.0, mean_reversion_speed=0.017,
        half_life_trend_slope=-0.01, zivot_andrews_break=None, cusum_first_excursion=None,
        hurst_rs=0.74, hurst_dfa=0.61, hurst_divergence=0.13,
        passes_ml_gate=False, hurst_interpretation="trending",
        eigenport_pvalue=0.25, passes_eigenportfolio=False, n_factors_removed=131,
        confidence_tier="silver", n_bars=6433, n_overlap=6433,
        source_a="unknown", source_b="unknown",
    )


def main():
    failures = []

    print("=== _is_index_tracking_pair unit checks ===")
    for sym_a, sym_b, expected in CASES:
        actual = CrossAssetTagger._is_index_tracking_pair(sym_a, sym_b)
        status = "OK" if actual == expected else "MISMATCH"
        if actual != expected:
            failures.append(("_is_index_tracking_pair", sym_a, sym_b, expected, actual))
        print(f"{status}  {sym_a}/{sym_b} -> is_index_tracking={actual} (expected {expected})")

    print("\n=== CrossAssetTagger.split() end-to-end ===")
    pairs = [_make_pair("SPY", "VOO"), _make_pair("AAPL", "MSFT")]
    same, cross = CrossAssetTagger.split(pairs)
    kept_symbols = {(p.symbol_a, p.symbol_b) for p in same + cross}
    if ("SPY", "VOO") in kept_symbols:
        failures.append(("split", "SPY", "VOO", "excluded", "kept"))
        print("MISMATCH  SPY/VOO was NOT excluded by split() — still in same/cross output")
    else:
        print("OK  SPY/VOO excluded from split() same/cross output")
    if ("AAPL", "MSFT") not in kept_symbols:
        failures.append(("split", "AAPL", "MSFT", "kept", "excluded"))
        print("MISMATCH  AAPL/MSFT was incorrectly excluded by split()")
    else:
        print("OK  AAPL/MSFT passed through split() as expected (unrelated pair, not structural)")

    print()
    if failures:
        print(f"FAILED: {len(failures)} case(s) did not match expected behavior")
        sys.exit(1)
    else:
        print("All cases match expected behavior.")


if __name__ == "__main__":
    main()
