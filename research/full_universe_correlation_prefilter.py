"""
research/full_universe_correlation_prefilter.py -- Thread P / Ross's "go for
it" (2026-08-14): runs the memory-bounded UniverseFilter.run_chunked()
against the FULL merged universe (universe_loader.py: yfinance + WRDS US +
WRDS international + Binance + IBKR intraday), not the ~1,659-symbol
S&P-1500-based universe analysis.py's own builder.build() currently produces.

DISCLOSED SCOPE LIMITATION, stated plainly, not hidden: this uses RAW price
data straight from universe_loader.py, NOT data.py's full DataCleaner/
GapFlag-aware quality-screening pipeline (that pipeline is scoped to the
existing ~1,659-symbol universe only; extending it to the full ~46,000-symbol
universe is a separate, real engineering task, not done here). This is
defensible SPECIFICALLY because the correlation step is already documented
elsewhere in this codebase (UniverseFilter.run()'s own BiasAuditLog record)
as "NOT the primary statistical decision" -- a coarse candidate pre-filter,
with the real rigor living in the downstream EG-cointegration + BH-FDR test.
Real, automatic protection still applies even without explicit GapFlag
columns: data.py's own `gap_aware_returns()` masks any return spanning more
than 4x the median bar interval purely from the DataFrame's own DatetimeIndex
-- a real safety net against the most egregious gap contamination, just not
the full FILL/NO_ACTIVITY/DATA_GAP distinction the production pipeline makes.

Candidates surviving this pre-filter should be re-verified through the
EXISTING, fully-rigorous production pipeline (proper GapFlag-aware alignment,
EG test, BH-FDR correction) before being trusted as real confirmed pairs --
this script produces a candidate LIST, not a final confirmed-pair set.

REVISED 2026-08-14 (Ross: "build the proper dedup fix first and re run full
cascade. also fix the fact that like 14000 assets or whatever it was didn't
get tested"). Two real, confirmed-not-theorized bugs found in the FIRST full
run (threshold=0.6, 541 raw "confirmed" pairs) and fixed here:
  1. Calendar misalignment -- universe_loader.load_full_universe()'s raw
     per-source DataFrames were never reindexed to a shared calendar.
     Confirmed live: a real candidate pair (0700.HK/3690.HK) crashed
     _eg_worker with a shape-broadcast ValueError, silently counted as a
     generic test failure alongside genuine insufficient_overlap cases --
     this is why ~17,797/18,450 candidates from the first run were never
     meaningfully EG-tested. Fixed via universe_loader.
     align_to_common_calendar(), applied right after loading, here AND in
     full_universe_eg_confirmation.py (both stages read raw arrays
     positionally and share the identical assumption).
  2. Identity-duplicate candidates -- 521/541 of the first run's raw
     "confirmed" pairs were same-underlying-security artifacts (PERMNO-
     fallback duplicate labels, or literal inverse-quoted FX pairs like
     FX_AUDUSD/FX_USDAUD), not real candidates. Fixed via universe_loader.
     filter_exact_correlation_duplicates() (general |pearson_corr|>=
     0.999999 signature) -- applied in full_universe_eg_confirmation.py
     right after this stage's chunk files are concatenated (one natural
     point already reading every candidate into memory), not rewritten
     into this script's own streamed chunk files, so run_chunked()'s
     already-verified bit-exact behavior stays untouched.
"""
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from analysis import UniverseFilter
from universe_loader import align_to_common_calendar, load_full_universe

