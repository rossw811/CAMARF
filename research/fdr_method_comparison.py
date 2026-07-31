"""
research/fdr_method_comparison.py -- Ross's direct request (2026-07-16), after
the confirmed-pair-set bug sweep proved the current step-up BH-FDR procedure
is correctly implemented but mechanically sensitive to a supporting-chain gap
(Development.md, "Ross explicitly distrusted the 0-confirmed-pairs finding").
Compares 4 multiple-testing corrections on the SAME real, current, full-
universe raw EG p-values, to see whether an alternative correction recovers
the genuinely-real-but-moderate pairs (LNT/VTR etc., raw p~2e-4) that the
current procedure's rank-chain sensitivity excludes now that DD's
contamination-inflated p-values no longer prop up the chain.

Methods compared, honestly, no cherry-picking of which one "wins":
  1. Step-up BH (Benjamini-Hochberg 1995) -- CAMARF's own production method
     (analysis.py's _benjamini_hochberg, reused directly, not reimplemented).
  2. Benjamini-Yekutieli (2001) -- FDR control under ARBITRARY dependence,
     always at least as conservative as BH (research/bh_fdr_dependence_check.py's
     benjamini_yekutieli, reused directly).
  3. Two-stage adaptive BH (Benjamini-Krieger-Yekutieli 2006, "TSBH") --
     statsmodels' fdr_tsbh, a well-established, less conservative-than-plain-BH
     adaptive procedure that estimates the true-null proportion from a first
     BH pass before a second, adjusted pass.
  4. Fixed threshold (Bonferroni) -- the simplest possible fixed, non-rank-
     dependent cutoff (alpha/m for every p-value individually), included
     specifically because it does NOT require an unbroken rank chain the way
     step-up BH does -- the property under direct investigation.

Uses REAL production code for everything upstream of the correction itself
(UniverseFilter Pearson pre-filter, analysis.py's own _eg_worker for the EG
test, CointScanner._build_log_price_map for gap-aware log-price construction)
-- not a reimplementation. Runs on the FULL current cached 1h universe (not
a sample), to get the genuine, complete raw p-value population this
comparison needs to be decisive rather than illustrative.

Output:
  output/research/fdr_method_comparison_raw.parquet -- every candidate pair's
    raw p-value plus a boolean confirmed-by-{method} column per method
  output/research/fdr_method_comparison_summary.parquet -- survivor counts
    per method, and specifically whether each of the 8 known non-DD pairs
    (LNT/VTR, LNT/WELL, CMS/DUK, EG/WRB, HAL/NOV, MET/TMHC, PFG/STLD, UMBF/FHB)
    survives under each method
  latest_run_fdr_method_comparison.log
"""
import logging
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config
from data import DataAligner
from analysis import UniverseFilter, _eg_worker, _benjamini_hochberg, CointScanner
from bh_fdr_dependence_check import benjamini_yekutieli

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE_DIR = os.path.join(_ROOT, "output", "cache")
_OUT_DIR = os.path.join(_ROOT, "output", "research")
TF_LABEL = "1h"

# The 8 non-DD/non-contaminated pairs already confirmed (this session) to be
# genuinely, individually significant at raw p<0.001 on clean data -- the
# specific pairs this comparison is checking for recovery under each method.
KNOWN_NON_DD_PAIRS = [
    ("LNT", "VTR"), ("LNT", "WELL"), ("CMS", "DUK"), ("EG", "WRB"),
    ("HAL", "NOV"), ("MET", "TMHC"), ("PFG", "STLD"), ("UMBF", "FHB"),
]

log = logging.getLogger("fdr_method_comparison")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_fdr_method_comparison.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def apply_all_methods(pvals: np.ndarray, alpha: float = 0.05) -> dict:
    """Pure function -- applies all 4 corrections to a raw p-value array,
    returns {method_name: rejected_boolean_array}. Kept data-loading-free so
    debug/_verify_fdr_method_comparison.py can call it directly on synthetic
    arrays with known expected behavior."""
    bh_rejected, _ = _benjamini_hochberg(pvals, alpha)
    by_rejected, _ = benjamini_yekutieli(pvals, alpha)
    tsbh_rejected, _, _, _ = multipletests(pvals, alpha=alpha, method="fdr_tsbh")
    bonf_rejected, _, _, _ = multipletests(pvals, alpha=alpha, method="bonferroni")
    return {
        "step_up_bh": bh_rejected,
        "benjamini_yekutieli": by_rejected,
        "two_stage_tsbh": tsbh_rejected,
        "fixed_bonferroni": bonf_rejected,
    }


