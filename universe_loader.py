"""
universe_loader.py -- canonical, shared "load the full universe" utility.

Built 2026-08-14 per Ross's direct instruction: "everywhere with load full
universe needs to load everything, including the IBKR, binance, and wrds."

Real problem this fixes: at least 4 research/*.py scripts each independently
defined their OWN `load_full_universe(suffix)` function (k_bahc_candidate_
discovery.py, fdr_method_comparison.py, pearson_threshold_sensitivity.py,
tail_dependence_universe_screen.py), and EVERY one of them only scanned
Config.DATA.CACHE_DIR (the original yfinance-based S&P Composite 1500
cache, ~1,700 symbols) -- none of them ever saw Thread K Part 1's full US
market fetch (29,366 symbols, `output/cache/wrds/`), Thread I's
international liquid universe (2,930 symbols, same directory, GVKEY-
prefixed labels), or the Binance crypto cache (`output/cache/binance/`).
Re-running any of these scripts today, even after the universe expansion,
was mechanically incapable of using the new data -- confirmed directly
(2026-08-14 k-BAHC re-runs loaded 1573-1730 symbols, essentially the SAME
old universe size, not the expected ~32,000+).

REVISED 2026-08-14 (Ross, directly): "i'm fine with using IBKR for the
intraday data." CLAUDE.md's rule 2 originally scoped `data_ibkr.py` as
confirmed-pairs-only deep history, motivated by an earlier session's real
instability incidents (see CLAUDE.md's own "Session 5-7 bug registry"
reference) -- that rule is now DELIBERATELY RELAXED, not silently ignored:
WRDS/CRSP now covers the DAILY equity case IBKR was originally the only
source for, but WRDS's own table used this session (`crsp_a_stock.dsf_v2`)
is daily-only -- IBKR's real remaining value is INTRADAY granularity
(15min/1hr/4hr/30min/5min/1min, confirmed directly: 539 real cached files,
92 distinct symbols) that neither WRDS nor the yfinance cache provides at
that resolution. Included here as a real discovery-universe source for
intraday timeframes. CLAUDE.md rule 2 updated to match (see that file).

Checked directly, not assumed (2026-08-14): despite an earlier belief that
IBKR was also a source for forex/commodities data, the real cache and
`data_ibkr.py`'s own code contain ZERO forex/commodity symbols or fetch
logic -- confirmed via a direct grep of all 539 cached files and the
module's source. Forex/commodities remain a genuinely separate, unbuilt
need (see Development.md's 2026-08-14 entry for the real WRDS-capability
investigation) -- NOT silently assumed solved by this IBKR inclusion.

Real memory constraint, checked directly on this machine (2026-08-14): 5GB
free / 15.6GB total RAM. A float64 N x N correlation matrix at the full
combined scale (~32,296 symbols) is ~8.3GB by itself -- before the returns
matrix, DataAligner overhead, or anything else. `load_full_universe` itself
just loads price DataFrames (memory-cheap, one Parquet file per symbol);
callers doing an O(N^2) correlation-matrix step on the FULL merged universe
must size that separately (float32, chunking, or a staged/bounded subset)
-- this loader does not attempt to solve that on its own.
"""
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from config import Config

# Real bottleneck found and fixed 2026-08-14: at the full merged-universe scale
# (44,694 WRDS files alone), sequential one-at-a-time pd.read_parquet() calls
# took well over 5 minutes just to LOAD the universe, before any correlation
# computation even started (confirmed directly -- a timed run sat on "Loading
# full merged universe..." with zero progress for 5+ minutes). Each read_parquet
# call carries real fixed overhead (file open, parquet metadata parse) that
# dominates at this file count; parallelizing the I/O (these are I/O-bound
# reads, not CPU-bound, so threads -- not processes -- are the right tool, no
# GIL contention concern for file I/O) is the real fix, not a workaround.
_IO_WORKERS = 16

_YF_CACHE_DIR = Config.DATA.CACHE_DIR
_WRDS_CACHE_DIR = os.path.join("output", "cache", "wrds")
_BINANCE_CACHE_DIR = os.path.join("output", "cache", "binance")
_IBKR_CACHE_DIR = os.path.join("output", "cache", "ibkr_supplement")
# IBKR files are named "{symbol}_{suffix}_deep.parquet", not "{symbol}_{suffix}.parquet"
# like every other source -- handled via _ibkr_deep_suffix below, not the shared _load_dir.
_IBKR_FILE_SUFFIX = "_deep"