log = logging.getLogger("full_universe_correlation_prefilter")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
_LOG_FILE_PATH = "latest_run_full_universe_correlation_prefilter.log"
_fh = logging.FileHandler(_LOG_FILE_PATH, mode="a", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s"))
log.addHandler(_fh)

_OUT_PATH = "output/research/full_universe_correlation_prefilter_candidates.parquet"


def _asset_class_for(symbol: str, source_hint: str) -> str:
    """Coarse asset-class tagging for cross-asset-class flagging in
    candidate_pairs() -- exact classification is not load-bearing for the
    correlation pre-filter itself (only used for the is_cross_asset flag)."""
    if symbol.startswith("GVKEY"):
        return "equity_intl"
    if "." in symbol and symbol.split(".")[-1] in ("USD", "JPY", "GBP", "EUR"):
        return "forex"
    return "equity"


def main():
    import argparse
    p = argparse.ArgumentParser(description="Full-universe correlation pre-filter (chunked)")
    p.add_argument("--tf", default="1D")
    p.add_argument("--batch-size", type=int, default=1500)
    p.add_argument("--threshold", type=float, default=None)
    p.add_argument("--lookback-years", type=int, default=10,
                    help="Calendar-alignment bound passed to align_to_common_calendar -- also "
                         "keys the output chunk directory/log so 3y/5y/10y runs don't collide "
                         "(added 2026-08-15, Ross: run the screen at 3y and 5y too for comparison)")
    p.add_argument("--limit", type=int, default=None,
                    help="Restrict to the first N symbols (alphabetical) -- for timing samples")
    args = p.parse_args()

    from config import Config
    threshold = args.threshold if args.threshold is not None else Config.UNIVERSE.MIN_PEARSON_CORR

    log.info(f"Loading full merged universe for tf={args.tf}...")
    t0 = time.time()
    # columns=["close"] (2026-08-17, real OOM near-miss found via k-BAHC): this driver only
    # ever uses the close column downstream -- see universe_loader.load_full_universe's docstring.
    aligned_data = load_full_universe(args.tf, columns=["close"])
    log.info(f"Loaded {len(aligned_data)} symbols in {time.time()-t0:.1f}s")

    # 2026-08-14 fix: raw per-source DataFrames were never reindexed to a shared
    # calendar -- confirmed live to crash/misalign EG testing for cross-market pairs
    # (see universe_loader.align_to_common_calendar's own docstring for the real,
    # data-confirmed bug). Applying it here too, not just before the EG stage,
    # since build_returns_matrix's own right-aligned positional padding has the
    # identical assumption -- the correlation prefilter's candidate list itself was
    # produced on misaligned data before this fix.
    log.info(f"Aligning all symbols to a shared calendar (lookback_years={args.lookback_years})...")
    t0 = time.time()
    aligned_data = align_to_common_calendar(aligned_data, lookback_years=args.lookback_years)
    log.info(f"Aligned {len(aligned_data)} symbols in {time.time()-t0:.1f}s")

    if args.limit:
        symbols_subset = sorted(aligned_data.keys())[: args.limit]
        aligned_data = {s: aligned_data[s] for s in symbols_subset}
        log.info(f"--limit {args.limit}: restricted to {len(aligned_data)} symbols")

    asset_class_map = {s: _asset_class_for(s, "") for s in aligned_data}

    # STREAMING (flush_path), not in-memory accumulation: a real run at full scale
    # (44,840 symbols) measured memory growing from 8.36GB to 9.66GB in 20s -- a rate
    # that would have OOM-crashed within ~90 more seconds. Fixed in UniverseFilter.
    # run_chunked() itself (see its own docstring); this driver just passes flush_path.
    out_path = _OUT_PATH.replace(".parquet", f"_{args.lookback_years}y.parquet")
    flush_dir = out_path.replace(".parquet", "_chunks") if not args.limit else \
        out_path.replace(".parquet", f"_limit{args.limit}_chunks")
    log.info(f"Running chunked correlation pre-filter: {len(aligned_data)} symbols, "
             f"batch_size={args.batch_size}, threshold={threshold}, streaming to {flush_dir}...")
    t0 = time.time()
    UniverseFilter.run_chunked(
        aligned_data, asset_class_map, threshold, tf_label=args.tf, batch_size=args.batch_size,
        flush_path=flush_dir, flush_every=20, progress_every=10,
    )
    elapsed = time.time() - t0
    log.info(f"Complete in {elapsed:.1f}s ({elapsed/60:.1f} min). "
             f"Candidate chunk files written to {flush_dir}")


if __name__ == "__main__":
    main()
