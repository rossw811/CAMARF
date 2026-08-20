"""
research/full_universe_eg_confirmation.py -- Thread P / pipeline cascade
stage 2: runs the EXISTING, fully-rigorous EG-cointegration + BH-FDR pipeline
(analysis.py::CointScanner.scan(), unmodified) against the 18,450 candidates
surviving the full-universe correlation pre-filter (research/full_universe_
correlation_prefilter.py, threshold=0.6, Ross's explicit choice, 2026-08-14).

Reuses CointScanner.scan() directly -- not reimplemented -- so this stage
gets the SAME rigor (both-direction EG regression, Benjamini-Hochberg FDR
correction, BiasAuditLog recording) as every other confirmed-pair set this
project has ever produced.

Same disclosed scope limitation as the pre-filter stage: input prices come
from universe_loader.py (raw cache reads), not the full DataCleaner/GapFlag-
aware alignment pipeline. gap_aware_returns's automatic elapsed-time gap
masking still applies at the correlation-matrix stage, but CointScanner's own
log-price construction reads directly from the aligned_data DataFrames passed
in here -- so this run inherits the same coarse-pass caveat already disclosed
for the correlation pre-filter.

REVISED 2026-08-14 (Ross: "build the proper dedup fix first and re run full
cascade. also fix the fact that like 14000 assets or whatever it was didn't
get tested. proceed on basis"). Two fixes applied here (see
universe_loader.py's align_to_common_calendar/filter_exact_correlation_
duplicates docstrings for the full, data-confirmed root-cause detail; see
full_universe_correlation_prefilter.py's header for the first run's honest
541-pair breakdown that motivated both):
  1. align_to_common_calendar() applied to aligned_data right after loading,
     same as the pre-filter stage -- fixes the real crash/misalignment root
     cause behind the first run's ~17,797/18,450 untested candidates.
  2. filter_exact_correlation_duplicates() applied to the concatenated
     candidate list before EG testing -- drops same-underlying-identity
     duplicate pairs (the general |pearson_corr|>=0.999999 signature) that
     accounted for 521/541 of the first run's raw "confirmed" pairs.
"""
import glob
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from analysis import CointScanner
from universe_loader import (
    align_to_common_calendar, filter_exact_correlation_duplicates,
    filter_structural_pairs, load_full_universe,
)

log = logging.getLogger("full_universe_eg_confirmation")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
_LOG_FILE_PATH = "latest_run_full_universe_eg_confirmation.log"
_fh = logging.FileHandler(_LOG_FILE_PATH, mode="a", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s"))
log.addHandler(_fh)

_CANDIDATES_DIR = "output/research/full_universe_correlation_prefilter_candidates_chunks"
_OUT_PATH = "output/research/full_universe_eg_confirmed_pairs.parquet"


def main():
    import argparse
    p = argparse.ArgumentParser(description="Full-universe EG/BH-FDR confirmation")
    p.add_argument("--tf", default="1D")
    p.add_argument("--n-workers", type=int, default=12)
    p.add_argument("--lookback-years", type=int, default=10,
                    help="Must match the --lookback-years the prefilter stage was run with -- "
                         "selects both the candidate chunk directory to read and the calendar "
                         "bound applied here (added 2026-08-15 for the 3y/5y/10y comparison)")
    args = p.parse_args()

    # Must match full_universe_correlation_prefilter.py's own naming exactly: that script
    # inserts the lookback-years suffix BEFORE "_chunks" (out_path.replace(".parquet", f"_{n}y.parquet")
    # then .replace(".parquet", "_chunks")), producing "..._candidates_5y_chunks", not
    # "..._candidates_chunks_5y" -- fixed 2026-08-15 after this exact mismatch caused the 5y EG
    # run to fail with "No candidate chunk files found" against a directory that was never written.
    candidates_dir = _CANDIDATES_DIR.replace("_chunks", f"_{args.lookback_years}y_chunks")
    out_path = _OUT_PATH.replace(".parquet", f"_{args.lookback_years}y.parquet")

    chunk_files = sorted(glob.glob(os.path.join(candidates_dir, "*.parquet")))
    if not chunk_files:
        log.error(f"No candidate chunk files found in {candidates_dir}")
        sys.exit(1)
    candidates_df = pd.concat([pd.read_parquet(f) for f in chunk_files], ignore_index=True)
    candidate_pairs_raw = candidates_df.to_dict("records")
    log.info(f"Loaded {len(candidate_pairs_raw)} candidate pairs from {len(chunk_files)} chunk files "
             f"in {candidates_dir}")

    candidate_pairs, dropped_dupes = filter_exact_correlation_duplicates(candidate_pairs_raw)
    log.info(f"Dedup (|pearson_corr|>=0.999999): dropped {len(dropped_dupes)} identity-duplicate "
             f"candidates, {len(candidate_pairs)} real candidates remain")

    candidate_pairs, dropped_structural = filter_structural_pairs(candidate_pairs)
    log.info(f"Structural-pair filter (index-tracking/share-class/GVKEY-cross-listing): dropped "
             f"{len(dropped_structural)} candidates, {len(candidate_pairs)} real candidates remain")

    log.info(f"Loading full merged universe for tf={args.tf} (same source as the pre-filter stage)...")
    t0 = time.time()
    aligned_data = load_full_universe(args.tf, columns=["close"])
    log.info(f"Loaded {len(aligned_data)} symbols in {time.time()-t0:.1f}s")

    log.info(f"Aligning all symbols to a shared calendar (lookback_years={args.lookback_years})...")
    t0 = time.time()
    aligned_data = align_to_common_calendar(aligned_data, lookback_years=args.lookback_years)
    log.info(f"Aligned {len(aligned_data)} symbols in {time.time()-t0:.1f}s")

    symbols_in_corr = sorted(aligned_data.keys())

    log.info(f"Running EG + BH-FDR confirmation on {len(candidate_pairs)} candidates "
             f"(n_workers={args.n_workers})...")
    t0 = time.time()
    confirmed, stats = CointScanner.scan(
        candidate_pairs, aligned_data, symbols_in_corr, tf_label=args.tf, n_workers=args.n_workers,
    )
    elapsed = time.time() - t0
    log.info(f"EG/BH-FDR complete in {elapsed:.1f}s ({elapsed/60:.1f} min). "
             f"stats={stats}")
    log.info(f"CONFIRMED: {len(confirmed)} pairs out of {len(candidate_pairs)} candidates tested")

    if confirmed:
        out_df = pd.DataFrame(confirmed)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        out_df.to_parquet(out_path, index=False)
        log.info(f"Saved {len(out_df)} confirmed pairs -> {out_path}")
    else:
        log.info("No pairs confirmed -- nothing saved.")


if __name__ == "__main__":
    main()
