"""
Synthetic verification for the 2026-06-23 confirmed_pairs_manifest.json
pruning fix in AnalysisPipeline._save_tf_results: a TF's tag on a symbol is
now fully refreshed (removed then re-added) on every call, instead of only
ever being added. Confirmed for real: D/NEE@1m, CRWD/DDOG@1m, and SPY/VOO's
"1h" tag were all stale leftovers from a prior session/run, still present
in the manifest despite being excluded by today's (correct) coint_frac
filter — data_ibkr.py would have kept fetching deep history for them.

Backs up and restores the REAL confirmed_pairs_manifest.json around the
test (it mutates the real file in place — there's no override hook) and
uses fake symbols/TFs that can't collide with real entries. Run this with
no other process writing the manifest concurrently.
"""
import os
import sys
import json
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import AnalysisPipeline, PairResult, _output_dir

_TF_X = "__TEST_MANIFEST_X__"
_TF_Y = "__TEST_MANIFEST_Y__"
_MANIFEST_PATH = "output/results/confirmed_pairs_manifest.json"
_BACKUP_PATH = _MANIFEST_PATH + ".bak_verify"


def _make_pair(symbol_a, symbol_b, tf_label):
    return PairResult(
        symbol_a=symbol_a, symbol_b=symbol_b,
        asset_class_a="equity", asset_class_b="equity",
        tf_label=tf_label, is_cross_asset=False,
        pearson_corr=0.8, coint_pvalue_raw=0.01, coint_pvalue_adjusted=0.02,
        coint_fraction_rolling=0.95,
        hedge_ratio_ols=1.0, hedge_ratio_tls=1.0, hedge_ratio_kalman_mean=1.0,
        half_life_rolling=20.0, half_life_expanding=20.0, mean_reversion_speed=0.05,
        half_life_trend_slope=-0.1, zivot_andrews_break=None, cusum_first_excursion=None,
        hurst_rs=0.4, hurst_dfa=0.4, hurst_divergence=0.0, passes_ml_gate=True,
        hurst_interpretation="mean_reverting",
        eigenport_pvalue=0.02, passes_eigenportfolio=True, n_factors_removed=1,
        confidence_tier="silver",
        n_bars=500, n_overlap=500,
        source_a="yfinance", source_b="yfinance",
    )


def _manifest():
    with open(_MANIFEST_PATH) as f:
        return json.load(f)


def main():
    shutil.copy(_MANIFEST_PATH, _BACKUP_PATH)
    failures = []
    try:
        # Round 1: TF_X confirms ZZZ1/ZZZ2, TF_Y confirms ZZZ2/ZZZ3.
        AnalysisPipeline._save_tf_results(
            _TF_X, [_make_pair("ZZZ1", "ZZZ2", _TF_X)], [], [], [], {}, None
        )
        AnalysisPipeline._save_tf_results(
            _TF_Y, [_make_pair("ZZZ2", "ZZZ3", _TF_Y)], [], [], [], {}, None
        )
        m = _manifest()
        check1 = (
            m.get("ZZZ1", {}).get("tfs") == [_TF_X]
            and sorted(m.get("ZZZ2", {}).get("tfs", [])) == sorted([_TF_X, _TF_Y])
            and m.get("ZZZ3", {}).get("tfs") == [_TF_Y]
        )
        print(f"{'OK' if check1 else 'MISMATCH'}  round 1 (both TFs confirm): "
              f"ZZZ1={m.get('ZZZ1')}, ZZZ2={m.get('ZZZ2')}, ZZZ3={m.get('ZZZ3')}")
        if not check1:
            failures.append("round1")

        # Round 2: TF_X re-runs and finds NOTHING confirmed anymore (the
        # staleness scenario — e.g. coint_frac filter now excludes it).
        # TF_Y is untouched (simulates a scoped --timeframes run).
        AnalysisPipeline._save_tf_results(_TF_X, [], [], [], [], {}, None)
        m = _manifest()
        check2 = (
            "ZZZ1" not in m  # fully dropped — TF_X was its only TF
            and m.get("ZZZ2", {}).get("tfs") == [_TF_Y]  # TF_X tag removed, TF_Y kept
            and m.get("ZZZ3", {}).get("tfs") == [_TF_Y]  # untouched
        )
        print(f"{'OK' if check2 else 'MISMATCH'}  round 2 (TF_X goes empty, TF_Y untouched): "
              f"ZZZ1={m.get('ZZZ1')}, ZZZ2={m.get('ZZZ2')}, ZZZ3={m.get('ZZZ3')}")
        if not check2:
            failures.append("round2")
    finally:
        shutil.move(_BACKUP_PATH, _MANIFEST_PATH)
        for tf in (_TF_X, _TF_Y):
            shutil.rmtree(_output_dir(tf), ignore_errors=True)

    if failures:
        print(f"\nFAILED: {failures}")
        sys.exit(1)
    print("\nAll cases match expected behavior. Real manifest restored from backup.")


if __name__ == "__main__":
    main()
