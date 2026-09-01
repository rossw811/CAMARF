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
import gc
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
from analysis import UniverseFilter, _eg_worker, _benjamini_hochberg, CointScanner, _limit_worker_blas_threads
from research.rolling_adv_comparison import rolling_adv, load_wrds_universe_ohlcv
from data_wrds import sp500_members_asof

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WRDS_CACHE_DIR = os.path.join(_ROOT, "output", "cache", "wrds")
_OUT_DIR = os.path.join(_ROOT, "output", "research")
_SYMBOL_PERMNO_MAP_PATH = os.path.join(_WRDS_CACHE_DIR, "symbol_permno_map.parquet")
_SP500_MEMBERSHIP_PATH = os.path.join(_WRDS_CACHE_DIR, "sp500_membership_history.parquet")

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


def load_membership_gate():
    """
    Point-in-time S&P 500 index-membership gate (2026-08-11, Ross's direct
    observation): candidate generation previously loaded every symbol with
    cached WRDS price history regardless of whether it was actually an S&P
    500 member at any given historical window's date -- a symbol added to
    the index in 2022 would still get correlation/EG-tested against 2015-era
    windows, which a real deployment back then would never have screened.

    Returns (membership_df, permno_by_symbol) from the two cache files
    research/build_symbol_permno_map.py + data_wrds.py::
    fetch_sp500_membership_history already produced (both READ-ONLY here,
    NEITHER re-fetched -- membership_df was already cached 2026-07-27;
    permno_by_symbol requires a one-time live WRDS metadata query, run
    separately via `python research/build_symbol_permno_map.py`).

    Returns (None, {}) if either cache is missing -- callers must treat this
    as "membership gating unavailable, do not filter," never as "no symbols
    are eligible." Logged loudly either way so an accidentally-missing cache
    is never silently indistinguishable from "gating deliberately off."
    """
    if not os.path.exists(_SP500_MEMBERSHIP_PATH) or not os.path.exists(_SYMBOL_PERMNO_MAP_PATH):
        log.warning(
            "Point-in-time membership gate UNAVAILABLE (missing %s -- run "
            "research/build_symbol_permno_map.py first) -- candidate generation will NOT be "
            "filtered by index-membership date this run.",
            _SYMBOL_PERMNO_MAP_PATH if not os.path.exists(_SYMBOL_PERMNO_MAP_PATH) else _SP500_MEMBERSHIP_PATH,
        )
        return None, {}
    membership_df = pd.read_parquet(_SP500_MEMBERSHIP_PATH)
    permno_map_df = pd.read_parquet(_SYMBOL_PERMNO_MAP_PATH)
    permno_by_symbol = dict(zip(permno_map_df["symbol"], permno_map_df["permno"]))
    log.info(f"Point-in-time membership gate ACTIVE: {len(membership_df)} membership spells, "
             f"{len(permno_by_symbol)} symbols resolved to permnos")
    return membership_df, permno_by_symbol


def _build_member_permno_cache(membership_df, window_end_dates) -> dict:
    """Precomputes {window_end_date: set(member_permnos)} ONCE for every
    UNIQUE window_end_date that will be queried, instead of recomputing
    sp500_members_asof's full membership_df scan per (pair, window) --
    there are only ~10-20 unique window dates shared across every candidate
    pair, versus tens of thousands of (pair, window) combinations."""
    return {d: sp500_members_asof(membership_df, d) for d in set(window_end_dates)}


def load_wrds_universe():
    """Loads every fetched output/cache/wrds/*_1D.parquet file. Returns
    {symbol: close_series} using close_total_return where available (CRSP),
    falling back to split-only close otherwise (Compustat Global, not yet
    total-return-adjusted -- logged explicitly, not silently blended in)."""
    out = {}
    used_total_return = set()
    used_split_only = set()
    skipped_unreadable = []
    for f in sorted(glob.glob(os.path.join(_WRDS_CACHE_DIR, "*_1D.parquet"))):
        sym = os.path.basename(f)[: -len("_1D.parquet")]
        # Found live 2026-08-24: 1032/44694 WRDS cache files are 0-byte (an interrupted bulk
        # fetch during an earlier session crash left partial/empty files) -- a single corrupted
        # file previously crashed this WHOLE function's read loop (pyarrow.lib.ArrowInvalid),
        # taking down every downstream caller (episodic_window_size_sweep.py,
        # rolling_adv_comparison.py) over one bad symbol. Skip and log, don't crash the scan;
        # re-fetching the missing data is a separate follow-up needing live WRDS access.
        try:
            df = pd.read_parquet(f)
        except Exception as e:
            skipped_unreadable.append(sym)
            continue
        if "close_total_return" in df.columns and df["close_total_return"].notna().any():
            out[sym] = df["close_total_return"]
            used_total_return.add(sym)
        else:
            out[sym] = df["close"]
            used_split_only.add(sym)
    log.info(f"Loaded {len(out)} symbols from output/cache/wrds/: "
             f"{len(used_total_return)} total-return-adjusted (CRSP), "
             f"{len(used_split_only)} split-only-adjusted (Compustat Global, disclosed)")
    if skipped_unreadable:
        log.warning(f"Skipped {len(skipped_unreadable)} unreadable/corrupted cache files "
                    f"(0-byte or otherwise unparseable) -- re-fetch needed via live WRDS access, "
                    f"not attempted here: {skipped_unreadable[:20]}"
                    f"{'...' if len(skipped_unreadable) > 20 else ''}")
    return out, used_split_only


