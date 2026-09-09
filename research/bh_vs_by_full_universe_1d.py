"""
research/bh_vs_by_full_universe_1d.py -- the corrected-scale re-run
PAPER_MAGNITUDE.md §10 flagged as "the single most important item"
before §7.1's BH-vs-Benjamini-Yekutieli claim is scale-complete. Ross
approved building this 2026-09-08.

Distinct from bh_vs_by_full_universe.py (kept, not replaced): that
script draws a fresh N=300 correlation-derived sample at 1h. This script
instead reuses the ALREADY-COMPUTED, full-universe-scale Pearson
prefilter output (`output/research/full_universe_correlation_
prefilter_candidates_10y_chunks/`, 997,024 real candidate pairs at 1D,
10-year lookback, produced 2026-08-24 by full_universe_correlation_
prefilter.py against the corrected ~44,700-symbol universe loader) --
redoing that O(n^2) correlation step from scratch is the actual
intractable part the original script's docstring named, not the EG
testing itself. 1D, not 1h, is also the more representative choice for
"full universe scale" specifically: WRDS/CRSP (this project's
1D-primary source) covers far more of the merged universe than 1h
intraday ever can (IBKR's much smaller supplemental cache) -- same
reasoning pit_wfa_wrds_daily.py already established for the PIT-fold
work.

Sample-size disclosure, same honest-tractability convention as the
original script: testing all 997,024 candidates' real EG cointegration
(OLS + ADF per pair) is not a single-session-tractable job even chunked
-- SAMPLE_N below draws a large (default 30,000), reproducibly seeded
random sample FROM the real full-universe candidate pool, not a smaller
population. This is ~100x the original script's N=300, a genuine scale
improvement, not a redefinition of "full universe" to mean something
smaller than the paper claims.
"""
import glob
import os
import sys
import random
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from analysis import _eg_worker, _benjamini_hochberg, CointScanner
from research.bh_fdr_dependence_check import benjamini_yekutieli
from universe_loader import load_full_universe, align_to_common_calendar

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CHUNKS_DIR = os.path.join(_ROOT, "output", "research",
                            "full_universe_correlation_prefilter_candidates_10y_chunks")
_LOG_PATH = os.path.join(_ROOT, "latest_run_bh_vs_by_full_universe_1d.log")

SAMPLE_N = 30_000
SEED = 20260908
TF_LABEL = "1D"


def load_candidate_sample(n=SAMPLE_N, seed=SEED) -> pd.DataFrame:
    files = sorted(glob.glob(os.path.join(_CHUNKS_DIR, "*.parquet")))
    if not files:
        raise FileNotFoundError(f"No candidate chunks found at {_CHUNKS_DIR} -- run "
                                 f"full_universe_correlation_prefilter.py --tf 1D --lookback-years 10 first.")
    full = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    rng = random.Random(seed)
    idx = rng.sample(range(len(full)), min(n, len(full)))
    return full.iloc[sorted(idx)].reset_index(drop=True), len(full)


