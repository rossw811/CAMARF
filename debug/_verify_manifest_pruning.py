"""
Synthetic verification for the 2026-06-23 confirmed_pairs_manifest.json
pruning fix in AnalysisPipeline._save_tf_results: a TF's tag on a symbol is
now fully refreshed (removed then re-added) on every call, instead of only
ever being added. Confirmed for real: D/NEE@1m, CRWD/DDOG@1m, and SPY/VOO's
"1h" tag were all stale leftovers from a prior session/run, still present
in the manifest despite being excluded by today's (correct) coint_frac
filter — data_ibkr.py would have kept fetching deep history for them.

UPDATE 2026-07-13 (BUG-D63): previously mutated the REAL manifest in place
and restored it from a backup in a `finally` block, because
_save_tf_results had no override hook at all. That per-script backup/
restore pattern is exactly what didn't generalize when a DIFFERENT script
(_verify_save_tf_results_return.py) touched the same function without it —
this file's own approach was never wrong, it just couldn't be relied on to
protect every future caller. Now uses manifest_path_override (added to
_save_tf_results this same session) pointing at a throwaway fixture path
instead — the real manifest is never opened, so there is nothing to back
up or restore.
"""
import os
import sys
import json
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import AnalysisPipeline, PairResult, _output_dir

_TF_X = "__TEST_MANIFEST_X__"
_TF_Y = "__TEST_MANIFEST_Y__"
_MANIFEST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "output", "results", "__TEST_MANIFEST_X__", "confirmed_pairs_manifest.json",
)


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


_REAL_MANIFEST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "output", "results", "confirmed_pairs_manifest.json",
)


def _manifest():
    with open(_MANIFEST_PATH) as f:
        return json.load(f)


def _real_manifest_snapshot():
    if not os.path.exists(_REAL_MANIFEST_PATH):
        return False, None
    with open(_REAL_MANIFEST_PATH, "rb") as f:
        return True, f.read()


def main():
    real_before = _real_manifest_snapshot()
    failures = []
    try:
        # Round 1: TF_X confirms ZZZ1/ZZZ2, TF_Y confirms ZZZ2/ZZZ3.
        AnalysisPipeline._save_tf_results(
            _TF_X, [_make_pair("ZZZ1", "ZZZ2", _TF_X)], [], [], [], {}, None,
            manifest_path_override=_MANIFEST_PATH,
        )
        AnalysisPipeline._save_tf_results(
            _TF_Y, [_make_pair("ZZZ2", "ZZZ3", _TF_Y)], [], [], [], {}, None,
            manifest_path_override=_MANIFEST_PATH,
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
        AnalysisPipeline._save_tf_results(
            _TF_X, [], [], [], [], {}, None,
            manifest_path_override=_MANIFEST_PATH,
        )
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

        real_after = _real_manifest_snapshot()
        real_untouched = real_before == real_after
        print(f"real production manifest untouched: {real_untouched}")
        if not real_untouched:
            failures.append(
                "REAL production confirmed_pairs_manifest.json was modified"
            )
    finally:
        for tf in (_TF_X, _TF_Y):
            shutil.rmtree(_output_dir(tf), ignore_errors=True)

    if failures:
        print(f"\nFAILED: {failures}")
        sys.exit(1)
    print("\nAll cases match expected behavior. Real production manifest was never touched.")


if __name__ == "__main__":
    main()
