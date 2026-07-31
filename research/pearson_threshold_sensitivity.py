"""
research/pearson_threshold_sensitivity.py -- Ross's direct request (2026-07-21,
following the filter-relevance/"exogeneity" sweep): does loosening the Pearson
pre-filter threshold (Config.UNIVERSE.MIN_PEARSON_CORR, currently 0.40) recover
any additional confirmed pairs at 1h, or does it just add more multiple-testing
burden for zero gain? The prior sweep explicitly disclosed this as not done
("would require rerunning the whole 67,582-candidate correlation+EG scan --
too heavy for this pass").

Method: reuses REAL production code throughout (UniverseFilter, _eg_worker,
_benjamini_hochberg, CointScanner._build_log_price_map -- same pattern as
research/fdr_method_comparison.py and research/sector_restricted_fdr_rescan.py,
not a reimplementation). The correlation matrix is the expensive part and is
computed ONCE at the loosest threshold tested (0.30); tighter thresholds
(0.35, 0.40) are obtained by re-applying UniverseFilter.candidate_pairs() to
the SAME matrix -- no redundant correlation computation. EG (_eg_worker) then
runs on the full candidate set admitted at 0.30 (a strict superset of 0.35
and 0.40's candidate sets), so every threshold's BH-FDR outcome can be
computed by subsetting ONE p-value population by which threshold's
correlation matrix would have admitted each pair -- rather than re-running EG
per threshold.

Honest scope note: this is 1h only (the timeframe under direct investigation
for the pair-set collapse), not all 12 timeframes -- a full 12-TF x 3-threshold
sweep would be substantially heavier and wasn't requested. Real, complete
computation for 1h -- no shortcuts, no subsampling of candidates.

Output:
  output/research/pearson_threshold_sensitivity.parquet -- per-candidate row
    (symbol_a, symbol_b, pearson_corr, eg pvalue, which thresholds admit it,
    confirmed_at_{0.30,0.35,0.40})
  output/research/pearson_threshold_sensitivity_summary.parquet -- one row per
    threshold: n_candidates, n_raw_significant, n_fdr_confirmed
  latest_run_pearson_threshold_sensitivity.log

Usage:
    python research/pearson_threshold_sensitivity.py
"""
import logging
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from data import DataAligner
from analysis import UniverseFilter, _eg_worker, _benjamini_hochberg, CointScanner

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE_DIR = os.path.join(_ROOT, "output", "cache")
_OUT_DIR = os.path.join(_ROOT, "output", "research")
TF_LABEL = "1h"
TF_SUFFIX = "1hr"

# Loosest threshold tested (superset), plus the two tighter cuts to compare
# against, including the current production value (0.40).
THRESHOLDS = [0.30, 0.35, 0.40]

log = logging.getLogger("pearson_threshold_sensitivity")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_pearson_threshold_sensitivity.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def load_full_universe(suffix: str = TF_SUFFIX):
    all_files = [f for f in os.listdir(_CACHE_DIR) if f.endswith(f"_{suffix}.parquet")]
    symbols = sorted(f[: -len(f"_{suffix}.parquet")] for f in all_files)
    tf_data_raw = {}
    for sym in symbols:
        path = os.path.join(_CACHE_DIR, f"{sym}_{suffix}.parquet")
        try:
            df = pd.read_parquet(path)
            if df is not None and not df.empty and "close" in df.columns:
                tf_data_raw[sym] = df
        except Exception:
            continue
    return tf_data_raw