def build_log_prices_and_returns(close_by_symbol):
    """Aligns every symbol onto the shared calendar (union of all trading
    dates present in the loaded WRDS data) and returns (log_price_df,
    returns_df). Log returns require min 756 bars (~3yr) overlap to be
    included -- matches production's own MIN_OVERLAP_BY_TF-style floor for
    daily-ish data, not an arbitrary new choice.

    UNCHANGED since this function's original version -- kept byte-for-byte
    identical in behavior for existing callers (this script's own production
    182-pair episodic run). At the full unrestricted ~44,694-symbol scale
    (episodic_window_size_sweep.py's --full-universe mode, added 2026-08-15),
    `pd.DataFrame(close_by_symbol)`'s internal alignment genuinely OOM-crashes
    on this machine (confirmed live: "Unable to allocate 5.25 GiB for an
    array with shape (25434, 27716)") -- see build_log_prices_and_returns_
    bounded() below for the memory-safe alternative used ONLY by that new
    caller, not a replacement for this function."""
    close_df = pd.DataFrame(close_by_symbol).sort_index()
    log_price_df = np.log(close_df.astype(float))
    returns = log_price_df.diff().iloc[1:]
    valid_cols = returns.columns[returns.notna().sum() >= 756]
    return log_price_df[valid_cols], returns[valid_cols]


def build_log_prices_and_returns_bounded(close_by_symbol, lookback_years=25, dtype=np.float32):
    """Memory-bounded alternative to build_log_prices_and_returns(), built
    2026-08-15 after the plain pd.DataFrame(dict-of-Series) constructor
    OOM-crashed at the full ~44,694-symbol scale (Ross: "use the full
    universe", then "fix it properly" once the crash was found). Root cause:
    pandas' internal DataFrame-from-dict-of-Series alignment path allocates
    large intermediate blocks proportional to symbol count x full historical
    depth (some WRDS symbols have ~100 years of history), with no caller
    control over dtype or scope.

    Fixed the same way as universe_loader.align_to_common_calendar's OOM fix
    earlier this session: build ONE canonical DatetimeIndex directly via a
    fast union (np.unique(concatenate(...)), not pandas' internal merge),
    bounded to `lookback_years`, then reindex each symbol into a
    pre-allocated array of `dtype` by column -- avoids pandas' internal
    merge machinery entirely (the actual OOM site) and float32 halves the
    per-cell footprint vs the original's float64.

    lookback_years defaults to 25 -- comfortably above this sweep's own grid
    max (5040 bars ~= 20yr, DEFAULT_GRID_BARS in episodic_window_size_
    sweep.py), so no window this script actually tests ever needs history
    older than this bound; NOT the same as claiming 25y is universally
    sufficient for every possible future caller. A caller sweeping windows
    larger than ~23-24yr equivalent should widen this bound accordingly, not
    assume it's safe by default.

    Precision note, disclosed not hidden: float32 vs the original's float64
    changes results at the ~1e-7 relative precision level -- immaterial for
    EG/ADF test statistics and correlation screening at the scale this
    operates on, but a real, deliberate tradeoff, not a free lunch."""
    symbols = list(close_by_symbol.keys())
    idx_arrays = []
    for s in symbols:
        idx = close_by_symbol[s].index
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
        idx_arrays.append(idx.values)
    all_dates = np.unique(np.concatenate(idx_arrays))
    cutoff = all_dates.max() - np.timedelta64(int(lookback_years * 365.25), "D")
    all_dates = all_dates[all_dates >= cutoff]
    canonical_index = pd.DatetimeIndex(all_dates)

    log_price_arr = np.full((len(canonical_index), len(symbols)), np.nan, dtype=dtype)
    for j, s in enumerate(symbols):
        ser = close_by_symbol[s]
        if ser.index.tz is not None:
            ser = ser.copy()
            ser.index = ser.index.tz_localize(None)
        aligned = ser.reindex(canonical_index)
        # BUG-D-style pd.NA leak (same class already hit and fixed in Thread I's WRDS work,
        # 2026-08-13): some cached columns use pandas nullable dtypes (pd.NA), not plain
        # np.nan -- `aligned.values > 0` on those raises "boolean value of NA is ambiguous"
        # inside np.where, since pd.NA's __bool__ refuses to resolve to True/False. Force a
        # real float64 array FIRST (pd.NA -> np.nan under .astype("float64")) before any
        # numpy-level comparison touches it.
        vals64 = pd.to_numeric(aligned, errors="coerce").astype("float64").values
        with np.errstate(invalid="ignore", divide="ignore"):
            vals = np.where(vals64 > 0, np.log(vals64), np.nan)
        log_price_arr[:, j] = vals.astype(dtype)

    log_price_df = pd.DataFrame(log_price_arr, index=canonical_index, columns=symbols)
    # Live OOM #2 (2026-08-24, same day as the fix above): `.astype(np.float64)` here made a
    # full-width float64 COPY of log_price_df transiently coexisting with the float32 original
    # plus diff()'s own same-size output -- at 100yr lookback x 43,636 symbols this alone spiked
    # ~18GB free -> 6.84GB free in a single mem_guard poll interval (breach). diff() on the
    # float32 array directly avoids the transient upcast entirely; precision is already the
    # disclosed float32 tradeoff this function's own docstring accepts for log_price_arr itself,
    # so keeping returns at the same precision is not a new tradeoff, just a consistent one.
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


def _checkpoint_part_glob(checkpoint_id):
    return os.path.join(_OUT_DIR, f"checkpoint_{checkpoint_id}_part*.parquet")


def _load_checkpoint(checkpoint_id):
    """Loads a prior run's checkpoint (results + how many pairs were already
    processed), if one exists. Returns (results_list, n_pairs_done) --
    (None, 0) if no checkpoint is found, so callers can start clean.

    Incremental format (added 2026-08-26, after a real crash at 7.8M-pair
    Tier-3 scale -- see _save_checkpoint_batch's own docstring): reads all
    checkpoint_{id}_part*.parquet files and concatenates them, rather than
    one single ever-growing snapshot file. Falls back to the OLD single-
    snapshot format (checkpoint_{id}.parquet) if that's what's on disk --
    a run already mid-flight on the old format must still resume correctly
    from it, not be silently discarded just because the save format changed."""
    _, meta_path = _checkpoint_paths(checkpoint_id)
    if not os.path.exists(meta_path):
        return None, 0
    with open(meta_path) as f:
        n_done = int(f.read().strip())
    part_files = sorted(glob.glob(_checkpoint_part_glob(checkpoint_id)))
    if part_files:
        dfs = [pd.read_parquet(p) for p in part_files]
        records = pd.concat(dfs, ignore_index=True).to_dict("records") if dfs else []
        return records, n_done
    old_data_path = _checkpoint_paths(checkpoint_id)[0]
    if os.path.exists(old_data_path):
        return pd.read_parquet(old_data_path).to_dict("records"), n_done
    return None, 0


