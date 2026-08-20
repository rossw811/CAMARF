"""
research/k_bahc_candidate_discovery.py -- comparison/diagnostic script, NOT
part of the production pipeline. Built 2026-07-21 per Ross's explicit
direction ("let's aim them toward building new application work... start
work on k-bahc"), motivated by the pair-set collapse this session
established (2 confirmed pairs out of a ~1.5M-possible-pair universe; the
filter-relevance sweep confirmed the collapse is NOT a filter-tuning
artifact -- excluded pairs are correctly excluded for real reasons). The
open question this script answers: is the collapse ALSO partly explained
by the FIRST stage of the funnel -- the raw Pearson correlation pre-filter
(Config.UNIVERSE.MIN_PEARSON_CORR, 0.40) -- burying genuine relationships
in sampling noise before they ever reach an EG cointegration test?

Method: reuses production UniverseFilter.run() directly (same code path as
research/fdr_method_comparison.py and research/sector_restricted_fdr_rescan.py)
to get the REAL, NaN-padding-aware pairwise-complete Pearson correlation
matrix for the current cached universe, then applies k-BAHC cleaning
(research/k_bahc_covariance_cleaning.py::clean_correlation_matrix, reused
directly, not reimplemented) to that same matrix.

IMPORTANT mechanism finding, verified BEFORE running on real data
(debug/_verify_k_bahc_candidate_discovery.py) -- read this before
interpreting output: k-BAHC cleaning keeps every WITHIN-cluster correlation
entry exactly as observed, and replaces every CROSS-cluster entry with a
SINGLE shared value (the mean of all observed cross-cluster correlations).
Consequence: cleaning can NEVER "rescue" an individual same-cluster pair
whose true relationship was pushed below threshold by sampling noise (those
entries are untouched). It CAN surface new cross-cluster candidates, but
ONLY in bulk -- either ALL cross-cluster pairs simultaneously (if the mean
cross-cluster correlation itself clears the threshold) or NONE of them
(never a subset). This is an all-or-nothing mechanism, not a per-pair
noise-reduction one -- confirmed directly on synthetic ground truth, not
assumed. Given this project's own established finding elsewhere (real
full-universe rho_bar ~ 0, research/eigenvalue_weighted_position_sizing.py's
docstring), the honest expectation going in is that this mechanism is
UNLIKELY to surface much at full-universe scale -- reported honestly
either way, not massaged toward a predetermined conclusion.

REWIRED 2026-08-17 (Ross, after the RAM-crash handoff: "run everything on the
17-18k universe calendar aligned"): this script previously read only
Config.DATA.CACHE_DIR (the old yfinance-only, ~1,567-1,730 symbol cache) via
its own local load_full_universe(suffix) -- meaning every "universe-wide"
k-BAHC run to date (2026-07-21 original, 2026-08-16 "reconfirmed" 1h/4h/1D)
never actually saw the WRDS-expanded universe at all, despite the plan
treating Thread P step 1 as complete. Real, checked-not-assumed reason this
can't just point at the full 44,840-symbol merged universe like the other
full-universe scripts: k-BAHC's clustering step needs the FULL dense N×N
correlation matrix at once (UniverseFilter.run(..., return_matrices=True)),
unlike the streaming/chunked candidate-pairs-only approach used elsewhere --
at 44,840 symbols that's a ~16GB float64 (or ~8GB float32) matrix alone, not
feasible on this 16GB-RAM machine even before adding a second concurrent job.
Rewired instead to universe_loader.load_full_universe() (yfinance+WRDS+
Binance+IBKR merge) + align_to_common_calendar(lookback_years=10) -- the
same calendar-bounded ~17-18k-symbol scope Thread J Test 1 uses (18,283
symbols in that run), which keeps the dense matrix feasible (~18k^2 * 4
bytes float32 =~ 1.2GB) while still being a real, order-of-magnitude-larger
test than the old ~1,700-symbol scope. If this run and a genuine 44,840-
symbol run (memory permitting, e.g. on different hardware) disagree
considerably, use the larger, more complete universe's result -- this
scoped-down run is a capacity compromise, not a claim that 17-18k is the
methodologically preferred universe.

Usage:
    python research/k_bahc_candidate_discovery.py --tf 1h
    python research/k_bahc_candidate_discovery.py --tf 1h --lookback-years 10
"""
import argparse
import logging
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config
from analysis import UniverseFilter, _eg_worker, _benjamini_hochberg, CointScanner
from k_bahc_covariance_cleaning import clean_correlation_matrix
from universe_loader import align_to_common_calendar, load_full_universe

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_ROOT, "output", "research")

