"""
research/wrds_deep_history_episodic_scan.py -- Ross's direct request
(2026-07-27): "I refuse to believe that our current confirmed sets are
correct. I believe we have way more episodic connections I want to test."

HYPOTHESIS: production's daily-timeframe (1D) EG+FDR scan, run on yfinance's
own daily bars, found ZERO confirmed pairs (confirmed directly: the
2026-07-22 capstone rerun's 1D summary shows pairs=0). yfinance's daily
history is comparatively short and lower-quality (retail-facing, subject to
the various documented data-quality issues this project has fought all
session). WRDS's CRSP (back to 1925) and Compustat Global (back to 1913)
give the SAME symbols FAR longer, cleaner, survivorship-bias-free daily
history. This script tests whether that additional depth reveals genuinely
cointegrated pairs the yfinance-based 1D scan lacked the history/quality to
detect -- not a different methodology, the SAME EG-both-directions+BH-FDR
pipeline already fixed and verified in analysis.py this session, applied to
better input data.

Honest framing, stated up front: this is NOT a like-for-like comparison
against the current 2m/3m-confirmed KVUE/KMB pairs (WRDS/CRSP has no
intraday data at all -- this script is necessarily a DAILY-timeframe-only
analysis). The correct comparison point is production's own 1D scan (zero
confirmed pairs on yfinance's daily data), not the intraday-confirmed set.

Reuses REAL production code throughout, not a reimplementation:
  - analysis.py's UniverseFilter.correlation_matrix/candidate_pairs (same
    Pearson pre-filter, same Config.UNIVERSE.MIN_PEARSON_CORR threshold)
  - analysis.py's _eg_worker + the SAME both-directions max-combination
    logic CointScanner.scan() uses (fixed this session) -- run manually
    here since CointScanner.scan() itself expects yfinance-shaped
    aligned_data, not WRDS's own cache layout
  - analysis.py's _benjamini_hochberg (BH-FDR, same Config.STATS.FDR_ALPHA)
  - analysis.py's CointScanner.rolling_fraction logic, reimplemented for a
    much longer window suited to decades of history (not copy-pasted with
    the same 252-bar window, which would badly under-use 50-100 years of
    data) -- this is the genuinely NEW piece: an "episodic" fraction over
    a MUCH longer horizon than was ever possible with yfinance/IBKR-depth
    data.

Return series used: 'close_total_return' (split+dividend adjusted) for
CRSP-sourced US equities; raw 'close' (split-adjusted only) for the two
Compustat Global symbols already fetched (7267.T/8058.T) -- their
total-return reconstruction isn't built yet (see data_wrds.py's own
docstring), disclosed rather than silently mixed with the US total-return
series as if equivalent.

Scope, stated honestly: only symbols with a fetched output/cache/wrds/
*_1D.parquet file are included -- this is currently the ~1500 US equity/ETF
universe (data_wrds.py's bulk fetch) plus whichever Compustat Global symbols
have been manually resolved so far (7267.T, 8058.T only -- the rest of the
international universe needs the same one-by-one name+currency resolution,
not yet done). NOT a claim of full-universe coverage.

Verified against synthetic ground truth first:
debug/_verify_wrds_deep_history_episodic_scan.py.

Usage:
    python research/wrds_deep_history_episodic_scan.py
"""
import glob
import logging
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from analysis import UniverseFilter, _eg_worker, _benjamini_hochberg, CointScanner
from research.rolling_adv_comparison import rolling_adv, load_wrds_universe_ohlcv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WRDS_CACHE_DIR = os.path.join(_ROOT, "output", "cache", "wrds")
_OUT_DIR = os.path.join(_ROOT, "output", "research")

TF_LABEL = "1D_wrds"  # distinct label -- NOT the production "1D" tf_label, to avoid any risk
                       # of this research output being mistaken for a production result
EPISODIC_WINDOW_BARS = 2520   # ~10 trading years -- long enough to span multiple decades
                               # in ~10-year steps across up to a century of history, versus
                               # production's own 252-bar (~1yr) window, which would be far
                               # too short-sighted to characterize century-scale stability
EPISODIC_STEP_BARS = 252      # re-evaluate roughly once a year

log = logging.getLogger("wrds_deep_history_episodic_scan")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_wrds_deep_history_episodic_scan.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def load_wrds_universe():
    """Loads every fetched output/cache/wrds/*_1D.parquet file. Returns
    {symbol: close_series} using close_total_return where available (CRSP),
    falling back to split-only close otherwise (Compustat Global, not yet
    total-return-adjusted -- logged explicitly, not silently blended in)."""
    out = {}
    used_total_return = set()
    used_split_only = set()
    for f in sorted(glob.glob(os.path.join(_WRDS_CACHE_DIR, "*_1D.parquet"))):
        sym = os.path.basename(f)[: -len("_1D.parquet")]
        df = pd.read_parquet(f)
        if "close_total_return" in df.columns and df["close_total_return"].notna().any():
            out[sym] = df["close_total_return"]
            used_total_return.add(sym)
        else:
            out[sym] = df["close"]
            used_split_only.add(sym)
    log.info(f"Loaded {len(out)} symbols from output/cache/wrds/: "
             f"{len(used_total_return)} total-return-adjusted (CRSP), "
             f"{len(used_split_only)} split-only-adjusted (Compustat Global, disclosed)")
    return out, used_split_only


