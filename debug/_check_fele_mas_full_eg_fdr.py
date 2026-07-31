"""
debug/_check_fele_mas_full_eg_fdr.py -- decisive final test closing out the
FELE/MAS root-cause investigation. Prior steps this session established:
  - FELE and MAS both survive the REAL production universe-build path
    (UniverseBuilder().build(connect=False, fetch=False)), both pass
    exclusion/frequency-validation, both are in the 1542-symbol aligned
    1h universe.
  - Production's own batch correlation matrix gives FELE/MAS corr=0.420184,
    bit-for-bit identical to the independent pairwise computation -- not an
    alignment/batch artifact.
  - FELE/MAS IS in UniverseFilter.candidate_pairs() at the production
    threshold (0.40) -- confirmed True.
  - Production's REAL candidate pool at threshold 0.40 is 67,525 pairs --
    almost 2x research/pearson_threshold_sensitivity.py's own narrower
    "every symbol with a _1hr.parquet cache file, all tagged 'equity'"
    universe (which never included crypto/forex/ETF/international-equity
    pairs, all of which can have mechanically near-perfect correlations).

Remaining, decisive question: does FELE/MAS's own EG p-value (independently
confirmed at 4.52e-7) survive BH-FDR correction across this REAL, full,
diverse 67,525-candidate pool -- or does the wider pool's more extreme
p-values (plausibly from crypto/forex pairs) push its RANK down enough to
fail, even though it did not fail against the narrower research-script pool?

Reuses REAL production code: UniverseBuilder, DataAligner.align_universe,
UniverseFilter.run/candidate_pairs, _eg_worker, _benjamini_hochberg,
CointScanner._build_log_price_map -- same pattern as every other script
this session. Deliberately reproduces the ADV-filter-OFF state (the actual
bug present when today's observed output/results/1hr/all_candidates.parquet
was generated) rather than the post-fix state, since the question is why
THAT SPECIFIC, ALREADY-OBSERVED absence happened.

Read-only. Never fetches. Writes only its own output files.
"""
import sys, os, logging, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fele_mas_full_eg_fdr")

from data import UniverseBuilder, DataStore, DataAligner
from analysis import Config, UniverseFilter, _eg_worker, _benjamini_hochberg, CointScanner

_OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
TF_LABEL = "1h"


def main():
    t0 = time.time()
    log.info("Building full universe (connect=False, fetch=False)...")
    universe = UniverseBuilder().build(connect=False, fetch=False)
    excl = getattr(universe, "exclusion_set", set()) or set()

    tf_data_raw = {}
    for sym, cls in universe.assets:
        if sym in excl:
            continue
        key = f"{sym}_{TF_LABEL}"
        if key not in universe.data or universe.data[key] is None:
            continue
        df = universe.data[key]
        if not DataStore.validate_frequency(sym, TF_LABEL, df):
            continue
        tf_data_raw[sym] = df
    log.info(f"tf_data_raw: {len(tf_data_raw)} assets (ADV filter deliberately NOT applied -- "
             f"reproducing the exact pre-fix state that generated today's observed all_candidates.parquet)")

    aligned = DataAligner.align_universe(
        {f"{sym}_{TF_LABEL}": df for sym, df in tf_data_raw.items()}, TF_LABEL
    )
    log.info(f"aligned: {len(aligned)} assets. FELE present: {'FELE' in aligned}  MAS present: {'MAS' in aligned}")

    asset_class_map = {sym: cls for sym, cls in universe.assets}
    threshold = Config.UNIVERSE.MIN_PEARSON_CORR
    pairs, retained, returns, corr_mat, sym_order = UniverseFilter.run(
        aligned, asset_class_map, threshold, TF_LABEL, return_matrices=True
    )
    log.info(f"candidate_pairs at threshold {threshold}: {len(pairs)}")

    log.info("Building log-price map and running EG on the FULL real candidate pool "
              f"({len(pairs)} pairs, workers=12)...")
    log_prices = CointScanner._build_log_price_map(aligned, retained)
    tasks = []
    for p in pairs:
        lp_a = log_prices.get(p["symbol_a"])
        lp_b = log_prices.get(p["symbol_b"])
        if lp_a is None or lp_b is None:
            continue
        tasks.append((p["symbol_a"], p["symbol_b"], lp_a, lp_b, Config.ANALYSIS.EG_MAX_LAG, TF_LABEL))

    t_eg = time.time()
    results = []
    with ProcessPoolExecutor(max_workers=12) as pool:
        for r in pool.map(_eg_worker, tasks, chunksize=100):
            results.append(r)
    log.info(f"EG complete in {(time.time()-t_eg)/60:.1f} min")

    ok = [r for r in results if r.get("ok")]
    log.info(f"EG usable results: {len(ok)}/{len(tasks)}")
    df = pd.DataFrame(ok)
    df["pair_key"] = list(zip(df["symbol_a"], df["symbol_b"]))

    alpha = Config.STATS.FDR_ALPHA
    pvals = df["pvalue"].to_numpy()
    rejected, adjusted = _benjamini_hochberg(pvals, alpha)
    df["fdr_rejected"] = rejected
    df["fdr_adjusted_pvalue"] = adjusted

    n_fdr = int(rejected.sum())
    log.info(f"=== Full production-pool BH-FDR (alpha={alpha}, m={len(ok)}): {n_fdr} confirmed ===")

    # Rank FELE/MAS's own p-value among the full pool
    sorted_idx = np.argsort(pvals)
    rank_of = {tuple(sorted(df.iloc[i]["pair_key"])): (rank + 1) for rank, i in enumerate(sorted_idx)}

    mask = df["pair_key"].apply(lambda k: set(k) == {"FELE", "MAS"})
    if mask.any():
        row = df.loc[mask].iloc[0]
        rank = rank_of[tuple(sorted(row["pair_key"]))]
        log.info(f"FELE/MAS: pvalue={row['pvalue']:.6e}  rank={rank}/{len(ok)}  "
                 f"fdr_adjusted_pvalue={row['fdr_adjusted_pvalue']:.6e}  "
                 f"fdr_rejected(confirmed)={bool(row['fdr_rejected'])}")
    else:
        log.warning("FELE/MAS not found in EG-usable results (lp_a/lp_b missing or EG failed for this pair)")

    # Show the top 10 most-significant pairs for context (are there crypto/forex pairs
    # far more extreme than FELE/MAS, pushing its rank down?)
    top10 = df.nsmallest(10, "pvalue")[["symbol_a", "symbol_b", "pvalue", "fdr_rejected"]]
    log.info("Top 10 most-significant pairs in the full production pool:")
    for _, r in top10.iterrows():
        log.info(f"  {r['symbol_a']}/{r['symbol_b']}: p={r['pvalue']:.3e}  confirmed={bool(r['fdr_rejected'])}")

    confirmed_pairs = df.loc[df["fdr_rejected"], ["symbol_a", "symbol_b", "pvalue", "fdr_adjusted_pvalue"]]
    log.info(f"All {n_fdr} BH-FDR-confirmed pairs:")
    for _, r in confirmed_pairs.iterrows():
        log.info(f"  {r['symbol_a']}/{r['symbol_b']}: p={r['pvalue']:.3e}  adj={r['fdr_adjusted_pvalue']:.3e}")

    os.makedirs(_OUT, exist_ok=True)
    df.drop(columns=["pair_key"]).to_parquet(
        os.path.join(_OUT, "fele_mas_full_eg_fdr_check.parquet"), index=False
    )
    log.info(f"Saved -> output/research/fele_mas_full_eg_fdr_check.parquet")
    log.info(f"Total runtime: {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
