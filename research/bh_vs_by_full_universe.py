"""
research/bh_vs_by_full_universe.py -- completes the BH-vs-Benjamini-Yekutieli
comparison that research/bh_fdr_dependence_check.py could not finish, because
the only persisted candidate file (output/results/1hr/all_candidates.parquet)
already contains only BH-FDR-CONFIRMED pairs (post both raw-significance and
BH-FDR filtering) -- both corrections trivially "pass" 100% of an
already-filtered set, so that file cannot show where a dependence-robust
threshold would actually bite.

This script regenerates the REAL raw (pre-BH-FDR) EG p-values for a large,
honestly-disclosed real sample of the 1h candidate universe, reusing the
exact same production code path (UniverseFilter.build_returns_matrix +
UniverseFilter.correlation_matrix/candidate_pairs, and analysis.py's own
_eg_worker for the EG test itself, via DataAligner.align_universe for
alignment) -- not a reimplementation.

Sample size disclosure: the full production 1h candidate pool involves the
full ~1,566-symbol cached universe (potentially tens of thousands of
Pearson-surviving candidate pairs, per PAPER.md's own Filter-Ablation-funnel
figure of 70,251 pairs at a prior universe snapshot). Running DataAligner +
the full N^2 correlation matrix + EG-testing across all ~1,566 symbols in a
single-shot background task is not practical here. This script instead uses
a real, randomly-selected sample of cached 1h symbols (SAMPLE_N below,
seeded for reproducibility) -- large enough to produce a real, substantial
candidate-pair set after the same real Pearson pre-filter production uses,
while remaining tractable. This is a disclosed sampling limitation, not a
silent one.
"""
import os
import sys
import random

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from data import DataAligner
from analysis import UniverseFilter, _eg_worker, _benjamini_hochberg, CointScanner
from research.bh_fdr_dependence_check import benjamini_yekutieli

SAMPLE_N = 300
SEED = 20260713
TF_LABEL = "1h"


def load_sample_universe(n=SAMPLE_N, seed=SEED, force_include=("DD", "MIDD")):
    cache_dir = Config.DATA.CACHE_DIR
    all_files = [f for f in os.listdir(cache_dir) if f.endswith("_1hr.parquet")]
    symbols_all = sorted(f[: -len("_1hr.parquet")] for f in all_files)
    rng = random.Random(seed)
    forced = [s for s in force_include if s in symbols_all]
    remaining_pool = [s for s in symbols_all if s not in forced]
    sample = forced + rng.sample(remaining_pool, min(n - len(forced), len(remaining_pool)))

    tf_data_raw = {}
    for sym in sample:
        path = os.path.join(cache_dir, f"{sym}_1hr.parquet")
        try:
            df = pd.read_parquet(path)
            if df is not None and not df.empty and "close" in df.columns:
                tf_data_raw[sym] = df
        except Exception:
            continue
    return tf_data_raw, len(symbols_all)


