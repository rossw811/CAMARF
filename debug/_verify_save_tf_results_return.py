"""
Synthetic verification for the 2026-06-23 fix to AnalysisPipeline._save_tf_results:
it now returns discovered_pairs (the actually-persisted, post coint_frac-filter
set) instead of None, and _run_one_tf reassigns pair_results to that return
value before returning to AnalysisPipeline.run(). Before this fix, pairs
excluded by the coint_frac >= MIN_COINT_FRAC gate (with no secondary-evidence
override) still ended up in results.pairs_by_tf / latest_run_analysis.log's
"confirmed_pairs" section despite never being written to pairs.parquet, the
manifest, or spread_series — confirmed for real on the 07:51 run: 1h's
PNC/ZION and SPY/VOO were both printed as confirmed but neither was ever
persisted (no pairs.parquet, no manifest entry).

Writes only to a throwaway output/results/__TEST_SAVE__/ directory, deleted
at the end. Does not touch any real cache or results files — safe to run
while data.py/analysis.py are active against the real output tree.
"""
import os
import sys
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import AnalysisPipeline, PairResult, _output_dir

_TF = "__TEST_SAVE__"


def _make_pair(symbol_a, symbol_b, coint_frac, slope=-0.5, za=None, cusum=None):
    return PairResult(
        symbol_a=symbol_a, symbol_b=symbol_b,
        asset_class_a="equity", asset_class_b="equity",
        tf_label=_TF, is_cross_asset=False,
        pearson_corr=0.8, coint_pvalue_raw=0.01, coint_pvalue_adjusted=0.02,
        coint_fraction_rolling=coint_frac,
        hedge_ratio_ols=1.0, hedge_ratio_tls=1.0, hedge_ratio_kalman_mean=1.0,
        half_life_rolling=20.0, half_life_expanding=20.0, mean_reversion_speed=0.05,
        half_life_trend_slope=slope, zivot_andrews_break=za, cusum_first_excursion=cusum,
        hurst_rs=0.4, hurst_dfa=0.4, hurst_divergence=0.0, passes_ml_gate=True,
        hurst_interpretation="mean_reverting",
        eigenport_pvalue=0.02, passes_eigenportfolio=True, n_factors_removed=1,
        confidence_tier="silver",
        n_bars=500, n_overlap=500,
        source_a="yfinance", source_b="yfinance",
    )


def main():
    cases = [
        # (label, pair, expected_kept)
        ("clean pass (cf>=0.70)", _make_pair("AAA", "BBB", 0.95), True),
        ("clean fail, no override (cf<0.70, decaying slope)", _make_pair("CCC", "DDD", 0.30, slope=0.5), False),
        ("override-kept (cf<0.70, improving slope, no breaks)", _make_pair("EEE", "FFF", 0.40, slope=-0.1, za=None, cusum=None), True),
        ("nan coint_frac, exempt by design", _make_pair("GGG", "HHH", float("nan")), True),
    ]
    pairs_in = [c[1] for c in cases]

    returned = AnalysisPipeline._save_tf_results(
        _TF, pairs_in, [], [], [], {}, None
    )
    returned_keys = {(p.symbol_a, p.symbol_b) for p in returned}

    out_dir = _output_dir(_TF)
    on_disk_path = os.path.join(out_dir, "pairs.parquet")
    on_disk_keys = set()
    if os.path.exists(on_disk_path):
        import pandas as pd
        df = pd.read_parquet(on_disk_path)
        on_disk_keys = set(zip(df["symbol_a"], df["symbol_b"]))

    failures = []
    for label, pair, expected_kept in cases:
        key = (pair.symbol_a, pair.symbol_b)
        in_return = key in returned_keys
        on_disk = key in on_disk_keys
        ok = (in_return == expected_kept) and (on_disk == expected_kept)
        status = "OK" if ok else "MISMATCH"
        if not ok:
            failures.append(label)
        print(f"{status}  {label}: expected_kept={expected_kept} "
              f"returned={in_return} on_disk={on_disk}")

    # Core regression check: return value must equal what's on disk —
    # this is the actual bug (return value used to be None / the unfiltered
    # input, diverging from what pairs.parquet contains).
    consistent = returned_keys == on_disk_keys
    print(f"\nreturned set == on-disk set: {consistent}")
    if not consistent:
        failures.append("return value diverges from persisted pairs.parquet")

    shutil.rmtree(out_dir, ignore_errors=True)

    if failures:
        print(f"\nFAILED: {failures}")
        sys.exit(1)
    print("\nAll cases match expected behavior.")


if __name__ == "__main__":
    main()
