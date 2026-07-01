"""
Synthetic verification of FilterFunnel/FilterFunnelStage (analysis.py),
added for the Phase 1 filter-ablation funnel work. Confirms: n_removed
arithmetic is correct, to_dataframe() produces the right shape/columns in
stage-recorded order, save() writes a real parquet file to
output/results/{tf_label}/filter_funnel.parquet and round-trips it exactly,
and save() on an empty funnel is a safe no-op (writes nothing).

Read-only with respect to real pipeline output — writes to a throwaway TF
label ("_verify_funnel_tf") under output/results/, then deletes that
directory afterward so it never pollutes a real run's results.
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from analysis import FilterFunnel, FilterFunnelStage, _output_dir

TF_LABEL = "_verify_funnel_tf"


def main():
    failures = []

    # --- n_removed arithmetic ---
    stage = FilterFunnelStage(stage="pearson_prefilter_pairs", n_before=100, n_after=37)
    if stage.n_removed != 63:
        failures.append(f"n_removed: expected 63, got {stage.n_removed}")

    # --- empty funnel save() is a safe no-op ---
    empty_funnel = FilterFunnel(TF_LABEL)
    empty_path = os.path.join(_output_dir(TF_LABEL), "filter_funnel.parquet")
    if os.path.exists(empty_path):
        os.remove(empty_path)
    empty_funnel.save()
    if os.path.exists(empty_path):
        failures.append("empty funnel save() wrote a file when it should have no-op'd")

    # --- recorded stages round-trip through to_dataframe()/save() ---
    funnel = FilterFunnel(TF_LABEL)
    funnel.record("adv_liquidity_symbols", 500, 480)
    funnel.record("pearson_prefilter_pairs", 480 * 479 // 2, 1200)
    funnel.record("eg_bh_fdr_pairs", 1200, 34)
    funnel.record("price_degeneracy_pairs", 34, 30)
    funnel.record("structural_exclusion_pairs", 30, 28)
    funnel.record("coint_frac_threshold_pairs", 28, 17)

    df = funnel.to_dataframe()
    expected_stages = [
        "adv_liquidity_symbols",
        "pearson_prefilter_pairs",
        "eg_bh_fdr_pairs",
        "price_degeneracy_pairs",
        "structural_exclusion_pairs",
        "coint_frac_threshold_pairs",
    ]
    if list(df["stage"]) != expected_stages:
        failures.append(f"stage order wrong: {list(df['stage'])}")
    if list(df["n_removed"]) != [20, 480 * 479 // 2 - 1200, 1166, 4, 2, 11]:
        failures.append(f"n_removed column wrong: {list(df['n_removed'])}")
    if set(df.columns) != {"tf_label", "stage", "n_before", "n_after", "n_removed"}:
        failures.append(f"unexpected columns: {set(df.columns)}")

    funnel.save()
    saved_path = os.path.join(_output_dir(TF_LABEL), "filter_funnel.parquet")
    if not os.path.exists(saved_path):
        failures.append(f"save() did not write {saved_path}")
    else:
        reloaded = pd.read_parquet(saved_path)
        if not reloaded.equals(df.reset_index(drop=True)):
            failures.append("reloaded parquet does not match in-memory dataframe")

    # Cleanup the throwaway TF directory so this test never pollutes real output.
    tf_dir = _output_dir(TF_LABEL)
    if os.path.isdir(tf_dir):
        shutil.rmtree(tf_dir)

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All FilterFunnel checks passed.")


if __name__ == "__main__":
    main()