# Canonical timeframe label -> each source's own on-disk filename suffix.
# Sources with no entry for a given canonical label simply contribute
# nothing for that timeframe (e.g. Binance has no "1D" entry -- it uses "1d").
_YF_SUFFIX = {"1D": "1day", "1h": "1hr"}
_WRDS_SUFFIX = {"1D": "1D"}  # WRDS caches (Thread K Part 1 + Thread I) are daily-only as fetched
_BINANCE_SUFFIX = {"1D": "1d", "1h": "1h"}
# IBKR's real remaining value is intraday granularity (2026-08-14, Ross: "i'm fine with using
# IBKR for the intraday data") -- confirmed directly against the real cache (539 files, 92
# symbols): 1min/5min/15min/30min/1hr/4hr/1day all exist.
_IBKR_SUFFIX = {"1D": "1day", "1h": "1hr", "4h": "4hr", "30min": "30min",
                "15min": "15min", "5min": "5min", "1min": "1min"}


def _read_one(cache_dir: str, filename: str, sym: str, columns=None):
    try:
        df = pd.read_parquet(os.path.join(cache_dir, filename), columns=columns)
    except Exception:
        # Real, checked reason this bare except stays broad rather than catching a specific
        # exception type: a `columns=` read fails with different exception classes depending on
        # engine/file state (pyarrow raises its own error type for a missing requested column,
        # a genuinely malformed/truncated file raises a plain OSError) -- either way the correct
        # behavior is "skip this one file," not a hard crash on a single bad cache entry among
        # tens of thousands. Falls back to a full read once before giving up, in case `columns`
        # itself was the problem (e.g. an older cache file missing a requested non-critical column).
        if columns is not None:
            try:
                df = pd.read_parquet(os.path.join(cache_dir, filename))
            except Exception:
                return sym, None
        else:
            return sym, None
    if df is not None and not df.empty and "close" in df.columns:
        return sym, df
    return sym, None


def _load_dir(cache_dir: str, suffix: str, columns=None) -> dict:
    if not suffix or not os.path.isdir(cache_dir):
        return {}
    file_suffix = f"_{suffix}.parquet"
    candidates = [
        (f, f[: -len(file_suffix)]) for f in os.listdir(cache_dir) if f.endswith(file_suffix)
    ]
    out = {}
    with ThreadPoolExecutor(max_workers=_IO_WORKERS) as ex:
        futures = [ex.submit(_read_one, cache_dir, f, sym, columns) for f, sym in candidates]
        for fut in as_completed(futures):
            sym, df = fut.result()
            if df is not None:
                out[sym] = df
    return out


def _load_ibkr_dir(cache_dir: str, suffix: str, columns=None) -> dict:
    """IBKR files are named '{symbol}_{suffix}_deep.parquet' -- a different
    convention from every other source's '{symbol}_{suffix}.parquet', so
    this can't reuse _load_dir directly (different file_suffix construction,
    same parallel-read mechanics via _read_one)."""
    if not suffix or not os.path.isdir(cache_dir):
        return {}
    file_suffix = f"_{suffix}{_IBKR_FILE_SUFFIX}.parquet"
    candidates = [
        (f, f[: -len(file_suffix)]) for f in os.listdir(cache_dir) if f.endswith(file_suffix)
    ]
    out = {}
    with ThreadPoolExecutor(max_workers=_IO_WORKERS) as ex:
        futures = [ex.submit(_read_one, cache_dir, f, sym, columns) for f, sym in candidates]
        for fut in as_completed(futures):
            sym, df = fut.result()
            if df is not None:
                out[sym] = df
    return out