def load_full_universe(suffix: str = "1hr"):
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
    log.info("=== fdr_method_comparison.py: 4-method FDR comparison on the FULL current 1h universe ===")
    log.info("Ross's direct request after the BH-FDR bug sweep -- honest comparison, no cherry-picking.")

    tf_data_raw = load_full_universe()
    log.info("Loaded %d symbols with usable 1h cache", len(tf_data_raw))

    log.info("Aligning via real production DataAligner.align_universe()...")
    aligned = DataAligner.align_universe(
        {f"{sym}_{TF_LABEL}": df for sym, df in tf_data_raw.items()}, TF_LABEL
    )
    log.info("Aligned: %d symbols", len(aligned))

    log.info("Running real production UniverseFilter (Pearson pre-filter, threshold=%s)...",
              Config.UNIVERSE.MIN_PEARSON_CORR)
    asset_class_map = {sym: "equity" for sym in aligned}
    uf_result = UniverseFilter.run(
        aligned, asset_class_map, threshold=Config.UNIVERSE.MIN_PEARSON_CORR,
        tf_label=TF_LABEL, return_matrices=True,
    )
    candidates, retained_symbols = uf_result[0], uf_result[1]
    n_possible = len(aligned) * (len(aligned) - 1) // 2
    log.info("Pearson pre-filter: %d possible pairs -> %d candidates", n_possible, len(candidates))

    log.info("Running real EG test (_eg_worker, same code as production CointScanner.scan) "
              "on all %d candidates (workers=12)...", len(candidates))
    log_prices = CointScanner._build_log_price_map(aligned, retained_symbols)
    tasks, meta = [], []
    for p in candidates:
        lp_a = log_prices.get(p["symbol_a"])
        lp_b = log_prices.get(p["symbol_b"])
        if lp_a is None or lp_b is None:
            continue
        tasks.append((p["symbol_a"], p["symbol_b"], lp_a, lp_b, Config.ANALYSIS.EG_MAX_LAG, TF_LABEL))
        meta.append(p)

    t_eg = time.time()
    results = []
    with ProcessPoolExecutor(max_workers=12) as pool:
        for r in pool.map(_eg_worker, tasks, chunksize=50):
            results.append(r)
    log.info("EG complete in %.1fs", time.time() - t_eg)

    ok = [r for r in results if r.get("ok")]
    log.info("EG usable results: %d/%d", len(ok), len(tasks))

    df = pd.DataFrame(ok)
    pvals = df["pvalue"].to_numpy()
    alpha = Config.STATS.FDR_ALPHA

    rejections = apply_all_methods(pvals, alpha)
    for method, rej in rejections.items():
        df[f"confirmed_{method}"] = rej

    log.info("")
    log.info("=== Survivor counts by method (m=%d candidates tested, alpha=%.2f) ===", len(pvals), alpha)
    summary_rows = []
    known_pair_status = {f"{a}/{b}": {} for a, b in KNOWN_NON_DD_PAIRS}
    for method, rej in rejections.items():
        n_survive = int(rej.sum())
        log.info("  %-22s: %d/%d survive", method, n_survive, len(pvals))
        summary_rows.append({"method": method, "n_survive": n_survive, "m_tested": len(pvals)})
        for sym_a, sym_b in KNOWN_NON_DD_PAIRS:
            mask = ((df["symbol_a"] == sym_a) & (df["symbol_b"] == sym_b)) | \
                   ((df["symbol_a"] == sym_b) & (df["symbol_b"] == sym_a))
            if mask.any():
                idx = mask.idxmax()
                known_pair_status[f"{sym_a}/{sym_b}"][method] = bool(rej[df.index.get_loc(idx)])
                known_pair_status[f"{sym_a}/{sym_b}"]["raw_pvalue"] = float(df.loc[idx, "pvalue"])
            else:
                known_pair_status[f"{sym_a}/{sym_b}"][method] = None

    log.info("")
    log.info("=== Known non-DD pairs (previously individually significant, raw p<0.001) -- "
              "confirmed by which method? ===")
    for pair, status in known_pair_status.items():
        raw_p = status.get("raw_pvalue", "not in candidate pool this run")
        log.info("  %-12s raw_p=%s  %s", pair, raw_p,
                  {k: v for k, v in status.items() if k != "raw_pvalue"})

    os.makedirs(_OUT_DIR, exist_ok=True)
    df.to_parquet(os.path.join(_OUT_DIR, "fdr_method_comparison_raw.parquet"), index=False)
    pd.DataFrame(summary_rows).to_parquet(
        os.path.join(_OUT_DIR, "fdr_method_comparison_summary.parquet"), index=False
    )
    pd.DataFrame(known_pair_status).T.to_parquet(
        os.path.join(_OUT_DIR, "fdr_method_comparison_known_pairs.parquet")
    )
    log.info("Saved -> output/research/fdr_method_comparison_{raw,summary,known_pairs}.parquet")

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("fdr_method_comparison.py complete (%.1f min)", runtime)


if __name__ == "__main__":
    main()