def build_log_prices_and_returns(close_by_symbol):
    """Aligns every symbol onto the shared calendar (union of all trading
    dates present in the loaded WRDS data) and returns (log_price_df,
    returns_df). Log returns require min 756 bars (~3yr) overlap to be
    included -- matches production's own MIN_OVERLAP_BY_TF-style floor for
    daily-ish data, not an arbitrary new choice."""
    close_df = pd.DataFrame(close_by_symbol).sort_index()
    log_price_df = np.log(close_df.astype(float))
    returns = log_price_df.diff().iloc[1:]
    valid_cols = returns.columns[returns.notna().sum() >= 756]
    return log_price_df[valid_cols], returns[valid_cols]


def episodic_fraction(log_a, log_b, max_lag, window=EPISODIC_WINDOW_BARS, step=EPISODIC_STEP_BARS):
    """Rolling EG-both-directions test over a MUCH longer window than
    production's own 252-bar rolling_fraction -- the genuinely new
    capability this script exists to test, now that WRDS depth makes a
    multi-decade rolling scan possible at all. Returns the fraction of
    windows where max(p_ab, p_ba) < 0.05, and the per-window p-values for
    inspection.

    Used ONLY as a descriptive stability check for Tier 1's already
    full-sample-confirmed pairs (see main()) -- NOT the discovery mechanism
    for episodic-only pairs. That distinction matters: a pair cointegrated
    in only one multi-decade regime is exactly the shape of relationship a
    FULL-SAMPLE EG test (Tier 1's gate) is least likely to detect, since
    decades of "no relationship" data dilate the whole-sample test
    statistic. Tiers 2/3 (build_rolling_eg_tasks/run_rolling_eg_pool/
    episodic_bhfdr_confirm, below) test EVERY candidate pair's rolling
    windows independent of any full-sample result, specifically to find
    what this function's Tier-1-only usage would structurally miss.
    """
    mask = np.isfinite(log_a) & np.isfinite(log_b)
    a, b = log_a[mask], log_b[mask]
    n = len(a)
    if n < window:
        return np.nan, []
    pvals = []
    for start in range(0, n - window + 1, step):
        seg_a, seg_b = a[start:start + window], b[start:start + window]
        r_ab = _eg_worker(("A", "B", seg_a, seg_b, max_lag, TF_LABEL))
        r_ba = _eg_worker(("B", "A", seg_b, seg_a, max_lag, TF_LABEL))
        if not (r_ab.get("ok") and r_ba.get("ok")):
            continue
        pvals.append(max(r_ab["pvalue"], r_ba["pvalue"]))
    if not pvals:
        return np.nan, []
    frac = float(np.mean(np.array(pvals) < 0.05))
    return frac, pvals


def _checkpoint_paths(checkpoint_id):
    base = os.path.join(_OUT_DIR, f"checkpoint_{checkpoint_id}")
    return base + ".parquet", base + ".meta"


def _load_checkpoint(checkpoint_id):
    """Loads a prior run's checkpoint (results + how many pairs were already
    processed), if one exists. Returns (results_list, n_pairs_done) --
    (None, 0) if no checkpoint is found, so callers can start clean."""
    data_path, meta_path = _checkpoint_paths(checkpoint_id)
    if not (os.path.exists(data_path) and os.path.exists(meta_path)):
        return None, 0
    df = pd.read_parquet(data_path)
    with open(meta_path) as f:
        n_done = int(f.read().strip())
    return df.to_dict("records"), n_done


def _save_checkpoint(checkpoint_id, results, n_pairs_done):
    """Persists accumulated results + progress marker so a crash can RESUME
    from the last saved batch instead of restarting the whole run -- added
    2026-07-27 directly in response to the real BrokenProcessPool crash this
    project hit partway through Tier 1's full-sample EG step."""
    os.makedirs(_OUT_DIR, exist_ok=True)
    data_path, meta_path = _checkpoint_paths(checkpoint_id)
    pd.DataFrame(results).to_parquet(data_path, index=False)
    with open(meta_path, "w") as f:
        f.write(str(n_pairs_done))


def clear_checkpoint(checkpoint_id):
    """Deletes a checkpoint's files -- call after a run completes
    successfully, so a later, unrelated invocation doesn't accidentally
    resume from stale progress."""
    data_path, meta_path = _checkpoint_paths(checkpoint_id)
    for p in (data_path, meta_path):
        if os.path.exists(p):
            os.remove(p)