def align_to_common_calendar(merged: dict, lookback_years: int = 10) -> dict:
    """
    Reindexes every symbol's DataFrame in `merged` onto ONE shared
    DatetimeIndex (the union of every symbol's own dates, bounded to the
    trailing `lookback_years`), so that row i means the SAME calendar date
    for every symbol afterward.

    Real bug this fixes (found 2026-08-14, confirmed against real data, not
    theorized): load_full_universe()'s raw per-source DataFrames retain each
    source's OWN native index -- WRDS US equities, WRDS/Compustat Global
    international equities (GVKEY-labeled), Binance crypto (24/7), forex,
    and IBKR intraday all have genuinely different trading calendars and
    different per-symbol start dates. Every downstream consumer that reads
    these DataFrames' "close" column as a plain array (UniverseFilter.
    build_returns_matrix's right-aligned padding, CointScanner.
    _build_log_price_map -> _eg_worker's positional isfinite-mask) silently
    ASSUMES row i is the same date for every symbol -- true for the
    production S&P1500 pipeline (DataAligner already guarantees one shared
    calendar before analysis.py ever sees the data), false here. Confirmed
    directly against a real candidate pair from the full-universe
    correlation pre-filter (0700.HK: 5,438 bars from 2004; 3690.HK: 1,907
    bars from 2018 -- same end date, different length and start): calling
    _eg_worker on their raw, un-aligned log-price arrays raises
    "ValueError: operands could not be broadcast together with shapes
    (5438,) (1907,)" -- not a graceful insufficient_overlap rejection, a
    hard per-pair crash silently absorbed by _eg_worker's own try/except
    and counted as "not ok" alongside genuine insufficient_overlap cases.
    Same-length coincidences (rarer, but real) would instead silently
    compare mismatched dates without ever raising anything.

    Bounded to `lookback_years` (default 10, matching this project's own
    EPISODIC_WINDOW_BARS ~10yr convention elsewhere) rather than a full
    multi-decade union -- unioning ~44,840 symbols' FULL history (some back
    to the 1920s) would produce an unnecessarily huge shared index for no
    real analytical benefit (older, thinner-source history is already the
    least reliable part of this cross-source merge) and cost real memory at
    this scale. Each symbol keeps whatever real NaN gaps result from days
    its own market didn't trade -- never forward-filled here (same
    "never silently forward-fill a DATA_GAP bar" principle as data.py's own
    GapFlag system, CLAUDE.md rule 3).

    tz-naive/tz-aware mismatch (found live while building this, real -- not
    hypothetical): some sources' cached DataFrames carry a tz-aware index,
    others tz-naive. Normalized to tz-naive (`tz_localize(None)`) before
    building the union -- comparing/unioning mixed tz-awareness silently
    produces an undefined sort order (confirmed via a live RuntimeWarning),
    not just a cosmetic issue.
    """
    if not merged:
        return merged

    import numpy as np

    idx_arrays = []
    for sym, df in merged.items():
        if df is None or df.empty:
            continue
        idx = df.index
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
        idx_arrays.append(idx.values)

    if not idx_arrays:
        return merged

    all_dates = np.unique(np.concatenate(idx_arrays))
    cutoff = all_dates.max() - np.timedelta64(int(lookback_years * 365.25), "D")
    all_dates = all_dates[all_dates >= cutoff]
    canonical_index = pd.DatetimeIndex(all_dates)

    out = {}
    for sym, df in merged.items():
        if df is None or df.empty:
            continue
        if df.index.tz is not None:
            df = df.copy()
            df.index = df.index.tz_localize(None)
        reindexed = df[~df.index.duplicated(keep="last")].reindex(canonical_index)
        out[sym] = reindexed
    return out


def filter_exact_correlation_duplicates(candidate_pairs: list, threshold: float = 0.999999) -> tuple:
    """
    Excludes candidate pairs whose pearson_corr is (near-)exactly ±1.0 --
    the general, principled signature of "these two labels are the same
    underlying security (or a deterministic transform of it), not a real
    candidate pair." Deliberately NOT limited to a specific known naming
    pattern (e.g. a PERMNO<n>-fallback-label regex) -- found empirically
    2026-08-14 that a naming-pattern-only filter misses real cases with no
    shared naming pattern at all (a ticker-rename pair like FISV/FI) while
    an exact-correlation filter catches those AND cases a naming filter
    can't reach in principle, like literal inverse-quoted FX pairs
    (FX_AUDUSD vs FX_USDAUD -- confirmed as real duplicate files in this
    project's own WRDS FX cache, both directions of the same underlying
    rate, log-price correlation exactly -1.0).

    Does NOT exclude dual-share-class pairs generally (e.g. LBRDA/LBRDK) --
    those are real, distinct, separately-listed securities that merely
    correlate very strongly; only pairs at or above the near-exact
    `threshold` are true data-identity artifacts, not near-perfect but
    genuinely distinct correlated pairs (dual-class pairs found in the
    2026-08-14 investigation were consistently NOT at |corr|>=0.999999
    themselves in every case, but where a dual-class pair genuinely IS a
    near-exact duplicate, excluding it here is correct -- it would provide
    zero incremental research value over its sibling label).

    Returns (kept, dropped) -- both lists of candidate-pair dicts.
    """
    kept, dropped = [], []
    for p in candidate_pairs:
        corr = p.get("pearson_corr")
        if corr is not None and abs(corr) >= threshold:
            dropped.append(p)
        else:
            kept.append(p)
    return kept, dropped