def main():
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s",
                         datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(_LOG_PATH, mode="w", encoding="utf-8")
    log = logging.getLogger("bh_vs_by_full_universe_1d")
    log.addHandler(fh)

    log.info(f"=== bh_vs_by_full_universe_1d.py: sampling {SAMPLE_N} real candidates from the "
             f"full-universe 10y/1D Pearson prefilter (997,024 total) ===")
    sample, n_total_candidates = load_candidate_sample()
    log.info(f"Sampled {len(sample)}/{n_total_candidates} real full-universe candidate pairs")

    symbols_needed = sorted(set(sample["symbol_a"]) | set(sample["symbol_b"]))
    log.info(f"Loading + aligning {len(symbols_needed)} symbols actually needed (not the full "
             f"~44,700-symbol universe -- avoids this project's own documented OOM risk on a "
             f"full-universe dense load)...")
    t0 = time.time()
    full_universe = load_full_universe(TF_LABEL, columns=["close"])
    raw = {sym: full_universe[sym] for sym in symbols_needed if sym in full_universe}
    # Known bug class in this project (pit_wfa_wrds_daily.py's own
    # load_universe_wrds_daily fix, 2026-09-03): Binance crypto symbols
    # carry tz-AWARE (UTC) indices while every other source is tz-naive --
    # comparing them raises TypeError, not a silent wrong answer. Same fix
    # applied here, at the single point every downstream consumer draws
    # from.
    for sym, df in raw.items():
        if df is not None and not df.empty and df.index.tz is not None:
            raw[sym] = df.tz_localize(None)
    log.info(f"  {len(raw)}/{len(symbols_needed)} symbols found in the merged universe cache "
             f"({time.time()-t0:.1f}s)")

    # align_to_common_calendar, NOT DataAligner.align_universe -- a real bug
    # this project already diagnosed and fixed once (universe_loader.py,
    # 2026-08-14): DataAligner.align_universe clips each symbol to its OWN
    # real-history length within the requested range (e.g. AA: 2,304 rows
    # from 2016; DOW: 1,698 rows from 2019 -- different lengths), but
    # _build_log_price_map/_eg_worker assume every symbol's log-price array
    # is the SAME length, positionally aligned. That mismatch doesn't crash
    # visibly -- _eg_worker's own try/except silently swallows the resulting
    # ValueError and counts the pair as "not ok," which is exactly what
    # this script's own smoke test found (5/200 usable results, not a
    # graceful insufficient_overlap rejection). align_to_common_calendar
    # reindexes every symbol onto ONE shared DatetimeIndex first, which is
    # what full_universe_eg_confirmation.py already uses for this same
    # full-universe-candidate scenario.
    aligned = align_to_common_calendar(raw, lookback_years=10)
    log.info(f"Aligned {len(aligned)} symbols to a common calendar")

    retained_symbols = set(aligned.keys())
    sample = sample[sample["symbol_a"].isin(retained_symbols) & sample["symbol_b"].isin(retained_symbols)]
    log.info(f"{len(sample)} candidate pairs have both legs alignable -- proceeding to real EG test")

    log_prices = CointScanner._build_log_price_map(aligned, retained_symbols)
    tasks = []
    for _, p in sample.iterrows():
        lp_a = log_prices.get(p["symbol_a"])
        lp_b = log_prices.get(p["symbol_b"])
        if lp_a is None or lp_b is None:
            continue
        tasks.append((p["symbol_a"], p["symbol_b"], lp_a, lp_b, Config.ANALYSIS.EG_MAX_LAG, TF_LABEL))

    log.info(f"Running real EG test (_eg_worker, same production code) on {len(tasks)} pairs, "
             f"capturing RAW p-values before any BH-FDR filtering...")
    t0 = time.time()
    from concurrent.futures import ProcessPoolExecutor
    results = []
    with ProcessPoolExecutor(max_workers=Config.RUNTIME.N_WORKERS) as pool:
        for i, r in enumerate(pool.map(_eg_worker, tasks, chunksize=25)):
            results.append(r)
            if (i + 1) % 5000 == 0:
                log.info(f"  {i+1}/{len(tasks)} EG tests complete ({time.time()-t0:.1f}s elapsed)")
    log.info(f"EG testing complete: {len(tasks)} pairs in {(time.time()-t0)/60:.1f} min")

    ok = [r for r in results if r.get("ok")]
    log.info(f"  {len(ok)}/{len(tasks)} usable results")

    df = pd.DataFrame(ok)
    pvals = df["pvalue"].to_numpy()
    alpha = Config.STATS.FDR_ALPHA

    n_raw_sig = int(np.sum(pvals < Config.ANALYSIS.EG_SIGNIFICANCE))
    bh_rejected, _ = _benjamini_hochberg(pvals, alpha)
    by_rejected, _ = benjamini_yekutieli(pvals, alpha)

    result = {
        "tf_label": TF_LABEL, "sample_n_pairs": len(pvals),
        "full_universe_candidate_pool": n_total_candidates,
        "n_symbols_involved": len(retained_symbols),
        "n_raw_significant_p_lt_05": n_raw_sig,
        "bh_confirmed": int(bh_rejected.sum()),
        "by_confirmed": int(by_rejected.sum()),
        "bh_minus_by": int(bh_rejected.sum()) - int(by_rejected.sum()),
    }
    log.info("\n=== Real BH vs. Benjamini-Yekutieli, full-universe-scale 1D sample ===")
    for k, v in result.items():
        log.info(f"  {k}: {v}")

    df.to_parquet(os.path.join(_ROOT, "output", "research", "bh_vs_by_full_universe_1d_raw.parquet"))
    pd.DataFrame([result]).to_parquet(
        os.path.join(_ROOT, "output", "research", "bh_vs_by_full_universe_1d_summary.parquet"))
    log.info("Saved: output/research/bh_vs_by_full_universe_1d_raw.parquet")
    log.info("Saved: output/research/bh_vs_by_full_universe_1d_summary.parquet")


if __name__ == "__main__":
    main()