log = logging.getLogger("k_bahc_candidate_discovery")


def _setup_logging(tf_label):
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, f"latest_run_k_bahc_candidate_discovery_{tf_label}.log"),
        mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def find_new_and_removed_candidates(raw_corr, cleaned_corr, symbols, threshold):
    """Compares candidate sets before/after k-BAHC cleaning. Returns
    (new_candidates, removed_candidates), each a list of (sym_a, sym_b,
    raw_corr, cleaned_corr) tuples."""
    n = len(symbols)
    new_candidates, removed_candidates = [], []
    for i in range(n):
        for j in range(i + 1, n):
            raw_c, clean_c = raw_corr[i, j], cleaned_corr[i, j]
            raw_ok = np.isfinite(raw_c) and abs(raw_c) >= threshold
            clean_ok = np.isfinite(clean_c) and abs(clean_c) >= threshold
            if clean_ok and not raw_ok:
                new_candidates.append((symbols[i], symbols[j], float(raw_c), float(clean_c)))
            elif raw_ok and not clean_ok:
                removed_candidates.append((symbols[i], symbols[j], float(raw_c), float(clean_c)))
    return new_candidates, removed_candidates


def run_eg_fdr(candidates, aligned, retained_symbols, tf_label, alpha=None):
    """Runs the real production EG test + BH-FDR on a candidate list.
    Reuses _eg_worker/_benjamini_hochberg directly (same pattern as
    research/fdr_method_comparison.py). candidates: list of (sym_a, sym_b)
    tuples. Returns a DataFrame with pvalue + confirmed_bh columns."""
    if not candidates:
        return pd.DataFrame()
    alpha = alpha if alpha is not None else Config.STATS.FDR_ALPHA
    log_prices = CointScanner._build_log_price_map(aligned, retained_symbols)
    tasks = []
    for sym_a, sym_b in candidates:
        lp_a = log_prices.get(sym_a)
        lp_b = log_prices.get(sym_b)
        if lp_a is None or lp_b is None:
            continue
        tasks.append((sym_a, sym_b, lp_a, lp_b, Config.ANALYSIS.EG_MAX_LAG, tf_label))
    if not tasks:
        return pd.DataFrame()

    results = []
    with ProcessPoolExecutor(max_workers=12) as pool:
        for r in pool.map(_eg_worker, tasks, chunksize=25):
            results.append(r)
    ok = [r for r in results if r.get("ok")]
    if not ok:
        return pd.DataFrame(results)
    df = pd.DataFrame(ok)
    rejected, _ = _benjamini_hochberg(df["pvalue"].to_numpy(), alpha)
    df["confirmed_bh"] = rejected
    return df


def _load_sector_map():
    """GICS sector tags, same file analysis.py's own _save_tf_results() merge
    step uses (Config.DATA.CACHE_DIR/gics_tags.csv). Returns {symbol: sector},
    empty dict if the file doesn't exist."""
    path = os.path.join(Config.DATA.CACHE_DIR, "gics_tags.csv")
    if not os.path.exists(path):
        return {}
    df = pd.read_csv(path, dtype=str)
    return dict(zip(df["symbol"], df["sector"]))