def _load_checkpoint_meta(checkpoint_id):
    """Lightweight resume-point lookup: reads ONLY the small `.meta` file (a
    single integer), never the potentially-huge accumulated row data.
    Returns n_pairs_done, or None if no checkpoint exists. Added 2026-08-26
    alongside the streaming-results fix in run_rolling_eg_pool -- a caller
    that only needs to know WHERE to resume from should never pay the cost
    of loading and concatenating a multi-million-row checkpoint just to
    read one number (confirmed live: at 2.4M+ already-checkpointed rows,
    that concatenation itself was a real, and growing, resume-time cost)."""
    _, meta_path = _checkpoint_paths(checkpoint_id)
    if not os.path.exists(meta_path):
        return None
    with open(meta_path) as f:
        return int(f.read().strip())


def _save_checkpoint(checkpoint_id, results, n_pairs_done):
    """Persists accumulated results + progress marker so a crash can RESUME
    from the last saved batch instead of restarting the whole run -- added
    2026-07-27 directly in response to the real BrokenProcessPool crash this
    project hit partway through Tier 1's full-sample EG step.

    ATOMIC WRITE (added 2026-08-08): writes to a `.tmp` sibling file first,
    then `os.replace()`s it onto the real path -- `os.replace` is atomic on
    both POSIX and Windows (MoveFileEx w/ MOVEFILE_REPLACE_EXISTING), so a
    process killed mid-write leaves the PREVIOUS good checkpoint intact
    rather than a truncated/corrupt file. Found the hard way running
    research/intraday_episodic_scan.py: a kill mid-`to_parquet()` left a
    4-byte unreadable checkpoint_intraday_1h_tier2.parquet while its
    sibling .meta file still said 56,500 pairs done (meta is written
    second, after the parquet write completes) -- resuming then crashed
    outright with `pyarrow.lib.ArrowInvalid` instead of just losing the
    unsaved tail, destroying everything back to the PRIOR checkpoint's
    data (parquet is written whole each call, not appended, so there was
    nothing to partially recover from the corrupt file). This exact class
    of bug is why atomic writes matter for any file a resume path depends
    on being either fully-old or fully-new, never half-written."""
    os.makedirs(_OUT_DIR, exist_ok=True)
    data_path, meta_path = _checkpoint_paths(checkpoint_id)
    data_tmp = data_path + ".tmp"
    meta_tmp = meta_path + ".tmp"
    pd.DataFrame(results).to_parquet(data_tmp, index=False)
    os.replace(data_tmp, data_path)
    with open(meta_tmp, "w") as f:
        f.write(str(n_pairs_done))
    os.replace(meta_tmp, meta_path)


def _save_checkpoint_batch(checkpoint_id, part_idx, new_rows, n_pairs_done):
    """Incremental checkpoint save (added 2026-08-26, live crash at 7.8M-pair
    Tier-3 scale): writes ONLY the rows computed since the last checkpoint
    to a new, uniquely-numbered part file, instead of _save_checkpoint's
    re-serialize-the-ENTIRE-accumulated-history-every-time behavior. Found
    live on CachyOS: at 815,500/7,834,906 Tier-3 pairs already done, that
    full-history reserialization was already large enough (several million
    accumulated rows) to spike memory ~2.6GB in a single checkpoint write
    and breach the mem_guard floor -- memory had been flat/stable for a long
    stretch of real batch processing right up until that one write. This
    cost only grows as a run progresses further, so a fixed memory floor can
    never be a durable fix against it -- the actual write volume per
    checkpoint needed to stop growing. Same per-batch-file pattern already
    proven elsewhere in this codebase (fund_membership_checkpoints/
    batch_N.parquet), reused rather than inventing a new scheme. Same atomic
    -write discipline as _save_checkpoint (`.tmp` + os.replace)."""
    os.makedirs(_OUT_DIR, exist_ok=True)
    _, meta_path = _checkpoint_paths(checkpoint_id)
    part_path = os.path.join(_OUT_DIR, f"checkpoint_{checkpoint_id}_part{part_idx:06d}.parquet")
    part_tmp = part_path + ".tmp"
    meta_tmp = meta_path + ".tmp"
    pd.DataFrame(new_rows).to_parquet(part_tmp, index=False)
    os.replace(part_tmp, part_path)
    with open(meta_tmp, "w") as f:
        f.write(str(n_pairs_done))
    os.replace(meta_tmp, meta_path)


def clear_checkpoint(checkpoint_id):
    """Deletes a checkpoint's files (both the old single-snapshot format and
    any new incremental part files) -- call after a run completes
    successfully, so a later, unrelated invocation doesn't accidentally
    resume from stale progress."""
    data_path, meta_path = _checkpoint_paths(checkpoint_id)
    for p in [data_path, meta_path] + glob.glob(_checkpoint_part_glob(checkpoint_id)):
        if os.path.exists(p):
            os.remove(p)