def filter_structural_pairs(candidate_pairs: list, gvkey_cross_listing_threshold: float = 0.99) -> tuple:
    """
    Excludes candidate pairs whose cointegration would be structural (mandate-
    or corporate-structure-driven), not a discovered economic relationship --
    the same category analysis.py's production pipeline already excludes via
    CrossAssetTagger, but which full_universe_eg_confirmation.py's driver
    script never calls (it bypasses CrossAssetTagger.split() entirely). Found
    2026-08-16: SPY/VOO (both track the S&P 500) reached the confirmed-pairs
    output of both the 3y and 10y full-universe cascades because of exactly
    this gap.

    Two checks, in addition to reusing CrossAssetTagger's own whitelists:
      1. CrossAssetTagger._is_index_tracking_pair / _is_share_class_pair --
         the same small, hand-curated whitelists analysis.py's own pipeline
         uses (currently only SPY/VOO for index-tracking; GOOGL/GOOG etc. for
         share classes).
      2. GVKEY-cross-listing heuristic (found 2026-08-15/16 while building the
         3y/5y/10y window comparison -- see docs/HANDOFF.md): a plain ticker
         paired against a GVKEY<n>_NNW-labeled entry at |pearson_corr| >= 0.99
         is almost certainly the same company reaching the merged universe
         through two different data sources (yfinance vs. Compustat Global),
         not two economically distinct securities. This is a heuristic, not a
         confirmed identity match (no company-name crosswalk is queried) --
         deliberately a looser threshold than filter_exact_correlation_
         duplicates' 0.999999 (a different, harder signature that stays as-is).

    Returns (kept, dropped) -- both lists of candidate-pair dicts.
    """
    from analysis import CrossAssetTagger

    kept, dropped = [], []
    for p in candidate_pairs:
        a, b = p.get("symbol_a", ""), p.get("symbol_b", "")
        corr = p.get("pearson_corr")
        is_gvkey_cross_listing = (
            corr is not None and abs(corr) >= gvkey_cross_listing_threshold
            and (a.startswith("GVKEY") != b.startswith("GVKEY"))
        )
        if (CrossAssetTagger._is_index_tracking_pair(a, b)
                or CrossAssetTagger._is_share_class_pair(a, b)
                or is_gvkey_cross_listing):
            dropped.append(p)
        else:
            kept.append(p)
    return kept, dropped


def load_full_universe(tf_label: str = "1D", include_yfinance: bool = True,
                        include_wrds: bool = True, include_binance: bool = True,
                        include_ibkr: bool = True, columns=None) -> dict:
    """Merges every real price-data source for `tf_label` into one
    {symbol: DataFrame} dict. Later sources win on a symbol collision (WRDS,
    then Binance, then IBKR override yfinance) -- real collisions are
    expected to be rare (WRDS US-market labels are real tickers or
    PERMNO<n> fallbacks, Binance uses crypto tickers like "BTC"/"ETH" that
    don't collide with equity tickers, IBKR's cache is a small, known
    92-symbol confirmed-pair set) and are not a data-integrity concern the
    way silently merging mismatched-adjustment price series would be --
    each source's own file is used as-is, never blended bar-by-bar.

    include_ibkr default True per Ross's direct 2026-08-14 instruction
    ("i'm fine with using IBKR for the intraday data") -- see module
    docstring for the real, checked-not-assumed scope (intraday only, no
    forex/commodities currently exist in this cache).

    columns (added 2026-08-17, real OOM near-miss found live): forwarded to
    every underlying `pd.read_parquet` call for real, disk-level column
    pruning (pyarrow never materializes the dropped columns in memory at
    all, not just discards them after reading) -- e.g. columns=["close"]
    when a caller only needs price, not full OHLCV+volume. Checked directly:
    every current caller of this function (k_bahc_candidate_discovery.py,
    full_universe_correlation_prefilter.py, full_universe_eg_confirmation.py,
    fdr_method_comparison.py, pearson_threshold_sensitivity.py, tail_
    dependence_universe_screen.py) only ever reads the "close" column
    downstream. A real cache file measured directly: 5 columns (open/high/
    low/close/volume), close-only is ~17% of the full row's memory --
    loading all 44,840 symbols' full OHLCV pushed this project's own machine
    to within ~600MB of a second RAM crash the same night this was found
    and fixed (see docs/HANDOFF.md). Default None (read every column,
    unchanged prior behavior) -- callers must opt in explicitly."""
    merged = {}
    if include_yfinance and tf_label in _YF_SUFFIX:
        merged.update(_load_dir(_YF_CACHE_DIR, _YF_SUFFIX[tf_label], columns=columns))
    if include_wrds and tf_label in _WRDS_SUFFIX:
        merged.update(_load_dir(_WRDS_CACHE_DIR, _WRDS_SUFFIX[tf_label], columns=columns))
    if include_binance and tf_label in _BINANCE_SUFFIX:
        merged.update(_load_dir(_BINANCE_CACHE_DIR, _BINANCE_SUFFIX[tf_label], columns=columns))
    if include_ibkr and tf_label in _IBKR_SUFFIX:
        merged.update(_load_ibkr_dir(_IBKR_CACHE_DIR, _IBKR_SUFFIX[tf_label], columns=columns))
    return merged