def main():
    p = argparse.ArgumentParser(description="k-BAHC correlation cleaning applied to candidate discovery (2026-07-21)")
    p.add_argument("--tf", default="1h")
    p.add_argument("--max-k", type=int, default=6)
    p.add_argument("--force-k", type=int, default=None,
                    help="Follow-up #1 (2026-07-21): bypass silhouette k-selection entirely and cut "
                         "the dendrogram at exactly this k. Silhouette picked k=2 on the real full "
                         "1h universe regardless of max_k up to 40 -- this tests whether a "
                         "deliberately finer partition surfaces structure silhouette's global optimum "
                         "misses at whole-universe scale. Chosen up front, not searched over multiple "
                         "values and kept whichever helps -- no Garden-of-Forking-Paths risk.")
    p.add_argument("--sector", default=None,
                    help="Follow-up #2 (2026-07-21): restrict clustering to symbols tagged with this "
                         "GICS sector (output/cache/gics_tags.csv) instead of the whole universe. "
                         "Correlation structure may be richer within a single sector than across the "
                         "full ~1500-asset universe, where cross-sector relationships dilute the "
                         "average toward the project's own established rho_bar~0 finding.")
    p.add_argument("--lookback-years", type=int, default=10,
                    help="Calendar-alignment bound passed to align_to_common_calendar (2026-08-17 "
                         "rewire) -- matches Thread J Test 1's own scope by default.")
    args = p.parse_args()
    tf_label = args.tf
    _setup_logging(tf_label)

    t0 = time.time()
    log.info("=== k_bahc_candidate_discovery.py: does denoising the correlation matrix "
              "surface new pair candidates the raw Pearson pre-filter misses? (tf=%s) ===", tf_label)

    # columns=["close"] (2026-08-17, real OOM near-miss): this script only ever uses the
    # close column downstream -- see universe_loader.load_full_universe's own docstring.
    tf_data_raw = load_full_universe(tf_label, columns=["close"])
    log.info("Loaded %d symbols from the merged yfinance+WRDS+Binance+IBKR universe for tf=%s",
             len(tf_data_raw), tf_label)
    if tf_label != "1D":
        log.warning("tf=%s: WRDS (the source of the ~44,840-symbol expansion) is daily-only -- "
                     "the merged universe at this timeframe is NOT meaningfully larger than the "
                     "old ~1,700-symbol scope. Only tf=1D sees the real expansion.", tf_label)

    if args.sector:
        sector_map = _load_sector_map()
        if not sector_map:
            log.warning("--sector given but output/cache/gics_tags.csv not found -- aborting.")
            return
        before = len(tf_data_raw)
        tf_data_raw = {sym: df for sym, df in tf_data_raw.items() if sector_map.get(sym) == args.sector}
        log.info("--sector=%s: restricted universe %d -> %d symbols", args.sector, before, len(tf_data_raw))

    if len(tf_data_raw) < 10:
        log.warning("Fewer than 10 symbols -- not enough for a meaningful clustering exercise. Aborting.")
        return

    log.info("Aligning to a shared calendar (lookback_years=%d)...", args.lookback_years)
    aligned = align_to_common_calendar(tf_data_raw, lookback_years=args.lookback_years)
    log.info("Aligned: %d symbols", len(aligned))

    threshold = Config.UNIVERSE.MIN_PEARSON_CORR
    asset_class_map = {sym: "equity" for sym in aligned}
    # REWIRED again, 2026-08-17, same night: even pearson_only=True still peaked at multiple
    # simultaneous (n,n) float64 arrays during correlation_matrix()'s own internal expression
    # evaluation (mid-expression temporaries, not eliminated by low_memory=True's explicit
    # `del`s alone) -- a second real near-miss caught live at N=17,324, ~600MB free before
    # being killed. Real fix: UniverseFilter.chunked_pearson_matrix() builds the SAME full
    # dense matrix k-BAHC's clustering step needs, but bounded to block-sized peaks (see its
    # own docstring). This is what k-BAHC needed all along -- the full matrix, computed safely.
    _min_overlap = getattr(Config.STATS, "MIN_OVERLAP_BY_TF", {}).get(tf_label, 252)
    returns, symbols, _idx = UniverseFilter.build_returns_matrix(aligned, min_overlap=_min_overlap)
    log.info("Returns matrix built: %d symbols retained after overlap filtering", len(symbols))
    log.info("Computing %dx%d Pearson correlation matrix (chunked, memory-bounded)...",
              len(symbols), len(symbols))
    pearson = UniverseFilter.chunked_pearson_matrix(
        returns, batch_size=1500, progress_every=20, progress_label=f"[{tf_label}] ",
    )
    finite_mask = np.isfinite(pearson) & ~np.eye(len(symbols), dtype=bool)
    n_candidates = int(np.sum((np.abs(pearson) >= threshold) & finite_mask)) // 2
    n_possible = len(symbols) * (len(symbols) - 1) // 2
    log.info("Raw candidates (|corr|>=%.2f): %d / %d possible pairs", threshold, n_candidates, n_possible)

    log.info("Applying k-BAHC cleaning (max_k=%d) to the %dx%d Pearson matrix...",
              args.max_k, len(symbols), len(symbols))
    t_clean = time.time()
    cleaned_corr, k_used = clean_correlation_matrix(pearson, max_k=args.max_k, force_k=args.force_k)
    log.info("k-BAHC cleaning done in %.1fs, chose k=%d clusters", time.time() - t_clean, k_used)

    n = len(symbols)
    finite_mask = np.isfinite(pearson) & ~np.eye(n, dtype=bool)
    off_diag = pearson[finite_mask]
    log.info("Raw correlation matrix: mean|corr|=%.4f over %d finite off-diagonal pairs",
              float(np.nanmean(np.abs(off_diag))), int(finite_mask.sum() / 2))

    new_candidates, removed_candidates = find_new_and_removed_candidates(
        pearson, cleaned_corr, symbols, threshold
    )
    log.info("")
    log.info("=== Candidate set comparison: raw vs. k-BAHC-cleaned Pearson matrix ===")
    log.info("New candidates (below threshold raw, above threshold cleaned): %d", len(new_candidates))
    log.info("Removed candidates (above threshold raw, below threshold cleaned): %d", len(removed_candidates))

    if removed_candidates:
        log.info("Sample of removed (likely noise-suppressed) candidates:")
        for sym_a, sym_b, raw_c, clean_c in sorted(removed_candidates, key=lambda x: -abs(x[2]))[:10]:
            log.info("  %s/%s: raw=%.3f -> cleaned=%.3f", sym_a, sym_b, raw_c, clean_c)

    eg_results_new = pd.DataFrame()
    if new_candidates:
        log.info("")
        log.info("New candidates found -- running real EG+BH-FDR test on them (%d pairs)...", len(new_candidates))
        eg_results_new = run_eg_fdr(
            [(a, b) for a, b, _, _ in new_candidates], aligned, symbols, tf_label
        )
        if not eg_results_new.empty:
            n_confirmed = int(eg_results_new["confirmed_bh"].sum()) if "confirmed_bh" in eg_results_new.columns else 0
            log.info("EG+BH-FDR on new candidates: %d/%d usable results, %d confirmed",
                      len(eg_results_new), len(new_candidates), n_confirmed)
            for _, row in eg_results_new.sort_values("pvalue").head(10).iterrows():
                log.info("  %s/%s: eg_pvalue=%.4f confirmed_bh=%s",
                         row["symbol_a"], row["symbol_b"], row["pvalue"], row.get("confirmed_bh"))
        else:
            log.info("No usable EG results for new candidates (insufficient overlap or all failed).")
    else:
        log.info("")
        log.info("HONEST NULL RESULT: no new candidates surfaced by k-BAHC cleaning at this "
                 "timeframe/threshold. Per the verified mechanism (debug/_verify_k_bahc_candidate_"
                 "discovery.py), this happens whenever the mean cross-cluster correlation itself "
                 "stays below the %.2f threshold -- consistent with this project's own established "
                 "finding that real full-universe correlation is close to zero on average "
                 "(rho_bar~0, see research/eigenvalue_weighted_position_sizing.py). This is a "
                 "genuine, informative negative result, not a failed search.", threshold)

    os.makedirs(_OUT_DIR, exist_ok=True)
    new_df = pd.DataFrame(
        [{"symbol_a": a, "symbol_b": b, "raw_corr": rc, "cleaned_corr": cc}
         for a, b, rc, cc in new_candidates]
    )
    removed_df = pd.DataFrame(
        [{"symbol_a": a, "symbol_b": b, "raw_corr": rc, "cleaned_corr": cc}
         for a, b, rc, cc in removed_candidates]
    )
    # Distinct output suffix per variant (whole-universe vs forced-k vs
    # sector-restricted) so follow-up runs don't silently overwrite each
    # other's results (same class of bug as BUG-D67/A14's tf-label
    # collisions, avoided here by construction).
    variant_suffix = suffix
    if args.sector:
        variant_suffix += f"_sector-{args.sector.replace(' ', '')}"
    if args.force_k is not None:
        variant_suffix += f"_forcek{args.force_k}"
    new_df.to_parquet(os.path.join(_OUT_DIR, f"k_bahc_candidate_discovery_new_{variant_suffix}.parquet"), index=False)
    removed_df.to_parquet(os.path.join(_OUT_DIR, f"k_bahc_candidate_discovery_removed_{variant_suffix}.parquet"), index=False)
    if not eg_results_new.empty:
        eg_results_new.to_parquet(
            os.path.join(_OUT_DIR, f"k_bahc_candidate_discovery_eg_{variant_suffix}.parquet"), index=False
        )
    log.info("Saved -> output/research/k_bahc_candidate_discovery_{new,removed,eg}_%s.parquet", variant_suffix)

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("k_bahc_candidate_discovery.py complete (%.1f min)", runtime)


if __name__ == "__main__":
    main()