def run_full_sample_eg_pool(pairs, log_price_df, max_lag, workers=12, pair_batch_size=5000,
                             checkpoint_id=None, checkpoint_every=5):
    """
    Tier 1's full-sample EG-both-directions step, run in BOUNDED-MEMORY
    batches (added 2026-07-27 after a real crash -- see run_rolling_eg_pool's
    docstring for the full BrokenProcessPool incident this and that function
    both fix the same way). At 199,589 Tier-1 candidate pairs, building all
    399,178 directional tasks in memory before any submission caused a
    worker to be killed abruptly (OOM). Now processes `pairs` in batches of
    `pair_batch_size` (default 5000 -- larger than Tier 2/3's 500, since
    Tier 1 has only ONE task per direction per pair, not dozens of rolling
    windows, so far more pairs fit in a bounded batch), reusing a single
    ProcessPoolExecutor and a symbol-array cache built once up front.

    CHECKPOINTING (added the same day, directly after the crash, per Ross's
    explicit request -- "if the scripts crash i don't want to have to
    restart. save progress."): if `checkpoint_id` is given, accumulated
    results are saved to disk every `checkpoint_every` batches. On start,
    if a checkpoint for this `checkpoint_id` already exists, resumes from
    the first UN-processed pair rather than recomputing from scratch --
    `pairs` MUST be passed in the SAME order across resumed runs for this
    to be correct (the checkpoint stores a pair COUNT, not pair identities,
    so it assumes the pair list itself hasn't changed between runs).
    Checkpoint files are NOT deleted automatically on success -- call
    clear_checkpoint(checkpoint_id) explicitly once a run's results have
    been consumed/saved to their final destination.

    Returns a list of raw {symbol_a, symbol_b, ..., ok, pvalue} result dicts
    (same shape _eg_worker always returned) -- main()'s existing
    reassembly logic (grouping by frozenset((symbol_a, symbol_b))) is
    unchanged, just fed from this batched runner instead of one giant
    pool.map call.
    """
    all_symbols = {p["symbol_a"] for p in pairs} | {p["symbol_b"] for p in pairs}
    array_cache = _build_symbol_array_cache(log_price_df, all_symbols)

    results = []
    start_pair_idx = 0
    if checkpoint_id:
        loaded, n_done = _load_checkpoint(checkpoint_id)
        if loaded is not None:
            results = loaded
            start_pair_idx = n_done
            log.info(f"Resuming '{checkpoint_id}' from checkpoint: {len(results)} results already "
                     f"computed, {n_done}/{len(pairs)} pairs already done -- skipping to pair {n_done}.")

    n_batches = (len(pairs) + pair_batch_size - 1) // pair_batch_size
    log.info(f"Running full-sample EG on {len(pairs)} pairs in {n_batches} batches of "
             f"<={pair_batch_size} pairs each (workers={workers})...")
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for batch_num, i in enumerate(range(start_pair_idx, len(pairs), pair_batch_size)):
            batch_pairs = pairs[i:i + pair_batch_size]
            tasks = []
            for p in batch_pairs:
                lp_a, lp_b = array_cache[p["symbol_a"]], array_cache[p["symbol_b"]]
                tasks.append((p["symbol_a"], p["symbol_b"], lp_a, lp_b, max_lag, TF_LABEL))
                tasks.append((p["symbol_b"], p["symbol_a"], lp_b, lp_a, max_lag, TF_LABEL))
            results.extend(pool.map(_eg_worker, tasks, chunksize=100))
            n_done_now = i + len(batch_pairs)
            if checkpoint_id and batch_num % checkpoint_every == 0:
                _save_checkpoint(checkpoint_id, results, n_done_now)
            if (i // pair_batch_size) % 5 == 0:
                log.info(f"  batch (pairs {i}-{n_done_now}/{len(pairs)}) done "
                         f"({(time.time()-t0)/60:.1f} min elapsed)")
    if checkpoint_id:
        _save_checkpoint(checkpoint_id, results, len(pairs))
    log.info(f"Full-sample EG complete in {(time.time()-t0)/60:.1f} min")
    return results


# =============================================================================
# SECTION: Tier 2/3 -- genuine episodic DISCOVERY (not post-hoc stability
# check of Tier-1-confirmed pairs). Added 2026-07-27 after discussing the
# Tier-1-only design's structural blind spot with Ross directly: a pair
# cointegrated in only one multi-decade regime would rarely survive a
# full-sample EG test, so Tier 1 alone could never surface it. Three tiers,
# run and reported SEPARATELY (not merged into one ambiguous confirmed set),
# per Ross's explicit request to compare all three side by side:
#   Tier 1 (unchanged, above): static whole-history corr prefilter ->
#           full-sample EG -> BH-FDR -> "confirmed" (production-identical).
#   Tier 2: SAME static corr prefilter as Tier 1, but candidate pairs go
#           straight to rolling-window EG -- no full-sample EG gate at all.
#           Isolates the effect of relaxing the EG-confirmation gate alone.
#   Tier 3: rolling correlation prefilter (a pair qualifies if correlated in
#           ANY sufficiently long window, not the whole history) + rolling
#           EG. Isolates the ADDITIONAL effect of relaxing the correlation
#           prefilter too.
# =============================================================================

def rolling_correlation_candidate_pairs(returns_df, symbols, threshold, asset_class_map,
                                         window=EPISODIC_WINDOW_BARS, step=EPISODIC_STEP_BARS):
    """
    Tier-3 upstream candidate filter. Production's own (and Tier 1/2's)
    correlation prefilter requires WHOLE-HISTORY correlation to clear
    `threshold` -- a pair correlated only in one multi-decade sub-period
    would be silently excluded before ever reaching an EG test, even though
    that sub-period is exactly what an episodic scan is trying to find.
    This function instead unions each window's qualifying pairs across the
    full rolling scan -- a pair qualifies if it clears `threshold` in AT
    LEAST ONE window, not on average across all of history.

    Reuses UniverseFilter.correlation_matrix/candidate_pairs PER WINDOW --
    the same vectorized production implementation Tier 1 already calls once
    for the whole sample, just called once per window here instead of
    reimplementing a new correlation routine.
    """
    returns_arr = returns_df.to_numpy()
    n = len(returns_arr)
    union_pairs = {}
    n_windows = 0
    for start in range(0, n - window + 1, step):
        seg = returns_arr[start:start + window]
        corr = UniverseFilter.correlation_matrix(seg.T)
        window_pairs = UniverseFilter.candidate_pairs(corr, symbols, threshold, asset_class_map)
        n_windows += 1
        for p in window_pairs:
            key = frozenset((p["symbol_a"], p["symbol_b"]))
            if key not in union_pairs or p["pearson_corr"] > union_pairs[key]["pearson_corr"]:
                union_pairs[key] = p
    log.info(f"Rolling correlation prefilter: {n_windows} windows scanned, "
             f"{len(union_pairs)} pairs qualify in >=1 window (vs whole-history static filter)")
    return list(union_pairs.values())


def _build_symbol_array_cache(log_price_df, symbols):
    """
    Converts each symbol's log-price column to a numpy array EXACTLY ONCE,
    keyed by symbol. Added 2026-07-27 alongside the batched-submission fix
    below -- found directly that the original per-pair `.to_numpy()` calls
    (once per pair, both here and in Tier 1's own task construction) created
    a SEPARATE array copy every time a symbol appeared in a pair, rather
    than sharing one copy -- for a popular symbol appearing in hundreds of
    candidate pairs, this meant hundreds of redundant copies of the same
    ~10,000+-element array. Building this cache once and passing it into
    build_rolling_eg_tasks (and Tier 1's analogous loop) eliminates that
    redundancy independent of the batching fix, which addresses the
    separate problem of holding ALL pairs' tasks in memory at once.
    """
    return {s: log_price_df[s].to_numpy() for s in symbols}


def build_rolling_eg_tasks(pairs, log_price_df, max_lag, window=EPISODIC_WINDOW_BARS, step=EPISODIC_STEP_BARS,
                           adv_by_symbol=None, adv_threshold=None, array_cache=None):
    """Builds the flat both-directions EG task list for every (pair, window)
    combination, in the exact tuple shape _eg_worker already expects -- lets
    Tier 2/3 reuse the SAME ProcessPoolExecutor pattern Tier 1's full-sample
    step uses (analysis.py's _eg_worker, unchanged), just with many more
    tasks (one pair produces ~8-9 windows x 2 directions instead of 1x2).
    Returns (tasks, task_meta) -- task_meta is a parallel list of
    (symbol_a, symbol_b, window_start, direction) so results can be
    reassembled after pool.map (which returns results in task order only,
    not tagged with which pair/window/direction produced them).

    Rolling ADV liquidity gate (added 2026-07-27, after
    research/rolling_adv_comparison.py's comparison arm found 26.8% of real
    (symbol, window) combinations were "false liquid" under a flat
    whole-history ADV check): if `adv_by_symbol` is provided (a
    {symbol: rolling-ADV pd.Series, DATE-indexed} map, built via
    rolling_adv_comparison.rolling_adv), a window is only tested if BOTH
    symbols' rolling ADV at that window's actual START DATE clears
    `adv_threshold`. Uses `.asof(date)` (not positional lookup) -- the
    per-pair `mask` below drops rows where EITHER symbol has a NaN log
    price, so window-array positions do NOT correspond to the same calendar
    dates across different pairs; only the pair's OWN dates (tracked via
    `dates_masked = log_price_df.index[mask]`) are a valid lookup key into
    a symbol's independently-indexed ADV series. `.asof()` is itself causal
    (finds the last value at or before the given date), preserving the
    no-lookahead guarantee already proven for rolling_adv() itself.

    `array_cache` (optional, see _build_symbol_array_cache): if provided,
    reuses each symbol's already-converted array instead of calling
    `.to_numpy()` again -- purely a memory/CPU optimization, same task
    output either way. Defaults to None (original per-call behavior) so
    existing callers/tests that don't pass it are unaffected.
    """
    tasks, task_meta = [], []
    thr = adv_threshold if adv_threshold is not None else Config.STATS.ADV_FILTER_USD
    n_gated = 0
    for p in pairs:
        sym_a, sym_b = p["symbol_a"], p["symbol_b"]
        if array_cache is not None:
            lp_a, lp_b = array_cache[sym_a], array_cache[sym_b]
        else:
            lp_a = log_price_df[sym_a].to_numpy()
            lp_b = log_price_df[sym_b].to_numpy()
        mask = np.isfinite(lp_a) & np.isfinite(lp_b)
        a, b = lp_a[mask], lp_b[mask]
        dates_masked = log_price_df.index[mask] if adv_by_symbol is not None else None
        n = len(a)
        if n < window:
            continue
        for start in range(0, n - window + 1, step):
            if adv_by_symbol is not None:
                window_start_date = dates_masked[start]
                adv_a_series = adv_by_symbol.get(sym_a)
                adv_b_series = adv_by_symbol.get(sym_b)
                adv_a_val = adv_a_series.asof(window_start_date) if adv_a_series is not None else np.nan
                adv_b_val = adv_b_series.asof(window_start_date) if adv_b_series is not None else np.nan
                liquid = (pd.notna(adv_a_val) and adv_a_val >= thr
                          and pd.notna(adv_b_val) and adv_b_val >= thr)
                if not liquid:
                    n_gated += 1
                    continue
            seg_a, seg_b = a[start:start + window], b[start:start + window]
            tasks.append((sym_a, sym_b, seg_a, seg_b, max_lag, TF_LABEL))
            task_meta.append((sym_a, sym_b, start, "ab"))
            tasks.append((sym_b, sym_a, seg_b, seg_a, max_lag, TF_LABEL))
            task_meta.append((sym_a, sym_b, start, "ba"))
    if adv_by_symbol is not None:
        log.info(f"  ADV liquidity gate: skipped {n_gated} (pair, window) combinations where "
                 f"either symbol's rolling ADV was below ${thr/1e6:.0f}M at that window's start date")
    return tasks, task_meta


def run_rolling_eg_pool(pairs, log_price_df, max_lag, window=EPISODIC_WINDOW_BARS,
                         step=EPISODIC_STEP_BARS, workers=12, adv_by_symbol=None, adv_threshold=None,
                         pair_batch_size=500, checkpoint_id=None, checkpoint_every=10):
    """Runs the rolling-window EG-both-directions test for EVERY candidate
    pair, independent of any full-sample EG result -- the actual episodic
    DISCOVERY step Tier 2/3 both need. Returns a flat list of
    {symbol_a, symbol_b, window_start, pvalue} rows, one per (pair, window)
    -- the raw material for episodic_bhfdr_confirm's JOINT correction across
    the whole test family, not a per-pair-independent threshold.

    adv_by_symbol/adv_threshold are passed straight through to
    build_rolling_eg_tasks's liquidity gate (see its docstring).

    BOUNDED-MEMORY BATCHING (added 2026-07-27, after a real crash): the
    original version called build_rolling_eg_tasks ONCE for ALL pairs,
    materializing every (pair, window) task -- for a large candidate set
    (this project hit 199,589 Tier-1 pairs against a WRDS-scale universe,
    each pair producing dozens of rolling windows) this created millions of
    tasks in memory simultaneously before submission even began, and crashed
    with a BrokenProcessPool (a worker killed abruptly -- consistent with
    OOM on this project's 16GB-RAM hardware). Now processes `pairs` in
    batches of `pair_batch_size` (default 500): each batch's tasks are built,
    submitted, and their lightweight results kept -- the raw task tuples
    (which carry the actual array segments) are discarded before the next
    batch starts. A SINGLE ProcessPoolExecutor is reused across all batches
    (created once, not per-batch) to avoid repeated worker-startup overhead.
    The symbol-array cache (_build_symbol_array_cache) is also built ONCE
    up front, not per batch, since the same symbols recur across batches.

    CHECKPOINTING (added the same day as the crash, per Ross's explicit
    request to never lose progress on a crash): mirrors run_full_sample_eg_
    pool's checkpoint_id/checkpoint_every mechanism. `by_key` (a dict keyed
    by (symbol_a, symbol_b, window_start) -> {direction: pvalue}) is
    flattened to individual {symbol_a, symbol_b, window_start, direction,
    pvalue} rows for persistence, then reconstructed into the same dict
    shape on resume. Same caveat as the full-sample version: `pairs` must be
    passed in the SAME order across a resumed run.
    """
    all_symbols = {p["symbol_a"] for p in pairs} | {p["symbol_b"] for p in pairs}
    array_cache = _build_symbol_array_cache(log_price_df, all_symbols)

    by_key = {}
    start_pair_idx = 0
    if checkpoint_id:
        loaded, n_done = _load_checkpoint(checkpoint_id)
        if loaded is not None:
            for row in loaded:
                key = (row["symbol_a"], row["symbol_b"], row["window_start"])
                by_key.setdefault(key, {})[row["direction"]] = row["pvalue"]
            start_pair_idx = n_done
            log.info(f"Resuming '{checkpoint_id}' from checkpoint: {len(loaded)} (pair,window,direction) "
                     f"rows already computed, {n_done}/{len(pairs)} pairs already done -- "
                     f"skipping to pair {n_done}.")

    def _flatten_by_key(d):
        return [{"symbol_a": k[0], "symbol_b": k[1], "window_start": k[2], "direction": direction,
                 "pvalue": pval} for k, dirs in d.items() for direction, pval in dirs.items()]

    n_batches = (len(pairs) + pair_batch_size - 1) // pair_batch_size
    log.info(f"Running rolling-window EG on {len(pairs)} pairs in {n_batches} batches of "
             f"<={pair_batch_size} pairs each (workers={workers})...")
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for batch_num, i in enumerate(range(start_pair_idx, len(pairs), pair_batch_size)):
            batch_pairs = pairs[i:i + pair_batch_size]
            tasks, task_meta = build_rolling_eg_tasks(
                batch_pairs, log_price_df, max_lag, window, step,
                adv_by_symbol=adv_by_symbol, adv_threshold=adv_threshold, array_cache=array_cache,
            )
            n_done_now = i + len(batch_pairs)
            if not tasks:
                if checkpoint_id and batch_num % checkpoint_every == 0:
                    _save_checkpoint(checkpoint_id, _flatten_by_key(by_key), n_done_now)
                continue
            results = pool.map(_eg_worker, tasks, chunksize=200)
            for meta, r in zip(task_meta, results):
                symbol_a, symbol_b, start, direction = meta
                if not r.get("ok"):
                    continue
                by_key.setdefault((symbol_a, symbol_b, start), {})[direction] = r["pvalue"]
            if checkpoint_id and batch_num % checkpoint_every == 0:
                _save_checkpoint(checkpoint_id, _flatten_by_key(by_key), n_done_now)
            if (i // pair_batch_size) % 10 == 0:
                log.info(f"  batch (pairs {i}-{n_done_now}/{len(pairs)}) done "
                         f"({(time.time()-t0)/60:.1f} min elapsed)")
    if checkpoint_id:
        _save_checkpoint(checkpoint_id, _flatten_by_key(by_key), len(pairs))
    log.info(f"  done in {(time.time()-t0)/60:.1f} min")

    flat = []
    for (symbol_a, symbol_b, start), d in by_key.items():
        if "ab" in d and "ba" in d:
            flat.append({"symbol_a": symbol_a, "symbol_b": symbol_b,
                         "window_start": start, "pvalue": max(d["ab"], d["ba"])})
    return flat


def episodic_bhfdr_confirm(flat_pvalue_rows, alpha, min_windows_confirmed=1):
    """
    Joint BH-FDR correction across the ENTIRE (pair, window) test family --
    deliberately NOT per-pair-independent uncorrected p<0.05 thresholding
    (which is what the original episodic_fraction() draft used). Testing
    thousands of candidate pairs across ~8-9 windows each multiplies the
    hypothesis count far beyond Tier 1's one-test-per-pair design; without
    correcting across that full, larger family, a naive p<0.05 cutoff would
    produce a materially inflated false-positive rate at this scale -- this
    is exactly the multiple-testing discipline production's own Tier-1
    BH-FDR step already applies, just extended to cover the much larger
    (pair x window) test count Tier 2/3 introduce.

    A pair is "episodically confirmed" if AT LEAST `min_windows_confirmed`
    of its windows survive the FDR correction -- default 1, i.e. at least
    one FDR-significant window is enough to flag the pair for inspection
    (the per-pair output reports the full window count and fraction so a
    borderline single-window hit is visibly distinguishable from a pair
    confirmed across many windows, not silently collapsed into one boolean).
    """
    if not flat_pvalue_rows:
        return []
    pvals = np.array([r["pvalue"] for r in flat_pvalue_rows])
    rejected, adjusted = _benjamini_hochberg(pvals, alpha)
    for r, rej, adj in zip(flat_pvalue_rows, rejected, adjusted):
        r["fdr_rejected"] = bool(rej)
        r["fdr_adjusted_pvalue"] = float(adj)

    by_pair = {}
    for r in flat_pvalue_rows:
        key = frozenset((r["symbol_a"], r["symbol_b"]))
        by_pair.setdefault(key, []).append(r)

    confirmed = []
    for rows in by_pair.values():
        n_rejected = sum(1 for r in rows if r["fdr_rejected"])
        if n_rejected >= min_windows_confirmed:
            confirmed.append({
                "symbol_a": rows[0]["symbol_a"], "symbol_b": rows[0]["symbol_b"],
                "n_windows_tested": len(rows),
                "n_windows_fdr_rejected": n_rejected,
                "episodic_fraction_fdr": n_rejected / len(rows),
                "min_adjusted_pvalue": min(r["fdr_adjusted_pvalue"] for r in rows),
            })
    return confirmed


def main():
    _setup_logging()
    t0 = time.time()
    log.info("=== wrds_deep_history_episodic_scan.py: does WRDS's much deeper daily history "
              "reveal cointegrated pairs yfinance's own 1D scan (0 confirmed) lacked the "
              "depth/quality to detect? ===")

    close_by_symbol, split_only_symbols = load_wrds_universe()
    if len(close_by_symbol) < 10:
        log.warning("Fewer than 10 symbols loaded -- aborting. Run data_wrds.py's full-universe "
                    "fetch first.")
        return

    # Rolling ADV liquidity gate (wired in 2026-07-27 per Ross's direction,
    # following rolling_adv_comparison.py's comparison-arm finding that a
    # flat whole-history ADV check was "false liquid" for 26.8% of real
    # (symbol, window) combinations). Separate load pass from
    # load_wrds_universe() above -- that one extracts only the price series
    # needed for cointegration; this one needs close+volume for ADV, which
    # load_wrds_universe deliberately doesn't carry.
    log.info("Building rolling ADV series for the liquidity gate (separate load pass, needs volume)...")
    ohlcv_universe = load_wrds_universe_ohlcv()
    adv_by_symbol = {sym: rolling_adv(df) for sym, df in ohlcv_universe.items()}
    log.info(f"Rolling ADV computed for {len(adv_by_symbol)} symbols "
             f"(threshold ${Config.STATS.ADV_FILTER_USD/1e6:.0f}M, applied to Tier 2/3 only -- "
             f"Tier 1's full-sample test is unchanged, production-identical)")

    log_price_df, returns = build_log_prices_and_returns(close_by_symbol)
    symbols = list(returns.columns)
    log.info(f"{len(symbols)} symbols have >=756 bars of overlapping history")

    asset_class_map = {s: "equity" for s in symbols}
    threshold = Config.UNIVERSE.MIN_PEARSON_CORR
    corr = UniverseFilter.correlation_matrix(returns.to_numpy().T)
    pairs = UniverseFilter.candidate_pairs(corr, symbols, threshold, asset_class_map)
    log.info(f"Candidate pairs at threshold {threshold}: {len(pairs)} "
             f"(Pearson pre-filter, same as production)")

    if not pairs:
        log.warning("No candidate pairs above threshold -- nothing to test further.")
        return

    results = run_full_sample_eg_pool(pairs, log_price_df, Config.ANALYSIS.EG_MAX_LAG,
                                       checkpoint_id="tier1_fullsample")
    clear_checkpoint("tier1_fullsample")

    ok_results = [r for r in results if r.get("ok")]
    by_key = {}
    for r in ok_results:
        by_key.setdefault(frozenset((r["symbol_a"], r["symbol_b"])), []).append(r)

    combined = []
    for p in pairs:
        key = frozenset((p["symbol_a"], p["symbol_b"]))
        rs = by_key.get(key)
        if not rs or len(rs) < 2:
            continue
        fwd = next((r for r in rs if r["symbol_a"] == p["symbol_a"]), None)
        rev = next((r for r in rs if r["symbol_a"] == p["symbol_b"]), None)
        if fwd is None or rev is None:
            continue
        combined.append({
            "symbol_a": p["symbol_a"], "symbol_b": p["symbol_b"],
            "pvalue": max(fwd["pvalue"], rev["pvalue"]),
            "pvalue_ab": fwd["pvalue"], "pvalue_ba": rev["pvalue"],
            "pearson_corr": p["pearson_corr"],
        })

    if not combined:
        log.warning("No pairs had usable EG results in both directions.")
        return

    pvals_arr = np.array([c["pvalue"] for c in combined])
    rejected, adjusted = _benjamini_hochberg(pvals_arr, Config.STATS.FDR_ALPHA)
    n_confirmed = int(rejected.sum())
    log.info(f"=== BH-FDR (alpha={Config.STATS.FDR_ALPHA}, m={len(combined)}): "
             f"{n_confirmed} confirmed (production's own yfinance 1D scan found 0) ===")

    rows = []
    for i, c in enumerate(combined):
        c["fdr_adjusted_pvalue"] = float(adjusted[i])
        c["fdr_confirmed"] = bool(rejected[i])
        rows.append(c)
        if rejected[i]:
            log.info(f"  CONFIRMED: {c['symbol_a']}/{c['symbol_b']}: "
                      f"p={c['pvalue']:.3e} adj={c['fdr_adjusted_pvalue']:.3e} "
                      f"corr={c['pearson_corr']:.3f}")

    # Tier 1's own post-hoc stability check for its full-sample-confirmed
    # pairs only (unchanged behavior -- see episodic_fraction's docstring for
    # why this is a stability DESCRIPTION, not the episodic DISCOVERY step).
    confirmed_rows = [r for r in rows if r["fdr_confirmed"]]
    log.info(f"[TIER 1] Computing post-hoc episodic stability ({EPISODIC_WINDOW_BARS}-bar / ~10yr "
              f"windows) for {len(confirmed_rows)} full-sample-confirmed pairs...")
    for r in confirmed_rows:
        lp_a = log_price_df[r["symbol_a"]].to_numpy()
        lp_b = log_price_df[r["symbol_b"]].to_numpy()
        frac, pvals = episodic_fraction(lp_a, lp_b, Config.ANALYSIS.EG_MAX_LAG)
        r["episodic_fraction"] = frac
        r["episodic_n_windows"] = len(pvals)
        log.info(f"  {r['symbol_a']}/{r['symbol_b']}: episodic_fraction={frac} "
                  f"over {len(pvals)} ~10yr windows")

    os.makedirs(_OUT_DIR, exist_ok=True)
    pd.DataFrame(rows).to_parquet(
        os.path.join(_OUT_DIR, "wrds_deep_history_episodic_scan_tier1.parquet"), index=False
    )
    log.info(f"[TIER 1] Saved -> output/research/wrds_deep_history_episodic_scan_tier1.parquet "
             f"({len(rows)} candidate pairs, {n_confirmed} full-sample confirmed)")

    # -------------------------------------------------------------------
    # TIER 2: same static (whole-history) correlation prefilter as Tier 1
    # (the `pairs` list already computed above), but candidate pairs go
    # STRAIGHT to rolling-window EG -- no full-sample EG gate. Isolates the
    # effect of relaxing the EG-confirmation gate alone, holding the
    # correlation prefilter fixed.
    # -------------------------------------------------------------------
    log.info(f"[TIER 2] Rolling-window EG discovery on the SAME {len(pairs)} static-corr-prefiltered "
             f"candidate pairs as Tier 1 -- no full-sample EG gate.")
    tier2_flat = run_rolling_eg_pool(pairs, log_price_df, Config.ANALYSIS.EG_MAX_LAG,
                                      adv_by_symbol=adv_by_symbol, checkpoint_id="tier2_rolling")
    clear_checkpoint("tier2_rolling")
    tier2_confirmed = episodic_bhfdr_confirm(tier2_flat, Config.STATS.FDR_ALPHA)
    log.info(f"[TIER 2] {len(tier2_flat)} (pair,window) tests -> "
             f"{len(tier2_confirmed)} episodically confirmed (>=1 FDR-rejected window)")
    for r in sorted(tier2_confirmed, key=lambda x: x["min_adjusted_pvalue"])[:20]:
        log.info(f"  [TIER 2 episodic] {r['symbol_a']}/{r['symbol_b']}: "
                 f"{r['n_windows_fdr_rejected']}/{r['n_windows_tested']} windows FDR-rejected, "
                 f"min_adj_p={r['min_adjusted_pvalue']:.3e}")
    pd.DataFrame(tier2_flat).to_parquet(
        os.path.join(_OUT_DIR, "wrds_deep_history_episodic_scan_tier2_windows.parquet"), index=False
    )
    pd.DataFrame(tier2_confirmed).to_parquet(
        os.path.join(_OUT_DIR, "wrds_deep_history_episodic_scan_tier2_confirmed.parquet"), index=False
    )
    log.info(f"[TIER 2] Saved -> output/research/wrds_deep_history_episodic_scan_tier2_{{windows,confirmed}}.parquet")

    # -------------------------------------------------------------------
    # TIER 3: rolling correlation prefilter (broader candidate set than
    # Tier 1/2's static whole-history filter) + the SAME rolling-window EG
    # discovery step as Tier 2. Isolates the ADDITIONAL effect of relaxing
    # the correlation prefilter too.
    # -------------------------------------------------------------------
    log.info("[TIER 3] Rolling correlation prefilter (pair qualifies if correlated in >=1 window, "
             "not the whole history)...")
    tier3_pairs = rolling_correlation_candidate_pairs(returns, symbols, threshold, asset_class_map)
    log.info(f"[TIER 3] {len(tier3_pairs)} candidate pairs (vs Tier 1/2's {len(pairs)} "
             f"static-corr-prefiltered pairs) -- running rolling-window EG discovery...")
    tier3_flat = run_rolling_eg_pool(tier3_pairs, log_price_df, Config.ANALYSIS.EG_MAX_LAG,
                                      adv_by_symbol=adv_by_symbol, checkpoint_id="tier3_rolling")
    clear_checkpoint("tier3_rolling")
    tier3_confirmed = episodic_bhfdr_confirm(tier3_flat, Config.STATS.FDR_ALPHA)
    log.info(f"[TIER 3] {len(tier3_flat)} (pair,window) tests -> "
             f"{len(tier3_confirmed)} episodically confirmed (>=1 FDR-rejected window)")
    for r in sorted(tier3_confirmed, key=lambda x: x["min_adjusted_pvalue"])[:20]:
        log.info(f"  [TIER 3 episodic] {r['symbol_a']}/{r['symbol_b']}: "
                 f"{r['n_windows_fdr_rejected']}/{r['n_windows_tested']} windows FDR-rejected, "
                 f"min_adj_p={r['min_adjusted_pvalue']:.3e}")
    pd.DataFrame(tier3_flat).to_parquet(
        os.path.join(_OUT_DIR, "wrds_deep_history_episodic_scan_tier3_windows.parquet"), index=False
    )
    pd.DataFrame(tier3_confirmed).to_parquet(
        os.path.join(_OUT_DIR, "wrds_deep_history_episodic_scan_tier3_confirmed.parquet"), index=False
    )
    log.info(f"[TIER 3] Saved -> output/research/wrds_deep_history_episodic_scan_tier3_{{windows,confirmed}}.parquet")

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info(f"SUMMARY: Tier 1 (full-sample) confirmed={n_confirmed} of {len(pairs)} pairs | "
             f"Tier 2 (rolling EG, static corr) episodic-confirmed={len(tier2_confirmed)} of {len(pairs)} pairs | "
             f"Tier 3 (rolling EG, rolling corr) episodic-confirmed={len(tier3_confirmed)} of {len(tier3_pairs)} pairs")
    log.info(f"wrds_deep_history_episodic_scan.py complete ({runtime:.1f} min)")


if __name__ == "__main__":
    main()