def main():
    _setup_logging()
    t0 = time.time()
    log.info("=== pearson_threshold_sensitivity.py: does loosening the Pearson pre-filter "
              "recover confirmed pairs at 1h, or just add multiple-testing burden? ===")

    tf_data_raw = load_full_universe()
    log.info("Loaded %d symbols with usable %s cache", len(tf_data_raw), TF_LABEL)

    log.info("Aligning via real production DataAligner.align_universe()...")
    aligned = DataAligner.align_universe(
        {f"{sym}_{TF_LABEL}": df for sym, df in tf_data_raw.items()}, TF_LABEL
    )
    log.info("Aligned: %d symbols", len(aligned))

    asset_class_map = {sym: "equity" for sym in aligned}
    loosest = min(THRESHOLDS)
    log.info("Computing correlation matrices ONCE at the loosest threshold (%.2f)...", loosest)
    uf_result = UniverseFilter.run(
        aligned, asset_class_map, threshold=loosest, tf_label=TF_LABEL, return_matrices=True,
    )
    candidates_loosest, retained_symbols, returns, corr, sym_order = uf_result
    log.info("Candidates at threshold %.2f: %d", loosest, len(candidates_loosest))

    # Re-threshold the SAME matrix for the tighter cuts -- no recomputation.
    candidates_by_threshold = {loosest: candidates_loosest}
    for thr in THRESHOLDS:
        if thr == loosest:
            continue
        candidates_by_threshold[thr] = UniverseFilter.candidate_pairs(
            corr, sym_order, thr, asset_class_map
        )
        log.info("Candidates at threshold %.2f: %d", thr, len(candidates_by_threshold[thr]))

    # Run EG on the full (loosest-threshold) candidate population once --
    # every tighter threshold's candidate set is a strict subset of this one
    # (re-applying a higher |rho| cutoff to the same correlation matrix can
    # only ever remove candidates, never add new ones), verified below before
    # trusting the subsetting logic.
    key_sets = {thr: {(p["symbol_a"], p["symbol_b"]) for p in candidates_by_threshold[thr]}
                for thr in THRESHOLDS}
    for thr in THRESHOLDS:
        if thr == loosest:
            continue
        extra = key_sets[thr] - key_sets[loosest]
        if extra:
            raise RuntimeError(
                f"Subset invariant violated: {len(extra)} candidates at threshold {thr} "
                f"are NOT in the loosest-threshold ({loosest}) candidate set -- re-thresholding "
                f"logic is wrong, aborting rather than reporting an invalid comparison."
            )
    log.info("Verified: every tighter threshold's candidate set is a strict subset of the "
              "loosest threshold's -- safe to run EG once and subset the results.")

    log.info("Running real EG test (_eg_worker) on all %d candidates at threshold %.2f "
              "(workers=12)...", len(candidates_loosest), loosest)
    log_prices = CointScanner._build_log_price_map(aligned, retained_symbols)
    tasks = []
    for p in candidates_loosest:
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
    log.info("EG complete in %.1fs", time.time() - t_eg)

    ok = [r for r in results if r.get("ok")]
    log.info("EG usable results: %d/%d", len(ok), len(tasks))
    df = pd.DataFrame(ok)
    df["pair_key"] = list(zip(df["symbol_a"], df["symbol_b"]))
    # Attach each candidate's own Pearson correlation for reference.
    corr_lookup = {(p["symbol_a"], p["symbol_b"]): p["pearson_corr"] for p in candidates_loosest}
    df["pearson_corr"] = df["pair_key"].map(corr_lookup)

    alpha = Config.STATS.FDR_ALPHA
    summary_rows = []
    log.info("")
    log.info("=== Threshold sensitivity summary (alpha=%.2f) ===", alpha)
    for thr in sorted(THRESHOLDS, reverse=True):
        subset_mask = df["pair_key"].isin(key_sets[thr])
        sub = df[subset_mask].copy()
        m = len(sub)
        pvals = sub["pvalue"].to_numpy()
        n_raw = int(np.sum(pvals < 0.05))
        if m > 0:
            rejected, _adj = _benjamini_hochberg(pvals, alpha)
            n_fdr = int(rejected.sum())
            df.loc[subset_mask, f"confirmed_at_{thr}"] = rejected
        else:
            n_fdr = 0
        summary_rows.append({
            "threshold": thr, "n_candidates": m, "n_raw_significant": n_raw,
            "n_fdr_confirmed": n_fdr,
        })
        log.info("  threshold=%.2f: m=%d candidates, raw p<0.05=%d, FDR-adjusted<0.05=%d",
                  thr, m, n_raw, n_fdr)

    n_additional_035 = len(key_sets[0.35]) - len(key_sets[0.40])
    n_additional_030 = len(key_sets[0.30]) - len(key_sets[0.35])
    log.info("")
    log.info("Additional candidates admitted at 0.35 vs 0.40: %d", n_additional_035)
    log.info("Additional candidates admitted at 0.30 vs 0.35: %d", n_additional_030)

    os.makedirs(_OUT_DIR, exist_ok=True)
    df.drop(columns=["pair_key"]).to_parquet(
        os.path.join(_OUT_DIR, "pearson_threshold_sensitivity.parquet"), index=False
    )
    pd.DataFrame(summary_rows).to_parquet(
        os.path.join(_OUT_DIR, "pearson_threshold_sensitivity_summary.parquet"), index=False
    )
    log.info("Saved -> output/research/pearson_threshold_sensitivity{,_summary}.parquet")

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("pearson_threshold_sensitivity.py complete (%.1f min)", runtime)


if __name__ == "__main__":
    main()