def main():
    print(f"Loading a real sample of {SAMPLE_N} symbols (seed={SEED}, forcing DD/MIDD inclusion "
          f"for a decisive test after the pure-random draw happened to exclude both) "
          f"from the cached 1h universe...")
    tf_data_raw, n_universe_total = load_sample_universe()
    print(f"  Loaded {len(tf_data_raw)}/{SAMPLE_N} requested symbols with usable 1h cache "
          f"(full cached universe: {n_universe_total} symbols)")

    print("Aligning via real production DataAligner.align_universe()...")
    aligned = DataAligner.align_universe(
        {f"{sym}_{TF_LABEL}": df for sym, df in tf_data_raw.items()}, TF_LABEL
    )
    print(f"  Aligned: {len(aligned)} symbols")

    print("Running real production UniverseFilter (Pearson pre-filter, threshold="
          f"{Config.UNIVERSE.MIN_PEARSON_CORR})...")
    asset_class_map = {sym: "equity" for sym in aligned}  # placeholder tag only; not used by EG test itself
    _uf = UniverseFilter.run(
        aligned, asset_class_map, threshold=Config.UNIVERSE.MIN_PEARSON_CORR,
        tf_label=TF_LABEL, return_matrices=True,
    )
    candidates, retained_symbols = _uf[0], _uf[1]
    n_possible = len(aligned) * (len(aligned) - 1) // 2
    print(f"  Pearson pre-filter: {n_possible} possible pairs -> {len(candidates)} candidates")

    if not candidates:
        print("No candidates survived the Pearson pre-filter on this sample -- aborting.")
        return

    print(f"Running real EG test (_eg_worker, same code as production CointScanner.scan) "
          f"on all {len(candidates)} candidates, capturing RAW p-values before any BH-FDR filtering...")
    log_prices = CointScanner._build_log_price_map(aligned, retained_symbols)
    tasks = []
    meta = []
    for p in candidates:
        lp_a = log_prices.get(p["symbol_a"])
        lp_b = log_prices.get(p["symbol_b"])
        if lp_a is None or lp_b is None:
            continue
        tasks.append((p["symbol_a"], p["symbol_b"], lp_a, lp_b, Config.ANALYSIS.EG_MAX_LAG))
        meta.append(p)

    from concurrent.futures import ProcessPoolExecutor
    results = []
    with ProcessPoolExecutor(max_workers=12) as pool:
        for r in pool.map(_eg_worker, tasks, chunksize=25):
            results.append(r)

    ok = [r for r in results if r.get("ok")]
    print(f"  EG complete: {len(ok)}/{len(tasks)} usable results")

    df = pd.DataFrame(ok)
    df["dd_leg"] = (df.symbol_a == "DD") | (df.symbol_b == "DD")
    df["midd_leg"] = (df.symbol_a == "MIDD") | (df.symbol_b == "MIDD")

    pvals = df["pvalue"].to_numpy()
    alpha = Config.STATS.FDR_ALPHA

    n_raw_sig = int(np.sum(pvals < Config.ANALYSIS.EG_SIGNIFICANCE))
    bh_rejected, _ = _benjamini_hochberg(pvals, alpha)
    by_rejected, _ = benjamini_yekutieli(pvals, alpha)

    dd_mask = df["dd_leg"].to_numpy()
    midd_mask = df["midd_leg"].to_numpy()

    result = {
        "sample_n_symbols": len(aligned),
        "full_cached_universe_n_symbols": n_universe_total,
        "m_total_candidates": len(pvals),
        "n_raw_significant_p_lt_05": n_raw_sig,
        "bh_confirmed": int(bh_rejected.sum()),
        "by_confirmed": int(by_rejected.sum()),
        "bh_confirmed_dd_leg": int(bh_rejected[dd_mask].sum()) if dd_mask.any() else 0,
        "by_confirmed_dd_leg": int(by_rejected[dd_mask].sum()) if dd_mask.any() else 0,
        "n_dd_leg_candidates": int(dd_mask.sum()),
        "bh_confirmed_midd_leg": int(bh_rejected[midd_mask].sum()) if midd_mask.any() else 0,
        "by_confirmed_midd_leg": int(by_rejected[midd_mask].sum()) if midd_mask.any() else 0,
        "n_midd_leg_candidates": int(midd_mask.sum()),
    }
    print("\n=== Real BH vs. Benjamini-Yekutieli, full (unfiltered-by-significance) sampled 1h universe ===")
    for k, v in result.items():
        print(f"  {k}: {v}")

    df.to_parquet("output/research/bh_vs_by_full_universe_raw.parquet")
    pd.DataFrame([result]).to_parquet("output/research/bh_vs_by_full_universe_summary.parquet")
    print("\nSaved: output/research/bh_vs_by_full_universe_raw.parquet")
    print("Saved: output/research/bh_vs_by_full_universe_summary.parquet")


if __name__ == "__main__":
    main()