def run_full_sample_eg_pool(pairs, log_price_df, max_lag, workers=Config.RUNTIME.N_WORKERS, pair_batch_size=5000,
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
    # initializer=_limit_worker_blas_threads (2026-08-26, found live on CachyOS during this exact
    # run): load average was 35.25 on a 16-core machine (2.2x oversubscribed) -- the SAME
    # ProcessPoolExecutor-plus-unthrottled-BLAS trap analysis.py's own EG pools were already fixed
    # for earlier this session (measured there: load avg 45->12-18, a stage going from "never
    # finishing" to 46 minutes). This script's pools never got that fix. Reused, not duplicated.
    with ProcessPoolExecutor(max_workers=workers, initializer=_limit_worker_blas_threads) as pool:
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
                                         window=EPISODIC_WINDOW_BARS, step=EPISODIC_STEP_BARS,
                                         chunk_batch_size=None):
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

    chunk_batch_size (added 2026-08-16, default None = original unchunked
    behavior, UNCHANGED for existing callers -- this project's own already-
    validated 182-pair production episodic run never sets this): when given,
    routes each window's correlation step through UniverseFilter.
    chunked_pearson_candidate_pairs() instead of the direct correlation_
    matrix() call. Needed at the full ~18,283-symbol universe scope
    (episodic_window_size_sweep.py --full-universe) -- the direct call
    OOM-crashed on its first window ("Unable to allocate 2.49 GiB for an
    array with shape (18283, 18283)"), since this function calls the full
    dense N x N correlation step ONCE PER ROLLING WINDOW (potentially dozens
    of times per grid point), not once per run the way the one-time
    full-universe correlation screen does.

    BUG-D112 fix (2026-08-11): each returned pair now also carries
    `first_qualified_window_end_date` -- the EARLIEST window's own
    `window_end_date` (via `returns_df`'s DatetimeIndex, matching
    build_rolling_eg_tasks' own window_end_date convention exactly) at
    which that pair first cleared `threshold`. This is tracked SEPARATELY
    from `pearson_corr` (which stays the BEST correlation seen, for
    reporting) -- the two can point at different windows, so overwriting
    one into the other was the root of the original lookahead bug: a
    pair's best-correlation window could be a LATE one while its
    first-qualifying window is earlier, or vice versa; only the earliest
    qualifying date is what makes candidacy causal. Consumed by
    build_rolling_eg_tasks below to gate which windows a pair is even
    ELIGIBLE to be EG-tested on.
    """
    returns_arr = returns_df.to_numpy()
    n = len(returns_arr)
    union_pairs = {}
    first_qualified = {}
    n_windows = 0
    for start in range(0, n - window + 1, step):
        seg = returns_arr[start:start + window]
        window_end_date = returns_df.index[start + window - 1]
        if chunk_batch_size:
            window_pairs = UniverseFilter.chunked_pearson_candidate_pairs(
                seg.T, symbols, threshold, asset_class_map, batch_size=chunk_batch_size,
                progress_every=10, progress_label=f"window end={window_end_date.date()} ",
            )
        else:
            corr = UniverseFilter.correlation_matrix(seg.T)
            window_pairs = UniverseFilter.candidate_pairs(corr, symbols, threshold, asset_class_map)
        n_windows += 1
        log.info(f"  Rolling correlation: window {n_windows} (end={window_end_date.date()}) -- "
                 f"{len(window_pairs)} pairs qualify")
        for p in window_pairs:
            key = frozenset((p["symbol_a"], p["symbol_b"]))
            if key not in union_pairs or p["pearson_corr"] > union_pairs[key]["pearson_corr"]:
                union_pairs[key] = p
            if key not in first_qualified or window_end_date < first_qualified[key]:
                first_qualified[key] = window_end_date
    for key, p in union_pairs.items():
        p["first_qualified_window_end_date"] = first_qualified[key]
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
                           adv_by_symbol=None, adv_threshold=None, array_cache=None,
                           membership_df=None, permno_by_symbol=None):
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

    Point-in-time index-membership gate (2026-08-11, see load_membership_gate):
    if BOTH `membership_df` and `permno_by_symbol` are provided, a window is
    only tested if BOTH symbols were resolved to a permno AND that permno
    was an S&P 500 member as of the window's OWN end date (via
    data_wrds.sp500_members_asof, memoized per unique date within this call
    -- only ~10-20 unique window dates are ever queried, not one lookup per
    (pair, window)). A symbol with no permno resolution is NOT excluded by
    this gate (unresolved != ineligible -- see load_membership_gate's own
    docstring); it simply isn't checked. Defaults to (None, None) so
    existing callers/tests that don't pass these are unaffected.
    """
    tasks, task_meta = [], []
    thr = adv_threshold if adv_threshold is not None else Config.STATS.ADV_FILTER_USD
    n_gated = 0
    n_causally_gated = 0
    n_membership_gated = 0
    _member_cache: dict = {}
    for p in pairs:
        sym_a, sym_b = p["symbol_a"], p["symbol_b"]
        permno_a = permno_by_symbol.get(sym_a) if permno_by_symbol else None
        permno_b = permno_by_symbol.get(sym_b) if permno_by_symbol else None
        if array_cache is not None:
            lp_a, lp_b = array_cache[sym_a], array_cache[sym_b]
        else:
            lp_a = log_price_df[sym_a].to_numpy()
            lp_b = log_price_df[sym_b].to_numpy()
        mask = np.isfinite(lp_a) & np.isfinite(lp_b)
        a, b = lp_a[mask], lp_b[mask]
        # ALWAYS compute dates_masked, not just when adv_by_symbol is given
        # (2026-08-02, BUG-episodic-PIT fix) -- window_start_date/window_end_date
        # are now attached to every task's meta so a genuinely point-in-time
        # confirmation (episodic_bhfdr_confirm_asof, below) is possible. Prior
        # version only computed real calendar dates transiently inside the
        # ADV-gate branch and never persisted them, so a window's actual date
        # never survived past this function -- confirmed via docs/HANDOFF.md's
        # explicit flag of this exact gap.
        dates_masked = log_price_df.index[mask]
        n = len(a)
        if n < window:
            continue
        # BUG-D112 fix (2026-08-11): if this pair carries a
        # first_qualified_window_end_date (Tier 3's causal candidacy date --
        # absent for Tier 1/2, which use a single whole-history filter and
        # are NOT gated here, unchanged behavior), skip any window that
        # concluded BEFORE the pair first qualified as a candidate. A real
        # deployment at that early date would never have proposed this pair
        # for EG testing at all.
        pair_first_qualified = p.get("first_qualified_window_end_date")
        for start in range(0, n - window + 1, step):
            window_start_date = dates_masked[start]
            window_end_date = dates_masked[start + window - 1]
            if pair_first_qualified is not None and window_end_date < pair_first_qualified:
                n_causally_gated += 1
                continue
            if membership_df is not None and permno_a is not None and permno_b is not None:
                members = _member_cache.get(window_end_date)
                if members is None:
                    members = sp500_members_asof(membership_df, window_end_date)
                    _member_cache[window_end_date] = members
                if permno_a not in members or permno_b not in members:
                    n_membership_gated += 1
                    continue
            if adv_by_symbol is not None:
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
            task_meta.append((sym_a, sym_b, start, "ab", window_start_date, window_end_date))
            tasks.append((sym_b, sym_a, seg_b, seg_a, max_lag, TF_LABEL))
            task_meta.append((sym_a, sym_b, start, "ba", window_start_date, window_end_date))
    if adv_by_symbol is not None:
        log.info(f"  ADV liquidity gate: skipped {n_gated} (pair, window) combinations where "
                 f"either symbol's rolling ADV was below ${thr/1e6:.0f}M at that window's start date")
    if n_causally_gated:
        log.info(f"  BUG-D112 causal-candidacy gate: skipped {n_causally_gated} (pair, window) "
                 f"combinations dated before that pair's first_qualified_window_end_date")
    if membership_df is not None:
        log.info(f"  Point-in-time S&P 500 membership gate: skipped {n_membership_gated} "
                 f"(pair, window) combinations where either symbol was not an index member "
                 f"as of that window's end date")
    return tasks, task_meta


def run_rolling_eg_pool(pairs, log_price_df, max_lag, window=EPISODIC_WINDOW_BARS,
                         step=EPISODIC_STEP_BARS, workers=Config.RUNTIME.N_WORKERS, adv_by_symbol=None, adv_threshold=None,
                         pair_batch_size=500, checkpoint_id=None, checkpoint_every=10,
                         membership_df=None, permno_by_symbol=None):
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

    STREAMING RESULTS (added 2026-08-26, after a second, more severe live
    incident at 7.8M Tier-3 pairs): the original checkpointing above still
    kept `by_key`/`window_end_by_key` fully in memory for the ENTIRE run
    (needed only to build the final `flat` return value at the end) -- an
    unbounded, ever-growing cost as a run progresses. Confirmed live: crash
    frequency got WORSE, not better, the deeper into the run it got (every
    ~5 minutes at 2.4M/7.8M pairs done, vs. long stable stretches earlier),
    because this accumulator kept growing regardless of the earlier
    checkpoint-WRITE fix (which only bounded `pending_new_rows` between
    saves, not this separate structure). Since build_rolling_eg_tasks always
    builds BOTH directions of a pair in the SAME batch, `by_key` never
    actually needed cross-batch persistence for correctness -- only for
    reconstruction, which is now instead read back from the already-
    checkpointed part files at the very end (`_load_checkpoint`, the same
    mechanism a resumed run already uses), never held in memory meanwhile.
    Only engages when `checkpoint_id` is given (every real production
    caller); smaller one-off callers with no checkpoint_id keep the
    original in-memory accumulator, since their scale never needed this.
    """
    all_symbols = {p["symbol_a"] for p in pairs} | {p["symbol_b"] for p in pairs}
    array_cache = _build_symbol_array_cache(log_price_df, all_symbols)

    # Streaming results (2026-08-26, replacing the always-in-memory `by_key`/`window_end_by_key`
    # accumulator for checkpointed callers -- live incident: at 7.8M Tier-3 pairs, crashes got
    # MORE frequent, not less, the deeper into the run it got, because this accumulator held
    # EVERY processed pair's result for the ENTIRE run, needed only to build the final `flat`
    # return value -- an unbounded, ever-growing cost, separate from (and not fixed by) the
    # earlier checkpoint-WRITE fix, which only bounded `pending_new_rows` between saves, not this.
    # Since build_rolling_eg_tasks always builds BOTH directions of a pair in the SAME batch, no
    # cross-batch persistence is actually needed for correctness -- only for reconstructing the
    # final flat list, which is instead read back from the already-checkpointed part files at the
    # very end (same mechanism _load_checkpoint already uses for resuming), never held in memory
    # meanwhile. Only used when checkpoint_id is given (every real production caller); smaller,
    # one-off callers with no checkpoint_id (some debug/verify scripts, episodic_window_size_
    # sweep.py) keep the simpler in-memory accumulator -- their scale never needed this.
    use_streaming = checkpoint_id is not None
    by_key = {}
    window_end_by_key = {}  # (symbol_a, symbol_b, window_start) -> window_end_date, for asof(T) confirmation
    start_pair_idx = 0
    if checkpoint_id:
        n_done = _load_checkpoint_meta(checkpoint_id)
        if n_done is not None:
            start_pair_idx = n_done
            log.info(f"Resuming '{checkpoint_id}' from checkpoint: {n_done}/{len(pairs)} pairs "
                     f"already done -- skipping to pair {n_done}. (Row data reconstructed from "
                     f"disk at the end, not loaded into memory now.)")

    # Incremental checkpointing (2026-08-26, see _save_checkpoint_batch's own docstring): only
    # the rows computed SINCE the last flush are kept in `pending_new_rows` and written out, never
    # the full accumulated `by_key` history -- part_idx starts past whatever part files a resumed
    # run already has on disk, so a resume never overwrites earlier parts.
    pending_new_rows = []
    part_idx = len(glob.glob(_checkpoint_part_glob(checkpoint_id))) if checkpoint_id else 0

    def _flatten_by_key(d):
        return [{"symbol_a": k[0], "symbol_b": k[1], "window_start": k[2], "direction": direction,
                 "pvalue": pval, "window_end_date": window_end_by_key.get(k)}
                for k, dirs in d.items() for direction, pval in dirs.items()]

    n_batches = (len(pairs) + pair_batch_size - 1) // pair_batch_size
    log.info(f"Running rolling-window EG on {len(pairs)} pairs in {n_batches} batches of "
             f"<={pair_batch_size} pairs each (workers={workers})...")
    t0 = time.time()
    # initializer=_limit_worker_blas_threads (2026-08-26, found live on CachyOS during this exact
    # run): load average was 35.25 on a 16-core machine (2.2x oversubscribed) -- the SAME
    # ProcessPoolExecutor-plus-unthrottled-BLAS trap analysis.py's own EG pools were already fixed
    # for earlier this session (measured there: load avg 45->12-18, a stage going from "never
    # finishing" to 46 minutes). This script's pools never got that fix. Reused, not duplicated.
    with ProcessPoolExecutor(max_workers=workers, initializer=_limit_worker_blas_threads) as pool:
        for batch_num, i in enumerate(range(start_pair_idx, len(pairs), pair_batch_size)):
            batch_pairs = pairs[i:i + pair_batch_size]
            tasks, task_meta = build_rolling_eg_tasks(
                batch_pairs, log_price_df, max_lag, window, step,
                adv_by_symbol=adv_by_symbol, adv_threshold=adv_threshold, array_cache=array_cache,
                membership_df=membership_df, permno_by_symbol=permno_by_symbol,
            )
            n_done_now = i + len(batch_pairs)
            if not tasks:
                if checkpoint_id and batch_num % checkpoint_every == 0 and pending_new_rows:
                    _save_checkpoint_batch(checkpoint_id, part_idx, pending_new_rows, n_done_now)
                    part_idx += 1
                    pending_new_rows = []
                continue
            results = pool.map(_eg_worker, tasks, chunksize=200)
            for meta, r in zip(task_meta, results):
                symbol_a, symbol_b, start, direction, window_start_date, window_end_date = meta
                if not r.get("ok"):
                    continue
                if not use_streaming:
                    key = (symbol_a, symbol_b, start)
                    by_key.setdefault(key, {})[direction] = r["pvalue"]
                    window_end_by_key[key] = window_end_date
                pending_new_rows.append({"symbol_a": symbol_a, "symbol_b": symbol_b,
                                          "window_start": start, "direction": direction,
                                          "pvalue": r["pvalue"], "window_end_date": window_end_date})
            if checkpoint_id and batch_num % checkpoint_every == 0 and pending_new_rows:
                _save_checkpoint_batch(checkpoint_id, part_idx, pending_new_rows, n_done_now)
                part_idx += 1
                pending_new_rows = []
            if (i // pair_batch_size) % 10 == 0:
                log.info(f"  batch (pairs {i}-{n_done_now}/{len(pairs)}) done "
                         f"({(time.time()-t0)/60:.1f} min elapsed)")
    if checkpoint_id and pending_new_rows:
        _save_checkpoint_batch(checkpoint_id, part_idx, pending_new_rows, len(pairs))
    log.info(f"  done in {(time.time()-t0)/60:.1f} min")

    # Reconstruct the final result from disk (streaming path only) -- a ONE-TIME cost paid once
    # at the very end, not compounding throughout the run the way the old always-in-memory
    # accumulator did. The function's own return contract already requires holding the full
    # flattened result in memory for the caller regardless (main() runs BH-FDR and saves it right
    # after) -- this doesn't add a new burden, it just relocates the existing one to a single
    # point instead of letting it grow continuously mid-run.
    if use_streaming:
        loaded, _ = _load_checkpoint(checkpoint_id)
        by_key = {}
        window_end_by_key = {}
        for row in (loaded or []):
            key = (row["symbol_a"], row["symbol_b"], row["window_start"])
            by_key.setdefault(key, {})[row["direction"]] = row["pvalue"]
            if row.get("window_end_date") is not None:
                window_end_by_key[key] = row["window_end_date"]

    flat = []
    for (symbol_a, symbol_b, start), d in by_key.items():
        if "ab" in d and "ba" in d:
            flat.append({"symbol_a": symbol_a, "symbol_b": symbol_b,
                         "window_start": start, "pvalue": max(d["ab"], d["ba"]),
                         "window_end_date": window_end_by_key.get((symbol_a, symbol_b, start))})
    return flat


def episodic_bhfdr_confirm(flat_pvalue_rows, alpha, min_windows_confirmed=1):
    """
    NOT POINT-IN-TIME-SAFE (disclosed 2026-08-02, per docs/HANDOFF.md's flagged
    gap): this collapses across EVERY historical window regardless of date --
    "was this pair EVER confirmed in any window," not "as of date T, using
    only windows already concluded by T." Fine as a descriptive whole-history
    stability check (same spirit as Tier 1's own full-sample EG gate); NOT
    fine as an input to any backtest or live decision, which needs
    episodic_bhfdr_confirm_asof (below) instead. Kept as-is (not removed) --
    nothing downstream currently consumes either function's output (confirmed
    via repo-wide grep), so this is not a live bug, and the whole-history
    version remains a legitimate question in its own right.

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


def episodic_bhfdr_confirm_asof(flat_pvalue_rows, alpha, as_of_date, min_windows_confirmed=1):
    """
    POINT-IN-TIME-SAFE episodic confirmation (2026-08-02) -- "as of date T,
    would this pair have been episodically confirmed using only windows that
    had ALREADY CONCLUDED by T?" This is the causal question
    episodic_bhfdr_confirm (above) cannot answer, per Ross's own framing of
    the underlying bias: "for rolling windows it must always be rolling up to
    that point" (docs/HANDOFF.md).

    A window "concludes" at its own last bar (window_end_date), not its start
    -- a window whose start is before T but whose end is after T still uses
    data a real deployment at time T would not yet have. Rows missing
    window_end_date (e.g. loaded from a pre-fix checkpoint) are excluded
    rather than silently treated as eligible.

    Applies the SAME joint BH-FDR correction as episodic_bhfdr_confirm, but
    over only the as-of-T-eligible subset of the test family -- the
    correction's multiple-testing universe genuinely shrinks as T moves
    earlier, which is the correct causal behavior (a real deployment at an
    early T could not have run tests it hadn't collected the data for yet).
    """
    eligible = [r for r in flat_pvalue_rows
                if r.get("window_end_date") is not None and r["window_end_date"] <= as_of_date]
    confirmed = episodic_bhfdr_confirm(eligible, alpha, min_windows_confirmed)
    for c in confirmed:
        c["as_of_date"] = as_of_date
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

    # Point-in-time S&P 500 membership gate (2026-08-11) -- applied to Tier 2/3
    # only, same scope as the ADV gate above; Tier 1's full-sample test is
    # unchanged, production-identical.
    membership_df, permno_by_symbol = load_membership_gate()

    # Bounded builder (2026-08-24): the plain build_log_prices_and_returns() OOM-crashed live
    # here tonight (mem_guard floor breach, 26GB free -> 13GB free in under a minute) -- the SAME
    # already-diagnosed pandas dict-of-Series alignment OOM this function's own docstring
    # documents ("Unable to allocate 5.25 GiB for an array with shape (25434, 27716)"), now hit
    # by this script's own main() at the real ~43,662-symbol WRDS universe scale (previously this
    # scope was ~1,500 symbols per the module docstring above -- stale as of the WRDS bulk fetch's
    # growth this session).
    #
    # lookback_years=100 was tried FIRST and also OOM-crashed (18GB free -> 6.84GB free in one
    # mem_guard poll, same night) -- the canonical_index length here is driven by the OLDEST
    # single symbol's earliest date across all 43,636 symbols (a handful of outlier long-history
    # names), not the typical symbol, so a 100yr bound produces a ~25,000-row index even though
    # the overwhelming majority of symbols are NaN for most of that span -- combined with the
    # (also since-fixed) float64 upcast in build_log_prices_and_returns_bounded's own returns.diff()
    # call, peak transient memory for log_price_arr+returns alone approached ~20GB+. Reduced to
    # lookback_years=50: still >2x yfinance's typical ~20-30yr depth (preserving this script's
    # actual hypothesis -- does WRDS's deeper history reveal pairs yfinance's shorter history
    # missed), while roughly halving canonical_index length. Combined with the diff() dtype fix
    # (see that function's own updated docstring/comment), this keeps the two-array peak in the
    # single-digit GB.
    log_price_df, returns = build_log_prices_and_returns_bounded(close_by_symbol, lookback_years=50)
    symbols = list(returns.columns)
    log.info(f"{len(symbols)} symbols have >=756 bars of overlapping history")

    # Third OOM crash tonight, live (2026-08-25): the SAME construction step above crashed again
    # (16.12GB free -> 13.17GB free in one poll) despite succeeding cleanly on an earlier launch
    # -- baseline system memory had shifted (desktop session active this time) leaving less
    # headroom, tipping an already-marginal peak over the floor. Root cause, previously missed:
    # `close_by_symbol` (raw per-symbol daily Series for all 43,636 symbols, up to 100yr each --
    # confirmed via grep, ~9-17GB realistic estimate) is loaded at this function's start and never
    # referenced again anywhere in main() after the line above -- everything downstream (Tier
    # 1/2/3) uses log_price_df/returns/symbols instead. It was staying fully resident for the
    # ENTIRE multi-hour rest of the run regardless, wasting real headroom rather than depending on
    # a lucky baseline. Freeing it here is a genuine fix, not a gamble on quiet system conditions.
    del close_by_symbol
    gc.collect()

    asset_class_map = {s: "equity" for s in symbols}
    threshold = Config.UNIVERSE.MIN_PEARSON_CORR

    # Cross-launch resume (added 2026-08-25, live crash-recovery gap found this same night):
    # Tier 1 alone took ~4h34m (correlation chunking + the full-sample EG pool) on its successful
    # 3rd launch, but a later mem_guard floor breach DURING TIER 2 killed the whole process --
    # main() has no "skip a tier whose output already exists" check, so a naive relaunch would
    # have silently redone all 4h34m of already-completed, already-saved Tier 1 work before ever
    # reaching Tier 2's own within-tier checkpoint (checkpoint_id="tier2_rolling", which DOES
    # resume correctly -- this gap was specifically the missing ACROSS-tier equivalent). Only
    # symbol_a/symbol_b/pearson_corr are ever read from `pairs` by any downstream code (confirmed
    # via grep) -- Tier 1's own saved output already carries exactly those three columns, so
    # reconstructing `pairs` from it is lossless. Delete the output file first to force a genuine
    # from-scratch Tier 1 re-run.
    _tier1_output_path = os.path.join(_OUT_DIR, "wrds_deep_history_episodic_scan_tier1.parquet")
    if os.path.exists(_tier1_output_path):
        log.info(f"[TIER 1] Found existing output at {_tier1_output_path} -- resuming from it "
                 f"instead of re-running correlation+EG from scratch. Delete this file first to "
                 f"force a genuine re-run.")
        tier1_df = pd.read_parquet(_tier1_output_path)
        pairs = tier1_df[["symbol_a", "symbol_b", "pearson_corr"]].to_dict("records")
        n_confirmed = int(tier1_df["fdr_confirmed"].sum())
        log.info(f"[TIER 1] Loaded {len(pairs)} candidate pairs, {n_confirmed} full-sample "
                 f"confirmed (from existing file, not recomputed)")
    else:
        # Chunked (2026-08-24): direct correlation_matrix() on the full ~44,700-symbol universe
        # allocates ~8 co-existing (N,N) float64 arrays in _vectorized_pairwise_stats -- the same
        # OOM class chunked_pearson_candidate_pairs was built for (see its own docstring, "Unable
        # to allocate 2.49 GiB for an array with shape (18283, 18283)" at 18,283 symbols; this
        # universe is now ~44,700). batch_size=1500 keeps peak per-block memory in the tens of MB
        # regardless of total universe size, well inside the ~32GB ceiling.
        pairs = UniverseFilter.chunked_pearson_candidate_pairs(
            returns.to_numpy().T, symbols, threshold, asset_class_map,
            batch_size=1500, progress_every=25, progress_label="tier1 ",
        )
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
    # Cross-launch resume for Tier 2, matching Tier 1's own pattern (added 2026-08-26 --
    # this exact gap kept costing a full ~1hr Tier-2 re-run every time a LATER stage, Tier 3's
    # EG-testing, crashed and forced a relaunch, even though Tier 2 itself had already completed
    # and saved cleanly each time. Only `tier2_flat` (raw pvalue rows) needs to survive --
    # `episodic_bhfdr_confirm` is cheap to recompute from it, not worth caching separately.
    _tier2_windows_path = os.path.join(_OUT_DIR, "wrds_deep_history_episodic_scan_tier2_windows.parquet")
    if os.path.exists(_tier2_windows_path):
        log.info(f"[TIER 2] Found existing output at {_tier2_windows_path} -- resuming from it "
                 f"instead of re-running rolling EG from scratch. Delete this file first to force "
                 f"a genuine re-run.")
        tier2_flat = pd.read_parquet(_tier2_windows_path).to_dict("records")
    else:
        log.info(f"[TIER 2] Rolling-window EG discovery on the SAME {len(pairs)} static-corr-prefiltered "
                 f"candidate pairs as Tier 1 -- no full-sample EG gate.")
        tier2_flat = run_rolling_eg_pool(pairs, log_price_df, Config.ANALYSIS.EG_MAX_LAG,
                                          adv_by_symbol=adv_by_symbol, checkpoint_id="tier2_rolling",
                                          membership_df=membership_df, permno_by_symbol=permno_by_symbol)
        clear_checkpoint("tier2_rolling")
        os.makedirs(_OUT_DIR, exist_ok=True)
        pd.DataFrame(tier2_flat).to_parquet(_tier2_windows_path, index=False)
    tier2_confirmed = episodic_bhfdr_confirm(tier2_flat, Config.STATS.FDR_ALPHA)
    log.info(f"[TIER 2] {len(tier2_flat)} (pair,window) tests -> "
             f"{len(tier2_confirmed)} episodically confirmed (>=1 FDR-rejected window)")
    for r in sorted(tier2_confirmed, key=lambda x: x["min_adjusted_pvalue"])[:20]:
        log.info(f"  [TIER 2 episodic] {r['symbol_a']}/{r['symbol_b']}: "
                 f"{r['n_windows_fdr_rejected']}/{r['n_windows_tested']} windows FDR-rejected, "
                 f"min_adj_p={r['min_adjusted_pvalue']:.3e}")
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
    # Cross-launch resume for the correlation-prefilter phase itself (added 2026-08-25, live loss
    # this same night): the rolling correlation prefilter took ~8h34m (all 45 windows, ending at
    # the present day) and found 7,834,906 candidate pairs, but a mem_guard floor breach hit
    # IMMEDIATELY on transitioning into run_rolling_eg_pool below -- and `tier3_pairs` was never
    # written to disk anywhere before that point, so the entire 8.5-hour correlation phase was
    # lost outright on relaunch (Tier 1 already had this exact protection via its own resume-skip
    # a few hours earlier tonight; this phase did not, and paid for it). Fixed the same way: save
    # `tier3_pairs` to its own checkpoint file immediately after computing it, and skip
    # recomputation on a future relaunch if that file already exists.
    _tier3_pairs_path = os.path.join(_OUT_DIR, "wrds_deep_history_episodic_scan_tier3_pairs.parquet")
    if os.path.exists(_tier3_pairs_path):
        log.info(f"[TIER 3] Found existing candidate-pairs cache at {_tier3_pairs_path} -- "
                 f"resuming from it instead of re-running the multi-hour rolling correlation "
                 f"prefilter. Delete this file first to force a genuine re-run.")
        tier3_pairs = pd.read_parquet(_tier3_pairs_path).to_dict("records")
    else:
        log.info("[TIER 3] Rolling correlation prefilter (pair qualifies if correlated in >=1 "
                 "window, not the whole history)...")
        # chunk_batch_size=1500 (2026-08-24): this calls the full N x N correlation step ONCE PER
        # ROLLING WINDOW (potentially dozens of times) at the real ~44,700-symbol universe scale
        # -- the unchunked default is exactly the OOM class this function's own chunked_pearson_
        # candidate_pairs path was built for (see its docstring). Was silently defaulting to
        # chunk_batch_size=None (unchunked) since no caller ever passed it.
        tier3_pairs = rolling_correlation_candidate_pairs(
            returns, symbols, threshold, asset_class_map, chunk_batch_size=1500,
        )
        os.makedirs(_OUT_DIR, exist_ok=True)
        pd.DataFrame(tier3_pairs).to_parquet(_tier3_pairs_path, index=False)
        log.info(f"[TIER 3] Checkpointed {len(tier3_pairs)} candidate pairs -> {_tier3_pairs_path} "
                 f"BEFORE starting EG-testing, so a crash during that phase doesn't lose this "
                 f"one again.")
    log.info(f"[TIER 3] {len(tier3_pairs)} candidate pairs (vs Tier 1/2's {len(pairs)} "
             f"static-corr-prefiltered pairs) -- running rolling-window EG discovery...")
    # Second floor breach at this exact transition, live (2026-08-26): `returns` (the OTHER big
    # float32 array, same size as log_price_df, ~1.5GB+) has NO remaining use anywhere past this
    # point (confirmed via grep -- its only two call sites are Tier 1's and Tier 3's own
    # correlation-prefilter branches above, BOTH of which are skipped entirely when their resume
    # caches exist, exactly what happened on this run). It was sitting resident, unused, through
    # all of Tier 2 and into Tier 3's EG-testing pool spin-up (which ALSO builds a second
    # near-full-universe-sized array_cache via _build_symbol_array_cache at 7.8M pairs' worth of
    # unique symbols) -- real, avoidable headroom lost right when this stage needs it most.
    del returns
    gc.collect()
    tier3_flat = run_rolling_eg_pool(tier3_pairs, log_price_df, Config.ANALYSIS.EG_MAX_LAG,
                                      adv_by_symbol=adv_by_symbol, checkpoint_id="tier3_rolling",
                                      membership_df=membership_df, permno_by_symbol=permno_by_symbol)
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
