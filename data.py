# =============================================================================
# CAMARF — Cross-Asset Co-Movement Arbitrage Research Framework
# data.py — Universe building, data acquisition, cleaning, caching
# github.com/rossw811/CAMARF
#
# Data source architecture:
#   yfinance  → S&P 500 equities, daily/weekly/monthly (bulk, chunked)
#   IBKR      → S&P 500 equities, intraday (1m–1h)
#   IBKR      → Futures, forex, crypto, commodities (all timeframes)
#
# Rationale: yfinance provides 20+ years of daily equity data in minutes.
# IBKR's historical API is not designed for bulk downloads and rate-limits
# aggressively on intraday. Using each source where it excels gives maximum
# depth with minimum fetch time.
# =============================================================================

import os
import re
import json
import time
import hashlib
import logging
import requests
import warnings
from io import StringIO
import asyncio
import numpy as np
import pandas as pd
import yfinance as yf
import pandas_market_calendars as mcal
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

import nest_asyncio

nest_asyncio.apply()

import ib_insync as ibi

from config import Config

warnings.filterwarnings("ignore", category=FutureWarning)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("CAMARF.data")

# IBKR maintenance window (ET) — avoid reconnect attempts during this window
_MAINTENANCE_START_ET = 23  # 11 PM ET
_MAINTENANCE_END_ET = 1  # 1 AM ET


# =============================================================================
# DATACLASSES
# =============================================================================


@dataclass
class QualityReport:
    symbol: str
    asset_class: str
    timeframe: str
    original_bars: int
    bars_after_clean: int
    bars_dropped: int
    gap_count: int
    missing_pct: float
    roll_dates: List[str]
    passed: bool
    fail_reason: str = ""
    source: str = "ibkr"


@dataclass
class UniverseResult:
    """
    Output of UniverseBuilder.build(). Carries the full universe plus the
    exclusion set so downstream consumers (analysis.py) can independently
    verify that excluded symbols don't enter results.
    """

    assets: List[Tuple[str, str]]
    excluded: List[Tuple[str, str, str]]
    data: Dict[str, pd.DataFrame]
    quality_reports: List[QualityReport]
    exclusion_set: Optional[Set[str]] = None  # symbols explicitly excluded

    def __post_init__(self) -> None:
        if self.exclusion_set is None:
            self.exclusion_set = set()


# =============================================================================
# CLASS 1 — DataStore
# =============================================================================


class DataStore:
    """Parquet cache. All classes read/write through here."""

    # Filesystem-safe TF label names.
    # CRITICAL: on Windows, filenames are case-insensitive.
    # "SYMBOL_1m.parquet" and "SYMBOL_1M.parquet" are the SAME file.
    # When _resample_from_daily saves 1M (monthly) data it overwrites the
    # 1m (1-minute) cache — causing the frequency mismatch warnings.
    # Fix: map all TF labels to unambiguous lowercase strings.
    _TF_SAFE: Dict[str, str] = {
        "1m": "1min",  # ← was "1m"; would collide with "1M" on Windows
        "2m": "2min",
        "3m": "3min",
        "5m": "5min",
        "15m": "15min",
        "30m": "30min",
        "1h": "1hr",
        "4h": "4hr",
        "1D": "1day",
        "7D": "7day",
        "1M": "1mo",  # ← was "1M"; would collide with "1m" on Windows
        "3M": "3mo",  # quarterly (derived from 1D via QS resample)
        "6M": "6mo",  # semi-annual (derived from 1D via 2QS resample)
    }

    @staticmethod
    def _path(symbol: str, tf_label: str) -> str:
        Config.ensure_dirs()
        safe = DataStore._TF_SAFE.get(tf_label, tf_label.lower())
        fname = f"{symbol}_{safe}.parquet".replace("/", "-").replace(" ", "_")
        return os.path.join(Config.DATA.CACHE_DIR, fname)

    @staticmethod
    def migrate_cache() -> None:
        """
        One-time migration: rename old TF-labeled cache files to the new
        safe names. Handles the case where "1M" and "1m" were the same file
        on Windows — those files contain corrupted data (1M overwrote 1m).

        After migration: re-run data.py to re-fetch genuine 1m data.
        The old (corrupted) files are deleted; new safe-named files will be
        written by the next data.py run.
        """
        import glob

        cache_dir = Config.DATA.CACHE_DIR
        if not os.path.exists(cache_dir):
            return

        # Old suffix → new suffix mapping
        old_to_new = {
            "_1m.parquet": "_1min.parquet",
            "_2m.parquet": "_2min.parquet",
            "_3m.parquet": "_3min.parquet",
            "_5m.parquet": "_5min.parquet",
            "_15m.parquet": "_15min.parquet",
            "_30m.parquet": "_30min.parquet",
            "_1h.parquet": "_1hr.parquet",
            "_4h.parquet": "_4hr.parquet",
            "_1D.parquet": "_1day.parquet",
            "_7D.parquet": "_7day.parquet",
        }
        # On Windows "1M" == "1m" — both point to the same physical file.
        # These files contain monthly data (1M overwrote 1m).
        # Delete them; data.py will re-fetch and save as _1min.parquet
        # (1m data) and _1mo.parquet (1M data) with safe names.
        corrupt_patterns = ["*_1m.parquet", "*_1M.parquet"]

        n_migrated = 0
        n_deleted = 0

        for old_suffix, new_suffix in old_to_new.items():
            if old_suffix in ("_1m.parquet",):
                continue  # handled separately below (corrupted on Windows)
            for old_path in glob.glob(os.path.join(cache_dir, f"*{old_suffix}")):
                new_path = old_path.replace(old_suffix, new_suffix)
                if not os.path.exists(new_path):
                    try:
                        os.rename(old_path, new_path)
                        n_migrated += 1
                    except OSError:
                        pass

        # Delete corrupted 1m/1M files — they contain monthly data on Windows
        # Case-insensitive glob on Windows will find both "1m" and "1M" files
        for pat in corrupt_patterns:
            for path in glob.glob(os.path.join(cache_dir, pat)):
                try:
                    os.remove(path)
                    n_deleted += 1
                except OSError:
                    pass

        # Also delete 2min/3min derived files — they were derived from the
        # corrupted 1m cache (monthly data), so they also have monthly frequency.
        for pat in ["*_2min.parquet", "*_3min.parquet", "*_2m.parquet", "*_3m.parquet"]:
            for stale_path in glob.glob(os.path.join(cache_dir, pat)):
                try:
                    os.remove(stale_path)
                    n_deleted += 1
                except OSError:
                    pass

        log.info(
            f"Cache migration: {n_migrated} renamed, {n_deleted} corrupted files deleted "
            f"(1m/1M collision and derived 2m/3m)"
        )
        log.info("Rerun data.py to re-fetch 1m data; 2m/3m re-derived from clean 1m.")

    @staticmethod
    def save(symbol: str, tf_label: str, df: pd.DataFrame) -> None:
        if df is None or df.empty:
            return
        path = DataStore._path(symbol, tf_label)
        df.to_parquet(path, index=True, compression="snappy")
        log.debug(f"Cached  {symbol} {tf_label}  →  {len(df)} bars")

    @staticmethod
    def load(symbol: str, tf_label: str) -> Optional[pd.DataFrame]:
        path = DataStore._path(symbol, tf_label)
        if not os.path.exists(path):
            return None
        return pd.read_parquet(path)

    @staticmethod
    def needs_refresh(symbol: str, tf_label: str) -> bool:
        """
        True if the cache is stale and should be updated with new bars.

        Daily TFs (1D, 7D, 1M): stale if the last bar is more than 1 trading
        day behind today. We define "stale" as: last_bar < today - 2 calendar
        days (to account for weekends and holidays).

        Intraday TFs: NOT handled by this function at all — it unconditionally
        returns False for them (see below), which simply means "not handled
        here," not "never refreshed." Real intraday staleness gating lives in
        DataStore.is_fresh(symbol, tf, max_age_hours=...) via
        DataStore.intraday_max_age_hours(tf), used directly at each fetch call
        site. Corrected 2026-06-23: this docstring previously claimed
        "intraday always re-fetched at each run," which was true in intent
        but not in the actual code — the real gating (is_fresh with no
        max_age_hours at all) had silently meant "never re-fetched past the
        first successful fetch," a real bug, now fixed; see BUG-D45-adjacent
        notes in Development.md Session 10.
        """
        _INCREMENTAL_TFS = {"1D", "7D", "1M"}
        if tf_label not in _INCREMENTAL_TFS:
            return False  # intraday staleness is handled by is_fresh() + intraday_max_age_hours(), not here
        cached = DataStore.load(symbol, tf_label)
        if cached is None or cached.empty:
            return True
        last_bar = cached.index[-1]
        # Convert to date for comparison
        if hasattr(last_bar, "date"):
            last_date = last_bar.date()
        else:
            last_date = pd.Timestamp(last_bar).date()
        today = datetime.now().date()
        delta = (today - last_date).days
        # More than 2 calendar days behind → needs refresh
        return delta > 2

    # Expected median gap in seconds for each TF label
    _EXPECTED_GAP_SECONDS: Dict[str, float] = {
        "1m": 60,
        "2m": 120,
        "3m": 180,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "4h": 14400,
        "1D": 86400,
        "7D": 604800,
        "1M": 2592000,
    }
    _FREQ_TOLERANCE = 5.0  # actual gap must be < expected × tolerance to be valid

    # Expected minimum bar counts per TF for a 10-year lookback.
    # Assets with fewer bars in cache are considered insufficiently fetched
    # (e.g. yfinance fallback gave 1458 bars where IBKR would give 5861).
    # Used to trigger upgrade re-fetch from a deeper source.
    _MIN_BARS: Dict[str, int] = {
        "1m": 5_000,  # yfinance max 7 days; IBKR goes further
        "2m": 5_000,
        "3m": 5_000,
        "5m": 2_500,  # yfinance max 60 days
        "15m": 2_000,
        "30m": 1_500,
        "1h": 1_200,  # yfinance max 730 days; IBKR goes further
        "4h": 2_500,
        "1D": 2_000,  # ~8 years daily
        "7D": 400,  # ~8 years weekly
        "1M": 80,  # ~7 years monthly
        "3M": 20,  # ~5 years quarterly
        "6M": 10,  # ~5 years semi-annual
    }

    @staticmethod
    def is_data_sufficient(symbol: str, tf_label: str) -> bool:
        """
        Returns True if the cached data meets the minimum bar count
        for this TF. Returns True (don't re-fetch) if no minimum is defined
        or if the file doesn't exist (caller handles missing separately).

        Primary use: flag assets where yfinance fallback gave truncated
        history (e.g. 1458 bars at 8h) so IBKR can be retried for the
        deeper history (5861 bars) in a later upgrade pass.
        """
        min_bars = DataStore._MIN_BARS.get(tf_label)
        if min_bars is None:
            return True  # no threshold defined — assume sufficient
        df = DataStore.load(symbol, tf_label)
        if df is None:
            return False  # missing entirely
        return len(df) >= min_bars

    @staticmethod
    def clear_tf_cache(tf_label: str, dry_run: bool = False) -> int:
        """
        Delete cached parquet files for a specific timeframe.
        Use when cached data has the wrong frequency (e.g., 8h data
        stored under the 1h key after a batch fallback bug).

        Returns count of deleted files.
        Example: DataStore.clear_tf_cache("1h") before re-running data.py
        to force a fresh 1h fetch for all assets.
        """
        safe = DataStore._TF_SAFE.get(tf_label, tf_label)
        suffix = f"_{safe}.parquet"
        cache_dir = Config.DATA.CACHE_DIR
        deleted = 0
        for fname in os.listdir(cache_dir):
            if fname.endswith(suffix):
                if not dry_run:
                    try:
                        os.remove(os.path.join(cache_dir, fname))
                        deleted += 1
                    except OSError:
                        pass
                else:
                    deleted += 1
        log.info(
            f"DataStore.clear_tf_cache('{tf_label}'): "
            f"{'would delete' if dry_run else 'deleted'} {deleted} files"
        )
        return deleted

    @staticmethod
    def validate_frequency(
        symbol: str,
        tf_label: str,
        df: pd.DataFrame,
    ) -> bool:
        """
        Check that the DataFrame's actual bar frequency matches tf_label.

        Computes the median time gap between consecutive index timestamps
        and compares it to the expected gap for the TF. Returns False if
        the actual gap is > expected × tolerance, meaning the data is at
        the wrong frequency (e.g. daily data stored in a 1m cache slot).

        This catches the NTRS/STT 1m = 1M identical results bug: daily bars
        stored in the 1m cache produce cointegration results indistinguishable
        from the daily analysis — silent contamination of the intraday pipeline.
        """
        expected = DataStore._EXPECTED_GAP_SECONDS.get(tf_label)
        if expected is None or df is None or len(df) < 3:
            return True  # can't validate, assume OK
        if not hasattr(df.index, "to_series"):
            return True

        diffs = df.index.to_series().diff().dropna()
        if diffs.empty:
            return True
        # Exclude structural overnight/weekend gaps (>8h) before computing
        # the median — same fix as _clean_contaminated_cache(). A correctly
        # session-aligned 4h file has exactly 2 bars/day, so half its gaps
        # are the legitimate ~20h overnight break; including them pushed
        # the median toward "looks like daily data" and wrongly rejected
        # good 4h files here too.
        gap_seconds = diffs.dt.total_seconds()
        intraday_gaps = gap_seconds[gap_seconds <= 8 * 3600]
        median_gap = (
            intraday_gaps if len(intraday_gaps) >= 3 else gap_seconds
        ).median()

        # Valid: median gap within [expected/tolerance, expected*tolerance]
        ok = (
            (expected / DataStore._FREQ_TOLERANCE)
            <= median_gap
            <= (expected * DataStore._FREQ_TOLERANCE)
        )
        if not ok:
            log.warning(
                f"  Frequency mismatch: {symbol} {tf_label} — "
                f"expected gap ~{expected:.0f}s, got median {median_gap:.0f}s. "
                f"Cache likely contains {DataStore._infer_tf(median_gap)} data. "
                f"Rerun data.py to refresh this asset's {tf_label} cache."
            )
        return ok

    @staticmethod
    def _infer_tf(median_gap_seconds: float) -> str:
        """Guess the actual TF from the median gap, for the warning message."""
        for label, expected in sorted(
            DataStore._EXPECTED_GAP_SECONDS.items(), key=lambda x: x[1]
        ):
            if abs(median_gap_seconds - expected) / expected < 2.0:
                return label
        return f"unknown (~{median_gap_seconds:.0f}s)"

    @staticmethod
    def append(
        symbol: str,
        tf_label: str,
        new_df: pd.DataFrame,
    ) -> Optional[pd.DataFrame]:
        """
        Append new bars to an existing cache file, dedup on index, sort.

        Used for incremental daily refresh: instead of re-fetching 20 years
        of history, we fetch only the last N days and append them.

        Returns the combined DataFrame (also overwrites the cache file).
        """
        if new_df is None or new_df.empty:
            return DataStore.load(symbol, tf_label)
        existing = DataStore.load(symbol, tf_label)
        if existing is None or existing.empty:
            DataStore.save(symbol, tf_label, new_df)
            return new_df
        # Concatenate, drop exact index duplicates, sort chronologically
        combined = pd.concat([existing, new_df])
        combined = combined[~combined.index.duplicated(keep="last")]
        combined = combined.sort_index()
        DataStore.save(symbol, tf_label, combined)
        log.debug(
            f"Appended {symbol} {tf_label}: {len(existing)} → {len(combined)} bars "
            f"(+{len(combined)-len(existing)} new)"
        )
        return combined

    @staticmethod
    def is_fresh(symbol: str, tf_label: str, max_age_hours: float = None) -> bool:
        path = DataStore._path(symbol, tf_label)
        if not os.path.exists(path):
            return False
        if max_age_hours is not None:
            age_hours = (time.time() - os.path.getmtime(path)) / 3600
            return age_hours < max_age_hours
        return True

    # Native-fetch intraday TFs only — excludes 4h/2m/3m, which are derived
    # from 1h/1m and deliberately have NO is_fresh() guard at all (re-derive
    # every run from the full accumulated source; see the comments at their
    # derivation call sites).
    _NATIVE_INTRADAY_TFS = {"1m", "2m", "3m", "5m", "15m", "30m", "1h"}

    @staticmethod
    def intraday_max_age_hours(tf_label: str) -> Optional[float]:
        """
        Found overnight (2026-06-23): every native-intraday is_fresh() call
        site was passing no max_age_hours, so is_fresh() just meant "file
        exists" — once a symbol/TF was cached even once, it was skipped on
        every future run forever, regardless of staleness. This silently
        broke the entire "intraday history accumulates day over day" premise
        (BUG-D42/BUG-D45's append() work, the scheduled daily data.py task)
        for any symbol that had already been successfully fetched once.
        20h (not 24h) so a once-daily scheduled run always sees yesterday's
        fetch as stale enough to refresh, with margin for the run firing a
        few hours early/late on a given day. Returns None (preserves the
        existing exists-only behavior) for daily+ TFs, which already pair
        is_fresh() with needs_refresh()'s real date-based staleness check.
        """
        return 20.0 if tf_label in DataStore._NATIVE_INTRADAY_TFS else None

    @staticmethod
    def list_cached() -> List[str]:
        Config.ensure_dirs()
        files = os.listdir(Config.DATA.CACHE_DIR)
        return [f.replace(".parquet", "") for f in files if f.endswith(".parquet")]


# =============================================================================
# CLASS 1b — ProgressLogger
# =============================================================================


class ProgressLogger:
    """
    Crash-safe progress tracking with config-hash invalidation.

    Writes progress.json after every completed asset. On restart, assets
    already completed under the current config hash are loaded from cache
    instead of re-fetched.

    Config hash: SHA-256 of all parameters affecting data validity. If any
    change, affected assets are automatically re-fetched.
    """

    PROGRESS_FILE = os.path.join(
        os.path.dirname(__file__), "output", "cache", "progress.json"
    )

    _HASH_FIELDS = [
        Config.DATA.TIMEFRAMES,
        Config.DATA.TIMEFRAME_LABELS,
        Config.DATA.HISTORY_DEPTH,
        Config.DATA.MIN_BARS_REQUIRED,
        Config.DATA.MAX_MISSING_PCT,
        Config.DATA.MIN_DOLLAR_VOLUME,
        Config.UNIVERSE.CRYPTO,
        Config.UNIVERSE.FOREX,
        Config.UNIVERSE.COMMODITIES,
        Config.UNIVERSE.FUTURES,
    ]

    @staticmethod
    def compute_config_hash() -> str:
        raw = json.dumps(
            [str(f) for f in ProgressLogger._HASH_FIELDS], sort_keys=True
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]

    @staticmethod
    def load() -> dict:
        Config.ensure_dirs()
        import tempfile

        fallback = os.path.join(tempfile.gettempdir(), "camarf_progress_fallback.json")
        # Try main file, then TEMP fallback (written when OneDrive locked the main file)
        for path in [ProgressLogger.PROGRESS_FILE, fallback]:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if path == fallback:
                        log.info(f"Loaded progress from TEMP fallback: {path}")
                    return data
                except Exception:
                    continue
        return {
            "config_hash": ProgressLogger.compute_config_hash(),
            "started_at": datetime.now().isoformat(),
            "completed": {},
        }

    @staticmethod
    def save(progress: dict) -> None:
        Config.ensure_dirs()
        tmp = ProgressLogger.PROGRESS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(progress, f, indent=2)
        saved = False
        for _i in range(5):
            try:
                os.replace(tmp, ProgressLogger.PROGRESS_FILE)
                saved = True
                break
            except OSError:
                time.sleep(0.5 * (_i + 1))
        if not saved:
            try:
                with open(ProgressLogger.PROGRESS_FILE, "w", encoding="utf-8") as f:
                    json.dump(progress, f, indent=2)
                saved = True
            except OSError:
                pass
        if not saved:
            import tempfile

            fallback = os.path.join(
                tempfile.gettempdir(), "camarf_progress_fallback.json"
            )
            try:
                with open(fallback, "w", encoding="utf-8") as f:
                    json.dump(progress, f, indent=2)
                log.warning(f"Progress saved to TEMP fallback: {fallback}")
            except Exception as e:
                log.error(f"Progress save completely failed: {e}")
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass

    @staticmethod
    def mark_complete(
        progress: dict,
        symbol: str,
        asset_class: str,
        timeframes_done: List[str],
    ) -> None:
        current_hash = ProgressLogger.compute_config_hash()
        progress["completed"][symbol] = {
            "asset_class": asset_class,
            "completed_at": datetime.now().isoformat(),
            "config_hash": current_hash,
            "timeframes_fetched": timeframes_done,
        }
        ProgressLogger.save(progress)

    @staticmethod
    def is_complete(progress: dict, symbol: str) -> bool:
        entry = progress.get("completed", {}).get(symbol)
        if entry is None:
            return False

        stored_hash = entry.get("config_hash", "")
        current_hash = ProgressLogger.compute_config_hash()

        if stored_hash == current_hash:
            return True

        # Config hash changed — but check if the asset's cached data is still
        # valid before forcing a full re-fetch. Adding new config parameters
        # (universe expansion, new TF labels, new analysis flags) doesn't
        # invalidate existing price data. Only re-fetch if data is missing
        # or insufficient.
        #
        # Check using the daily TF as a proxy for "was this asset ever fetched".
        # If daily data is fresh and sufficient, accept the cache and silently
        # update the hash. If not, force re-fetch.
        if DataStore.is_fresh(symbol, "1D") and DataStore.is_data_sufficient(
            symbol, "1D"
        ):
            # Data is valid — update the stored hash without re-fetching
            entry["config_hash"] = current_hash
            return True

        log.debug(
            f"Config changed and data is stale/missing for {symbol} "
            f"({stored_hash[:8]} → {current_hash[:8]}) — re-fetching"
        )
        return False

    @staticmethod
    def reset() -> None:
        if os.path.exists(ProgressLogger.PROGRESS_FILE):
            os.remove(ProgressLogger.PROGRESS_FILE)
            log.info("Progress file reset — next build will re-fetch all assets")


# =============================================================================
# CLASS 1c — DataAligner
# Aligns all assets to a common NYSE calendar timeline with gap flagging.
# =============================================================================

# =============================================================================
# GAP FLAG SYSTEM
# =============================================================================


class GapFlag:
    """
    Integer codes for bar-level gap classification.

    Each bar in aligned data carries a `gap_flag` integer column so that
    downstream consumers (correlation, EG, ML features, backtest) can each
    decide how to handle the bar based on why it was flagged.

    Design: integer codes (not enum) for parquet serialization compatibility.

    Usage in analysis pipeline:
        NONE         → include in all calculations
        FILL         → include in EG/corr; exclude from ML volume features
        NO_ACTIVITY  → include in corr (real zero-return); mark volume=0
        HALT         → include price in EG/corr; exclude from volume features
        DATA_GAP     → if ≤5 bars: FILL treatment; if >5 bars: exclude from EG
        SPARSE       → include in EG/corr; lower weight in rolling corr
        STRUCTURAL   → never appears as row (weekends/holidays excluded entirely)
    """

    NONE = 0  # Clean bar — include in everything
    FILL = 1  # Forward-filled (≤5 bar gap, liquid asset)
    NO_ACTIVITY = 2  # Genuine zero-trade bar (crypto 24/7, thin markets)
    HALT = 3  # Trading halt — price valid, volume meaningless
    DATA_GAP = 4  # Provider gap > 5 bars — exclude from EG window
    SPARSE = 5  # Thin history (new listing, low liquidity period)
    STRUCTURAL = 6  # Weekend/holiday — these rows don't exist in the data


# Maximum consecutive gap bars before DATA_GAP instead of FILL
_MAX_FILL_BARS = 5

# Crypto tickers: these trade 24/7 so single missing bars are NO_ACTIVITY not FILL
_CRYPTO_SUFFIXES = {"-USD", "-USDT", "-BTC"}


def _is_crypto(symbol: str) -> bool:
    return any(symbol.upper().endswith(s) for s in _CRYPTO_SUFFIXES)


def _gap_aware_returns(
    df: "pd.DataFrame",
    exclude_flags: tuple = (GapFlag.DATA_GAP,),
) -> "np.ndarray":
    """
    Compute log returns masking bars with bad gap flags.
    DATA_GAP bars (>5 consecutive missing) produce spuriously large
    returns from accumulated price movement and are excluded.
    FILL bars (≤5 missing) are kept — forward-fill is acceptable.
    NO_ACTIVITY (crypto zero-trade) are kept as genuine zero returns.

    Elapsed-time detection is applied after gap-flag masking so this
    function is correct even when DATA_GAP sentinel rows were removed
    (drop_data_gap_rows=True). Any return spanning > 4× the median bar
    interval is masked — catches data holes np.roll cannot detect when
    the marker rows are absent. No-op when all diffs equal one bar width.
    """
    import numpy as np

    if "close" not in df.columns:
        return np.full(len(df), np.nan)
    log_prices = np.log(df["close"].values.astype(float))
    returns = np.diff(log_prices, prepend=np.nan)
    if "gap_flag" in df.columns:
        flags = df["gap_flag"].values.astype(int)
        for code in exclude_flags:
            bad = flags == code
            bad_return = bad | np.roll(bad, 1)
            bad_return[0] = False
            returns[bad_return] = np.nan
    if len(df) > 1:
        try:
            diffs = df.index.to_series().diff().dt.total_seconds().values
            finite_diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
            if len(finite_diffs) > 0:
                expected = np.median(finite_diffs)
                large_gap = diffs > expected * 4
                large_gap[0] = False
                returns[large_gap] = np.nan
        except AttributeError:
            pass
    return returns


def _clean_close(
    df: "pd.DataFrame",
    exclude_flags: tuple = (GapFlag.DATA_GAP,),
) -> "np.ndarray":
    """Return close prices with DATA_GAP bars masked to NaN for EG tests."""
    import numpy as np

    prices = df["close"].values.astype(float).copy()
    if "gap_flag" in df.columns:
        flags = df["gap_flag"].values.astype(int)
        for code in exclude_flags:
            prices[flags == code] = np.nan
    return prices


class DataAligner:
    """
    Aligns OHLCV DataFrames across all assets to a common timeline,
    classifying every bar with a GapFlag code.

    Gap treatment hierarchy:
      NONE         → clean bar, include in all downstream calculations
      FILL (≤5)    → forward-fill price, zero volume; include in EG/corr,
                     exclude from ML volume features
      NO_ACTIVITY  → crypto genuine zero-trade bar; include as-is
      HALT         → trading halt; forward-fill price, mark volume invalid
      DATA_GAP(>5) → long provider gap; do NOT fill; exclude from EG window
      SPARSE       → pre-liquidity period (new listing); include with caveat

    Cross-asset alignment note:
      When correlating equity intraday with futures (ES↔utilities at 15m),
      restrict to equity session hours (9:30 AM – 4:00 PM ET) only.
      Using ES overnight bars against a zero-return equity bar inflates
      cross-asset correlation — the equity price is stale, not correlated.
    """

    _NYSE = None

    @staticmethod
    def _get_nyse_calendar(start: str, end: str) -> pd.DatetimeIndex:
        """Return NYSE trading session dates between start and end."""
        if DataAligner._NYSE is None:
            DataAligner._NYSE = mcal.get_calendar("NYSE")
        schedule = DataAligner._NYSE.schedule(start_date=start, end_date=end)
        return mcal.date_range(schedule, frequency="1D").normalize().tz_localize(None)

    @staticmethod
    def align_daily(
        data: Dict[str, pd.DataFrame],
        asset_classes: Dict[str, str] = None,  # {symbol: class} for per-type treatment
        start_date: str = None,
        end_date: str = None,
        drop_data_gap_rows: bool = False,
    ) -> Dict[str, pd.DataFrame]:
        """
        Align all daily DataFrames to the NYSE master calendar.
        Each bar is classified with a GapFlag code (stored in `gap_flag` int column).
        The legacy `is_gap` boolean column is also preserved for backward compatibility.

        Gap classification logic (daily):
          - Bar present, clean:              GapFlag.NONE
          - 1-5 consecutive missing bars:    GapFlag.FILL (forward-fill price, zero vol)
          - >5 consecutive missing bars:     GapFlag.DATA_GAP (fill price, flag for exclusion)
          - Asset age gap (pre-IPO period):  GapFlag.SPARSE (leading NaN = new listing)
          - Crypto missing single bar:       GapFlag.NO_ACTIVITY (24/7, genuine zero-trade)

        drop_data_gap_rows: see align_intraday's docstring for the full
        rationale (2026-06-24) — same opt-in, same default-False safety
        for build_returns_matrix's cross-symbol dense alignment. The NYSE
        calendar already excludes weekends/holidays entirely (they never
        enter the index), so the row-bloat this addresses for intraday is
        much smaller here — added for consistency, not because daily had
        the same severity of issue.
        """
        if not data:
            return {}

        all_starts = [
            df.index.min() for df in data.values() if df is not None and not df.empty
        ]
        all_ends = [
            df.index.max() for df in data.values() if df is not None and not df.empty
        ]
        if not all_starts:
            return {}

        start = start_date or str(min(all_starts).date())
        end = end_date or str(max(all_ends).date())
        master_idx = DataAligner._get_nyse_calendar(start, end)
        asset_classes = asset_classes or {}

        log.info(
            f"DataAligner: aligning {len(data)} assets to NYSE calendar "
            f"({start} → {end}, {len(master_idx)} sessions)"
        )

        aligned: Dict[str, pd.DataFrame] = {}
        for symbol, df in data.items():
            if df is None or df.empty:
                continue

            is_crypto_asset = (
                _is_crypto(symbol) or asset_classes.get(symbol, "") == "crypto"
            )

            df = df.copy()
            df.index = df.index.normalize()
            df_aligned = df.reindex(master_idx)

            # ---- Gap classification ----
            missing = df_aligned["close"].isna()
            missing_bool = missing.values  # numpy bool array — no pandas overhead
            gap_flag = np.zeros(len(missing_bool), dtype=np.int8)

            # Walk runs of consecutive missing bars using numpy for speed
            run_len = 0
            run_start = 0
            for i in range(len(missing_bool)):
                if missing_bool[i]:
                    if run_len == 0:
                        run_start = i
                    run_len += 1
                else:
                    if run_len > 0:
                        code = (
                            GapFlag.NO_ACTIVITY
                            if (is_crypto_asset and run_len == 1)
                            else (
                                GapFlag.FILL
                                if run_len <= _MAX_FILL_BARS
                                else GapFlag.DATA_GAP
                            )
                        )
                        gap_flag[run_start : run_start + run_len] = code
                        run_len = 0
            if run_len > 0:  # trailing gap at end of series
                code = GapFlag.DATA_GAP if run_len > _MAX_FILL_BARS else GapFlag.FILL
                gap_flag[run_start : run_start + run_len] = code

            df_aligned["gap_flag"] = gap_flag
            df_aligned["is_gap"] = missing_bool  # backward compat

            # ---- Fill prices (all gap types — downstream filters on flag) ----
            for col in ["open", "high", "low", "close"]:
                if col in df_aligned.columns:
                    df_aligned[col] = df_aligned[col].ffill()

            # Zero volume for any filled bar
            if "volume" in df_aligned.columns:
                df_aligned["volume"] = df_aligned["volume"].where(~missing, 0)

            # ---- Drop pre-IPO leading rows & mark as SPARSE ----
            first_valid = df_aligned["close"].first_valid_index()
            if first_valid is None:
                continue
            df_aligned = df_aligned.loc[first_valid:]

            # Any remaining NaN close (shouldn't happen after ffill but guard)
            still_nan = df_aligned["close"].isna()
            df_aligned.loc[still_nan, "gap_flag"] = GapFlag.SPARSE

            # ---- Quality gate: exclude >50% gap rate ----
            # Recompute missing AFTER the first_valid trim above so gap_pct
            # reflects only the asset's actual trading history — not the
            # pre-IPO void. Without this, a 2013 IPO has 79% "gap rate"
            # on a 1962-present calendar and gets excluded incorrectly.
            missing_trimmed = df_aligned["close"].isna()
            gap_pct = float(missing_trimmed.mean()) if len(missing_trimmed) > 0 else 0.0
            if gap_pct > 0.50:
                log.warning(f"DataAligner: {symbol} {gap_pct:.1%} gap rate — excluded")
                continue

            if gap_pct > 0.05:
                log.debug(
                    f"DataAligner: {symbol} gap rate {gap_pct:.1%} (kept, flagged)"
                )

            if drop_data_gap_rows:
                df_aligned = df_aligned[df_aligned["gap_flag"] != GapFlag.DATA_GAP]

            aligned[symbol] = df_aligned

        log.info(
            f"DataAligner: {len(aligned)}/{len(data)} assets aligned "
            f"({len(data)-len(aligned)} excluded for excessive gaps)"
        )
        return aligned

    @staticmethod
    def align_intraday(
        data: Dict[str, pd.DataFrame],
        tf_label: str,
        drop_data_gap_rows: bool = False,
    ) -> Dict[str, pd.DataFrame]:
        """
        Align intraday DataFrames within each asset's own trading session.

        For intraday, we don't impose a cross-asset master calendar since
        assets have different trading hours. Instead we:
          1. Forward-fill within-session gaps (missing bars due to no trades)
          2. Add is_gap flag
          3. Ensure all assets share the same frequency (no irregular spacing)

        Returns aligned DataFrames with is_gap column added.

        drop_data_gap_rows (default False, preserves exact existing
        behavior): found 2026-06-24 that the dense reindex below makes
        EVERY row's distance from its predecessor identically the bar
        frequency, by construction — meaning a "drop the bar after each
        overnight break" check based on timestamp diffs computed AFTER
        reindexing can never fire (diffs are constant on a uniform-freq
        index). This was silent dead code, not a correctness bug — every
        overnight/weekend hour gets reindexed in, forward-filled, and
        correctly flagged DATA_GAP, and _gap_aware_returns/_clean_close
        already mask DATA_GAP downstream — but it means every aligned
        intraday symbol carries ~6x more rows than necessary (verified:
        CATY @1h, 4369 real bars -> 25565 aligned rows). Left as an
        explicit opt-in rather than changed unconditionally: production's
        build_returns_matrix relies on every symbol sharing the SAME
        dense, uniform-frequency grid for its right-pad-by-row-count
        cross-symbol alignment to be calendar-correct (verified directly
        this session) — dropping DATA_GAP rows by default would silently
        reintroduce a different version of the exact misalignment bug
        this session already found and fixed elsewhere. Single-pair
        consumers that join by real DatetimeIndex (aligned_pair_loader.py
        and everything built on it) have no such dependency and opt in.
        """
        freq_map = {
            "4h": "4h",
            "1h": "1h",
            "30m": "30min",
            "15m": "15min",
            "5m": "5min",
            "3m": "3min",
            "2m": "2min",
            "1m": "1min",
        }
        freq = freq_map.get(tf_label)

        _freq_minutes = {
            "1min": 1,
            "2min": 2,
            "3min": 3,
            "5min": 5,
            "15min": 15,
            "30min": 30,
            "1h": 60,
            "4h": 240,
        }
        _MAX_REINDEX = 500_000

        aligned: Dict[str, pd.DataFrame] = {}
        for symbol, df in data.items():
            if df is None or df.empty:
                continue

            is_crypto_asset = _is_crypto(symbol)
            df = df.copy()

            if freq and len(df) > 10:
                _fmin = _freq_minutes.get(freq, 1)
                _span_min = (df.index.max() - df.index.min()).total_seconds() / 60
                _expected_rows = int(_span_min / _fmin) + 1

                if _expected_rows > _MAX_REINDEX:
                    log.debug(
                        f"  align_intraday: {symbol} expected {_expected_rows} rows "
                        f"at freq={freq} — OOM guard, using raw"
                    )
                    df["gap_flag"] = np.zeros(len(df), dtype=np.int8)
                    df["is_gap"] = False
                    aligned[symbol] = df.dropna(subset=["close"])
                    continue

                full_idx = pd.date_range(df.index.min(), df.index.max(), freq=freq)
                df_aligned = df.reindex(full_idx)
                missing = df_aligned["close"].isna()

                # ---- Gap classification (same run-length logic as daily) ----
                missing_bool = missing.values
                gap_flag = np.zeros(len(missing_bool), dtype=np.int8)
                run_len = 0
                run_start = 0
                for i in range(len(missing_bool)):
                    if missing_bool[i]:
                        if run_len == 0:
                            run_start = i
                        run_len += 1
                    else:
                        if run_len > 0:
                            code = (
                                GapFlag.NO_ACTIVITY
                                if (is_crypto_asset and run_len == 1)
                                else (
                                    GapFlag.FILL
                                    if run_len <= _MAX_FILL_BARS
                                    else GapFlag.DATA_GAP
                                )
                            )
                            gap_flag[run_start : run_start + run_len] = code
                            run_len = 0
                if run_len > 0:
                    gap_flag[run_start : run_start + run_len] = (
                        GapFlag.DATA_GAP if run_len > _MAX_FILL_BARS else GapFlag.FILL
                    )

                df_aligned["gap_flag"] = gap_flag
                df_aligned["is_gap"] = missing_bool

                # ---- Fill prices ----
                for col in ["open", "high", "low", "close"]:
                    if col in df_aligned.columns:
                        df_aligned[col] = df_aligned[col].ffill()
                if "volume" in df_aligned.columns:
                    df_aligned["volume"] = df_aligned["volume"].where(~missing, 0)

                # ---- Optionally drop DATA_GAP rows (opt-in, see docstring) ----
                # Uses the gap_flag classification directly rather than
                # re-deriving "is this an overnight break" from timestamp
                # diffs — the diff-based check (former implementation here)
                # cannot distinguish a real gap from a normal bar-to-bar
                # step once the index has already been reindexed onto a
                # uniform-frequency grid, since every diff is identical by
                # construction at that point.
                if drop_data_gap_rows:
                    df_aligned = df_aligned[gap_flag != GapFlag.DATA_GAP]

                aligned[symbol] = df_aligned.dropna(subset=["close"])
            else:
                df["gap_flag"] = np.zeros(len(df), dtype=np.int8)
                df["is_gap"] = False
                aligned[symbol] = df

        return aligned

    @staticmethod
    def align_universe(
        universe_data: Dict[str, pd.DataFrame],
        tf_label: str = "1D",
        drop_data_gap_rows: bool = False,
    ) -> Dict[str, pd.DataFrame]:
        """
        Top-level alignment method. Routes to daily or intraday aligner
        based on tf_label. Returns aligned dict ready for analysis.py.

        Keys in universe_data are "SYMBOL_TFLABEL" format.
        Returns same format with is_gap column added to each DataFrame.

        drop_data_gap_rows: see align_intraday's docstring — default False
        preserves exact existing (production) behavior. Pass True only for
        single-pair/real-timestamp-join consumers, never for anything
        feeding build_returns_matrix's cross-symbol dense alignment.
        """
        # Extract only the requested timeframe
        tf_data = {
            k.replace(f"_{tf_label}", ""): v
            for k, v in universe_data.items()
            if k.endswith(f"_{tf_label}") and v is not None
        }

        if tf_label == "1D":
            return DataAligner.align_daily(tf_data, drop_data_gap_rows=drop_data_gap_rows)
        else:
            return DataAligner.align_intraday(
                tf_data, tf_label, drop_data_gap_rows=drop_data_gap_rows
            )


# =============================================================================
# CLASS 2 — DataCleaner
# =============================================================================

# =============================================================================
# Bar alignment utilities — canonical cutoff and timestamp snapping
# =============================================================================

# NYSE intraday session bar boundaries (minutes after midnight Eastern)
# Used for timestamp snapping to ensure IBKR and yfinance agree on bar stamps.
_SESSION_OPEN_MIN = 9 * 60 + 30  # 9:30 AM ET
_SESSION_CLOSE_MIN = 16 * 60  # 4:00 PM ET

# TF → bar duration in minutes
_TF_MINUTES: Dict[str, int] = {
    "1m": 1,
    "2m": 2,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,  # 4h = 240 minutes
}


def compute_canonical_cutoff(tf_label: str) -> Optional[pd.Timestamp]:
    """
    Compute the last COMPLETE bar boundary for this TF as of right now.

    All fetched data is truncated to this timestamp before saving so that
    every asset in the sweep has data through exactly the same bar —
    regardless of when during the sweep it was fetched.

    Logic:
      - During market hours: floor to the last complete bar open
      - Pre-market: use previous session's last bar open
      - Post-market / weekend: use today's (or Friday's) last bar open

    Returns a timezone-naive Eastern-time timestamp, or None for
    daily/weekly/monthly TFs where partial-bar alignment isn't needed.
    """
    if tf_label not in _TF_MINUTES or tf_label in ("1D", "7D", "1M", "3M", "6M"):
        return None  # daily+ TFs: partial bar not an issue

    bar_mins = _TF_MINUTES[tf_label]
    now_et = pd.Timestamp.now(tz="America/New_York").tz_localize(None)
    today = now_et.normalize()

    open_today = today + pd.Timedelta(minutes=_SESSION_OPEN_MIN)
    close_today = today + pd.Timedelta(minutes=_SESSION_CLOSE_MIN)

    def last_bar_open_on(date: pd.Timestamp) -> pd.Timestamp:
        """Last complete bar open of a given trading session date."""
        open_dt = date + pd.Timedelta(minutes=_SESSION_OPEN_MIN)
        close_dt = date + pd.Timedelta(minutes=_SESSION_CLOSE_MIN)
        session_mins = _SESSION_CLOSE_MIN - _SESSION_OPEN_MIN  # 390 min
        n_complete = session_mins // bar_mins
        last_open_min = (n_complete - 1) * bar_mins
        return open_dt + pd.Timedelta(minutes=last_open_min)

    if now_et < open_today:
        # Pre-market — use previous session
        prev_day = today - pd.Timedelta(days=1)
        while prev_day.dayofweek >= 5:  # skip weekend
            prev_day -= pd.Timedelta(days=1)
        return last_bar_open_on(prev_day)
    elif now_et >= close_today:
        # Post-market — today's last bar is complete
        return last_bar_open_on(today)
    else:
        # During session: floor to last complete bar open
        mins_into_session = (now_et - open_today).total_seconds() / 60
        complete_bars = int(mins_into_session // bar_mins)
        if complete_bars == 0:
            # Haven't completed even one bar today
            prev_day = today - pd.Timedelta(days=1)
            while prev_day.dayofweek >= 5:
                prev_day -= pd.Timedelta(days=1)
            return last_bar_open_on(prev_day)
        last_complete_open = open_today + pd.Timedelta(
            minutes=(complete_bars - 1) * bar_mins
        )
        return last_complete_open


def snap_timestamps(
    df: pd.DataFrame,
    tf_label: str,
    source: str = "ibkr",
) -> pd.DataFrame:
    """
    Normalize bar timestamps to open-of-bar convention, Eastern time,
    timezone-naive.

    Problem: yfinance sometimes stamps intraday bars at bar CLOSE
    (e.g., the 9:30-10:30 bar appears as 10:30). IBKR stamps at bar OPEN
    (same bar appears as 9:30). When correlated, this produces an apparent
    1-bar lead-lag that contaminates cross-source pair comparisons —
    including the ES↔utility 15m finding.

    Fix: snap every timestamp to the nearest valid bar OPEN for this TF
    that falls within the NYSE session, then drop any that don't land
    on a valid boundary (they're off-session bars).

    For daily+ TFs: only normalize timezone (no bar-open snapping needed).
    """
    if df is None or df.empty:
        return df

    df = df.copy()

    # Step 1: normalize to tz-naive Eastern time
    if hasattr(df.index, "tz") and df.index.tz is not None:
        try:
            df.index = df.index.tz_convert("America/New_York").tz_localize(None)
        except Exception:
            df.index = df.index.tz_localize(None)

    if tf_label not in _TF_MINUTES:
        return df  # daily+ TFs: timezone normalize is sufficient

    bar_mins = _TF_MINUTES[tf_label]

    # Step 2: snap each timestamp to the nearest session bar open
    def _snap(ts: pd.Timestamp) -> Optional[pd.Timestamp]:
        """Snap ts to the nearest bar open on the same date within session."""
        day_open = ts.normalize() + pd.Timedelta(minutes=_SESSION_OPEN_MIN)
        day_close = ts.normalize() + pd.Timedelta(minutes=_SESSION_CLOSE_MIN)
        if ts < day_open or ts >= day_close:
            return None  # outside session — drop

        mins_since_open = (ts - day_open).total_seconds() / 60
        # Round to nearest bar boundary
        nearest_bar = round(mins_since_open / bar_mins) * bar_mins
        snapped = day_open + pd.Timedelta(minutes=nearest_bar)

        # Clamp to session
        last_open = day_open + pd.Timedelta(
            minutes=((_SESSION_CLOSE_MIN - _SESSION_OPEN_MIN) // bar_mins - 1)
            * bar_mins
        )
        if snapped > last_open:
            snapped = last_open
        return snapped

    new_idx = [_snap(ts) for ts in df.index]
    valid = [t is not None for t in new_idx]

    df = df[valid].copy()
    df.index = pd.DatetimeIndex([t for t in new_idx if t is not None])

    # Drop duplicates that arose from snapping (keep last — most recent data wins)
    df = df[~df.index.duplicated(keep="last")]
    df.sort_index(inplace=True)
    return df


def truncate_to_cutoff(
    df: pd.DataFrame,
    cutoff: Optional[pd.Timestamp],
) -> pd.DataFrame:
    """
    Drop bars after the canonical cutoff timestamp.
    Ensures every asset in a sweep has data through the same point in time.
    """
    if df is None or df.empty or cutoff is None:
        return df
    # cutoff is the OPEN of the last complete bar — include it
    return df[df.index <= cutoff]


class DataCleaner:
    """
    Cleans raw OHLCV bar data for analytical use.

    Pipeline:
        1. Standardize columns and promote date column to DatetimeIndex
        2. Timestamp snapping (open-of-bar convention, Eastern time, tz-naive)
        3. Canonical cutoff truncation (all assets aligned to same last bar)
        4. Remove duplicate timestamps
        5. Gap detection and forward-fill
        6. Roll adjustment for futures
        7. Dollar-volume liquidity filter
        8. Minimum bar count validation
    """

    _REQUIRED_COLS = {"open", "high", "low", "close", "volume", "average"}
    _NYSE_CALENDAR = None

    @staticmethod
    def clean(
        df: pd.DataFrame,
        symbol: str,
        asset_class: str,
        tf_label: str,
        tf_ibkr: str,
        source: str = "ibkr",
    ) -> Tuple[Optional[pd.DataFrame], QualityReport]:

        original_bars = len(df)
        roll_dates: List[str] = []

        df = DataCleaner._standardize(df)
        if df is None or df.empty:
            return None, QualityReport(
                symbol,
                asset_class,
                tf_label,
                original_bars,
                0,
                original_bars,
                0,
                1.0,
                [],
                passed=False,
                fail_reason="empty_after_standardize",
                source=source,
            )

        df = df[~df.index.duplicated(keep="last")]

        df, gap_count, missing_pct = DataCleaner._fill_gaps(df, tf_ibkr)
        if missing_pct > Config.DATA.MAX_MISSING_PCT:
            return None, QualityReport(
                symbol,
                asset_class,
                tf_label,
                original_bars,
                len(df),
                original_bars - len(df),
                gap_count,
                missing_pct,
                [],
                passed=False,
                fail_reason=f"missing_pct_{missing_pct:.3f}_exceeds_threshold",
                source=source,
            )

        if asset_class in ("futures", "commodity"):
            df, roll_dates = DataCleaner._roll_adjust(df)

        if asset_class == "equity":
            df = DataCleaner._liquidity_filter(df)

        min_bars = Config.DATA.MIN_BARS_REQUIRED.get(tf_label, 100)
        if len(df) < min_bars:
            return None, QualityReport(
                symbol,
                asset_class,
                tf_label,
                original_bars,
                len(df),
                original_bars - len(df),
                gap_count,
                missing_pct,
                roll_dates,
                passed=False,
                fail_reason=f"insufficient_bars_{len(df)}_min_{min_bars}",
                source=source,
            )

        bars_dropped = original_bars - len(df)
        return df, QualityReport(
            symbol,
            asset_class,
            tf_label,
            original_bars,
            len(df),
            bars_dropped,
            gap_count,
            missing_pct,
            roll_dates,
            passed=True,
            source=source,
        )

    @staticmethod
    def _standardize(df: pd.DataFrame) -> Optional[pd.DataFrame]:
        df = df.copy()
        df.columns = [
            c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns
        ]

        # Promote date column to index (ib_insync and some yfinance formats)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
        elif "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.set_index("datetime")

        keep = [c for c in df.columns if c in DataCleaner._REQUIRED_COLS]
        if not all(c in keep for c in ["open", "high", "low", "close"]):
            return None
        df = df[keep]

        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)

        # Strip timezone for uniform handling
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        if "average" in df.columns:
            df = df.rename(columns={"average": "vwap"})
        df = df.sort_index()
        df = df.dropna(subset=["open", "high", "low", "close"])
        return df

    @staticmethod
    def _get_nyse_sessions(start: str, end: str) -> pd.DatetimeIndex:
        if DataCleaner._NYSE_CALENDAR is None:
            DataCleaner._NYSE_CALENDAR = mcal.get_calendar("NYSE")
        schedule = DataCleaner._NYSE_CALENDAR.schedule(start_date=start, end_date=end)
        return mcal.date_range(schedule, frequency="1D").normalize().tz_localize(None)

    @staticmethod
    def _fill_gaps(
        df: pd.DataFrame,
        tf_ibkr: str,
    ) -> Tuple[pd.DataFrame, int, float]:

        INTRADAY = {
            "1 min",
            "2 mins",
            "3 mins",
            "5 mins",
            "15 mins",
            "30 mins",
            "1 hour",
            "4 hours",
        }

        if tf_ibkr in INTRADAY:
            df = df.ffill()
            if "volume" in df.columns:
                df["volume"] = df["volume"].fillna(0)
            return df, 0, 0.0

        if tf_ibkr == "1 day":
            try:
                start = df.index.min().strftime("%Y-%m-%d")
                end = df.index.max().strftime("%Y-%m-%d")
                expected_idx = DataCleaner._get_nyse_sessions(start, end)
                df.index = df.index.normalize()
                gap_count = max(0, len(expected_idx) - len(df))
                missing_pct = gap_count / max(len(expected_idx), 1)
                df = df.reindex(expected_idx)
                df = df.ffill()
                if "volume" in df.columns:
                    df["volume"] = df["volume"].fillna(0)
                return df, gap_count, missing_pct
            except Exception:
                return df, 0, 0.0

        # Weekly / Monthly — no reindexing
        df = df.ffill()
        if "volume" in df.columns:
            df["volume"] = df["volume"].fillna(0)
        return df, 0, 0.0

    @staticmethod
    def _roll_adjust(
        df: pd.DataFrame,
    ) -> Tuple[pd.DataFrame, List[str]]:
        roll_dates: List[str] = []
        df = df.copy()
        returns = df["close"].pct_change().abs()
        roll_idx = returns[returns > 0.05].index
        for roll_date in roll_idx:
            roll_dates.append(str(roll_date.date()))
            loc = df.index.get_loc(roll_date)
            if loc == 0:
                continue
            price_before = df["close"].iloc[loc - 1]
            price_after = df["close"].iloc[loc]
            if price_after == 0:
                continue
            ratio = price_before / price_after
            df.iloc[:loc, df.columns.get_loc("open")] *= ratio
            df.iloc[:loc, df.columns.get_loc("high")] *= ratio
            df.iloc[:loc, df.columns.get_loc("low")] *= ratio
            df.iloc[:loc, df.columns.get_loc("close")] *= ratio
        return df, roll_dates

    @staticmethod
    def _liquidity_filter(df: pd.DataFrame) -> pd.DataFrame:
        if "volume" not in df.columns:
            return df
        df = df.copy()
        dollar_vol = df["close"] * df["volume"]
        illiquid = dollar_vol < Config.DATA.MIN_DOLLAR_VOLUME
        df.loc[illiquid, ["open", "high", "low", "close"]] = np.nan
        df = df.ffill()
        return df


# =============================================================================
# CLASS 3 — YFinanceFeed
# Bulk equity data via yfinance. Fast, chunked, no rate limits for daily.
# =============================================================================


class YFinanceFeed:
    """
    Downloads historical OHLCV data for S&P 500 equities using yfinance.

    Strategy:
    - Daily, weekly, monthly: yfinance bulk download, full history (~20+ years)
    - Intraday (1h and finer): separate per-ticker downloads with depth limits
      enforced by Yahoo's API (1h=730d, 5m/2m=60d, 1m=7d)

    Downloads in chunks of Config.DATA.YF_CHUNK_SIZE tickers to balance
    speed and memory. Each chunk is cached to disk before the next begins.

    yfinance MultiIndex columns: (Price, Ticker) — flattened per ticker
    before passing to DataCleaner.

    SESSION HANDLING — do NOT pass a custom session to yf.Ticker().
    yfinance 0.2.66+ uses curl_cffi internally for its HTTP layer and
    explicitly rejects any other session type at runtime: "Yahoo API
    requires curl_cffi session not requests.sessions.Session. Solution:
    stop setting session, let YF handle." A prior fix attempt added a
    shared requests.Session (hypothesizing cookie/crumb renegotiation
    overhead under rapid sequential Ticker() calls as the cause of a
    100%-failure pattern) — this was wrong for this yfinance version and
    was reverted. yfinance manages its own session/cookie/crumb caching
    internally across Ticker() instantiations within a process; let it.
    The actual mitigation for burst-rate concerns is the small
    inter-request delay applied in the Phase 2A calling loop, not a
    custom session object.
    """

    # yfinance fetches daily/weekly/monthly only.
    # Intraday (1m through 8h) fetched from IBKR for proper historical depth:
    #   IBKR 1h  → 5Y,  IBKR 4h/8h → 10Y,  IBKR 1m → 42D
    # yfinance intraday depths are too shallow for meaningful analysis:
    #   yfinance 1h → 730D,  yfinance 5m → 60D,  yfinance 1m → 7D
    _YF_INTERVALS: List[Tuple[str, str, str]] = [
        # (yf_interval, tf_label, max_period)
        # 7D and 1M are NOT fetched directly from yfinance.
        # They are derived from 1D by resampling in _resample_from_daily().
        # This ensures consistent trading-week and calendar-month alignment
        # across equities, crypto, forex, commodities, and futures.
        ("1d", "1D", "max"),
    ]

    @staticmethod
    def _resample_from_daily(df_1d: pd.DataFrame) -> Dict[str, Optional[pd.DataFrame]]:
        """
        Derive 7D (weekly) and 1M (monthly) bars from a 1D DataFrame.

        Week anchor: W-FRI (Friday) — standard US trading week convention.
        Each weekly bar runs Mon open → Fri close, stamped at Friday.
        This is consistent across equities, crypto, and commodities because
        all use the same 1D source data with market-appropriate trading calendars.

        Month anchor: MS (month start) with label="left" — bar stamped at
        the first trading day of the month.

        OHLCV aggregation:
          open   = first bar of period
          high   = max of period
          low    = min of period
          close  = last bar of period
          volume = sum of period
          vwap   = volume-weighted mean close (proxy — true VWAP unavailable)

        Returns {tf_label: resampled_df} for "7D" and "1M".
        """
        out: Dict[str, Optional[pd.DataFrame]] = {}
        if df_1d is None or df_1d.empty or "close" not in df_1d.columns:
            out["7D"] = None
            out["1M"] = None
            return out

        agg = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
        # Only aggregate columns that exist
        agg = {k: v for k, v in agg.items() if k in df_1d.columns}

        for tf_label, rule, lbl, cls_ in [
            ("7D", "W-FRI", "right", "right"),  # stamp = Friday (week close)
            ("1M", "MS", "left", "left"),  # stamp = first trading day of month
            ("3M", "QS", "left", "left"),  # stamp = first trading day of quarter
            ("6M", "2QS", "left", "left"),  # stamp = first day of each half-year
        ]:
            try:
                resampled = df_1d.resample(rule, label=lbl, closed=cls_).agg(agg)
                # Drop empty periods (weeks/months with no trading days)
                resampled = resampled.dropna(subset=["close"])
                resampled = resampled[resampled["close"] > 0]
                resampled["is_gap"] = False
                out[tf_label] = resampled
            except Exception as e:
                log.debug(f"Resample {tf_label} failed: {e}")
                out[tf_label] = None
        return out

    @staticmethod
    def get_equity_history(
        tickers: List[str],
        chunk_size: int = 50,
        yf_tickers: List[str] = None,
        period: str = None,  # override max_period (e.g. "1mo" for incremental)
    ) -> Dict[str, Dict[str, Optional[pd.DataFrame]]]:
        """
        Download full history for a list of tickers using yfinance.

        Handles both equities (BRK B → BRK-B) and crypto (BTC → BTC-USD).

        Parameters
        ----------
        tickers    : IBKR-format ticker list (used as result keys)
        chunk_size : tickers per batch
        yf_tickers : yfinance-format ticker list (parallel to tickers).
                     If None, defaults to space→hyphen conversion of tickers.

        Returns dict: {ibkr_symbol: {tf_label: DataFrame}}
        """
        if yf_tickers is None:
            yf_tickers = [t.replace(" ", "-") for t in tickers]

        # Build parallel lists for chunking
        pairs = list(zip(tickers, yf_tickers))
        chunks = [pairs[i : i + chunk_size] for i in range(0, len(pairs), chunk_size)]

        results: Dict[str, Dict[str, Optional[pd.DataFrame]]] = {}

        log.info(
            f"yfinance: downloading {len(tickers)} assets "
            f"in {len(chunks)} chunks of {chunk_size}"
        )

        for chunk_idx, chunk_pairs in enumerate(chunks):
            chunk_ibkr = [p[0] for p in chunk_pairs]
            chunk_yf = [p[1] for p in chunk_pairs]
            log.info(
                f"  Chunk {chunk_idx+1}/{len(chunks)}: "
                f"{chunk_ibkr[0]} → {chunk_ibkr[-1]} ({len(chunk_ibkr)} tickers)"
            )

            for yf_interval, tf_label, max_period in YFinanceFeed._YF_INTERVALS:
                _period = period if period is not None else max_period
                chunk_data = YFinanceFeed._download_chunk(
                    chunk_ibkr,
                    yf_interval,
                    tf_label,
                    _period,
                    yf_tickers=chunk_yf,
                )
                for symbol, df in chunk_data.items():
                    if symbol not in results:
                        results[symbol] = {}
                    results[symbol][tf_label] = df
                    # Derive 7D and 1M from 1D by resampling
                    if tf_label == "1D" and df is not None:
                        derived = YFinanceFeed._resample_from_daily(df)
                        for derived_tf, derived_df in derived.items():
                            results[symbol][derived_tf] = derived_df

            # Retry any tickers that failed (got None for daily) individually
            failed = [
                (ibkr, yf_t)
                for ibkr, yf_t in zip(chunk_ibkr, chunk_yf)
                if results.get(ibkr, {}).get("1D") is None
            ]
            if failed:
                log.info(f"  Retrying {len(failed)} failed tickers individually")
                for ibkr_sym, yf_sym in failed:
                    for yf_interval, tf_label, max_period in YFinanceFeed._YF_INTERVALS:
                        try:
                            _period = period if period is not None else max_period
                            import contextlib, io

                            with contextlib.redirect_stderr(io.StringIO()):
                                raw = yf.download(
                                    yf_sym,
                                    period=_period,  # use overridden period
                                    interval=yf_interval,
                                    auto_adjust=True,
                                    progress=False,
                                    threads=False,
                                )
                            if raw is not None and not raw.empty:
                                if isinstance(raw.columns, pd.MultiIndex):
                                    try:
                                        raw = raw.xs(yf_sym, axis=1, level=1)
                                    except Exception:
                                        raw = raw.xs(yf_sym, axis=1, level=0)
                                cleaned, _ = DataCleaner.clean(
                                    raw,
                                    ibkr_sym,
                                    "equity",
                                    tf_label,
                                    tf_label,
                                    source="yfinance",
                                )
                                if ibkr_sym not in results:
                                    results[ibkr_sym] = {}
                                results[ibkr_sym][tf_label] = cleaned
                                # Derive 7D and 1M from 1D in retry path too
                                if tf_label == "1D" and cleaned is not None:
                                    derived = YFinanceFeed._resample_from_daily(cleaned)
                                    for derived_tf, derived_df in derived.items():
                                        results[ibkr_sym][derived_tf] = derived_df
                        except Exception:
                            pass

            # Cache daily/weekly/monthly — intraday handled separately by IBKR
            for ibkr_sym in chunk_ibkr:
                sym_data = results.get(ibkr_sym, {})
                for tf_lbl, df in sym_data.items():
                    if df is not None:
                        DataStore.save(ibkr_sym, tf_lbl, df)

        return results

    @staticmethod
    def _download_chunk(
        tickers: List[str],
        yf_interval: str,
        tf_label: str,
        max_period: str,
        yf_tickers: List[str] = None,
    ) -> Dict[str, Optional[pd.DataFrame]]:
        """
        Download one interval for a chunk of tickers using yf.download().
        Returns {ibkr_symbol: cleaned_DataFrame}.

        yf_tickers: pre-converted yfinance format (e.g. BRK-B, BTC-USD).
                    If None, defaults to space→hyphen conversion of tickers.
        """
        if yf_tickers is None:
            yf_tickers = [t.replace(" ", "-") for t in tickers]

        # Full ticker→yf map (including cached ones for result assembly)
        full_ticker_map = {yf: ibkr for yf, ibkr in zip(yf_tickers, tickers)}

        # Check cache first
        uncached_pairs = [
            (ibkr, yf)
            for ibkr, yf in zip(tickers, yf_tickers)
            if not DataStore.is_fresh(
                ibkr, tf_label, max_age_hours=DataStore.intraday_max_age_hours(tf_label)
            )
        ]
        if not uncached_pairs:
            log.debug(f"    {tf_label}: all {len(tickers)} tickers cached — skipping")
            return {t: DataStore.load(t, tf_label) for t in tickers}

        uncached_ibkr = [p[0] for p in uncached_pairs]
        uncached_yf = [p[1] for p in uncached_pairs]
        ticker_map = {yf: ibkr for ibkr, yf in uncached_pairs}

        try:
            # Suppress yfinance's own stderr output — we handle errors ourselves
            import contextlib, io

            with contextlib.redirect_stderr(io.StringIO()):
                raw = yf.download(
                    yf_tickers,
                    period=max_period,
                    interval=yf_interval,
                    auto_adjust=True,
                    progress=False,
                    threads=True,
                    # No group_by — default MultiIndex is (Price, Ticker)
                    # with tickers at level=1, matching our extraction code.
                    # group_by="ticker" puts tickers at level=0 which breaks extraction.
                )
        except Exception as e:
            log.warning(f"    yfinance download failed {tf_label}: {e}")
            # Found overnight (2026-06-23): was `uncached` (undefined name —
            # NameError), masking the real yfinance exception and crashing
            # the whole chunked download uncaught instead of gracefully
            # marking this chunk's tickers as failed. Result dict is keyed
            # by IBKR symbol (see "result[ibkr_ticker] = ..." below).
            return {t: None for t in uncached_ibkr}

        if raw is None or raw.empty:
            log.warning(f"    yfinance returned empty for {tf_label}")
            return {t: None for t in uncached_ibkr}

        result = {}

        # yfinance MultiIndex extraction — robust to both column orientations:
        # Standard (no group_by): (Price, Ticker) → tickers at level=1
        # group_by="ticker":      (Ticker, Price) → tickers at level=0
        for yf_ticker, ibkr_ticker in ticker_map.items():
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    # Try level=1 first (standard), then level=0 (group_by format)
                    for lvl in (1, 0):
                        if yf_ticker in raw.columns.get_level_values(lvl):
                            df_raw = raw.xs(yf_ticker, axis=1, level=lvl)
                            break
                    else:
                        result[ibkr_ticker] = None
                        continue
                else:
                    # Single ticker download — raw is already flat
                    df_raw = raw.copy()

                cleaned, report = DataCleaner.clean(
                    df_raw, ibkr_ticker, "equity", tf_label, tf_label
                )
                result[ibkr_ticker] = cleaned
                if not report.passed:
                    log.debug(f"    {ibkr_ticker} {tf_label}: {report.fail_reason}")

            except Exception as e:
                log.debug(f"    {ibkr_ticker} {tf_label} extract failed: {e}")
                result[ibkr_ticker] = None

        # Return cached tickers not in this download batch
        for t in tickers:
            if t not in result:
                result[t] = DataStore.load(t, tf_label)

        return result

    @staticmethod
    def _resample(df: pd.DataFrame, rule: str) -> Optional[pd.DataFrame]:
        """Resample OHLCV to coarser timeframe. Open=first, H=max, L=min, C=last, V=sum."""
        try:
            agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
            if "volume" in df.columns:
                agg["volume"] = "sum"
            # 4h fixed 2026-06-20: plain df.resample("4h") clock-aligns bins
            # to 00:00/04:00/08:00/12:00/16:00/20:00, NOT market open. For a
            # 9:30-16:00 NYSE session that puts real bars in the 08:00 and
            # 12:00 buckets — stamped wrong and with the overnight gap
            # dominating frequency checks. origin="start_day" + offset=
            # "9h30min" anchors bins to 09:30/13:30 instead (confirmed via
            # direct test: was producing 08:00/12:00 stamps with a 20h
            # median gap before this fix).
            if rule == "4h":
                resampled = (
                    df.resample(rule, origin="start_day", offset="9h30min")
                    .agg(agg)
                    .dropna(subset=["open", "close"])
                )
            else:
                resampled = df.resample(rule).agg(agg).dropna(subset=["open", "close"])
            return resampled if len(resampled) >= 2 else None
        except Exception as e:
            log.debug(f"Resample failed ({rule}): {e}")
            return None

    # yfinance intraday interval mapping: tf_label → (yf_interval, max_period)
    _YF_INTRADAY_MAP: Dict[str, Tuple[str, str]] = {
        "4h": ("1h", "730d"),  # resample from 1h
        "1h": ("1h", "730d"),
        "30m": ("30m", "60d"),
        "15m": ("15m", "60d"),
        "5m": ("5m", "60d"),
        "3m": ("1m", "5d"),  # resample from 1m; Yahoo 1m limit = 8 days
        "2m": ("2m", "55d"),  # 55d ≈ 39 trading days; within 60-calendar-day API limit
        "1m": ("1m", "5d"),  # Yahoo 1m hard limit = 8 days; 5d is safe
    }

    # TFs that require resampling from their yfinance source interval
    _YF_RESAMPLE_RULES: Dict[str, str] = {
        "4h": "4h",
        "3m": "3min",
    }

    @staticmethod
    def get_intraday_fallback(
        symbol: str,
        asset_class: str,
        tf_label: str,
    ) -> Optional[pd.DataFrame]:
        """
        yfinance fallback for intraday bars when IBKR fails or returns no data.

        Attempts to download the closest available yfinance interval,
        resampling to the target TF where necessary (4h from 1h, 3m from 1m).
        Tags the returned data with source="yfinance" or "yfinance_resampled"
        via DataCleaner so the QualityReport records the data provenance.

        Returns cleaned DataFrame or None if unavailable.
        """
        if tf_label not in YFinanceFeed._YF_INTRADAY_MAP:
            return None

        yf_interval, period = YFinanceFeed._YF_INTRADAY_MAP[tf_label]
        needs_resample = tf_label in YFinanceFeed._YF_RESAMPLE_RULES
        source_tag = "yfinance_resampled" if needs_resample else "yfinance"

        # Build yfinance ticker format
        if asset_class == "crypto":
            yf_sym = f"{symbol}-USD"
        elif asset_class == "forex":
            yf_sym = symbol.replace(".", "") + "=X"
        elif asset_class in ("futures", "commodity"):
            yf_sym = f"{symbol}=F"  # GC → GC=F, NQ → NQ=F, ZN → ZN=F
        else:
            yf_sym = symbol.replace(" ", "-")

        # Load cached working period for this ticker/interval
        _pkey = f"yf_period_{symbol.replace(' ','_')}_{yf_interval}"
        try:
            _pmeta = DataStore.load(_pkey, "meta")
            if _pmeta is not None and not _pmeta.empty:
                period = str(_pmeta.iloc[0]["period"])
        except Exception:
            pass

        # Download via yf.Ticker().history() — NOT yf.download().
        #
        # Empirically verified (2026-06-18 user test script): .history() with
        # a plain period string ("7d" for 1m, "60d" for 5m/2m/30m/15m, "730d"
        # for 1h) succeeds reliably, including 1m which previously failed
        # 100% of the time under yf.download() with explicit start/end dates.
        #
        # A prior fix attempted to solve a (real) period-ambiguity concern by
        # switching to explicit start/end timestamps via yf.download(). That
        # introduced a worse bug: the day-count table was keyed by tf_label
        # instead of the underlying yf_interval, so "3m" (which downloads at
        # yf_interval="1m") was requesting a 55-day span at 1m granularity —
        # nearly 7x over Yahoo's 8-day hard limit for 1m data. This silently
        # failed for every single asset. Reverting to the simpler, proven
        # period-string approach removes the whole class of bug along with it.
        #
        # _YF_INTRADAY_MAP already encodes the correct conservative period
        # per yf_interval (1m→5d, 2m→55d, 5m/15m/30m→60d, 1h→730d) — trust it.
        _attempts = [period] if period != "max" else ["max"]
        if period != "max":
            _attempts.append("max")  # final fallback for edge cases

        # Defensive guard: validate period format before it ever reaches the
        # API. Catches any malformed period string (e.g. a stray text label
        # from a mismatched or partially-merged file) with a clear, specific
        # error instead of a cryptic per-asset API failure.
        import re as _re

        _VALID_PERIOD = _re.compile(
            r"^(\d+d|\d+mo|\d+y|1d|5d|1mo|3mo|6mo|1y|2y|5y|10y|ytd|max)$"
        )
        _attempts = [p for p in _attempts if _VALID_PERIOD.match(p)]
        if not _attempts:
            log.error(
                f"yfinance {symbol} {tf_label}: no valid period strings "
                f"after validation (got {[period, 'max']}) — this indicates "
                f"a corrupted _YF_INTRADAY_MAP entry or a stale/mismatched "
                f"data.py file. Skipping."
            )
            return None

        raw = None
        worked_period = None
        for _try_period in _attempts:
            try:
                import contextlib, io

                with contextlib.redirect_stderr(io.StringIO()):
                    # DO NOT pass a custom session. yfinance 0.2.66+ uses
                    # curl_cffi internally for its HTTP layer and explicitly
                    # rejects a plain requests.Session — confirmed directly
                    # via the library's own runtime error: "Yahoo API
                    # requires curl_cffi session not requests.sessions.
                    # Session. Solution: stop setting session, let YF
                    # handle." (BUG-D31 follow-up, 2026-06-19.)
                    #
                    # yfinance manages its own session/cookie/crumb caching
                    # internally across Ticker() instantiations within the
                    # same process — a DIY session override was actively
                    # breaking that mechanism rather than helping it.
                    # The inter-request delay (set in the calling loop) is
                    # the correct mitigation for burst-rate concerns, not a
                    # custom session.
                    r = yf.Ticker(yf_sym).history(
                        period=_try_period,
                        interval=yf_interval,
                        auto_adjust=True,
                    )
                if r is not None and not r.empty:
                    raw = r
                    worked_period = _try_period
                    break
                else:
                    # RE-ELEVATED to WARNING (2026-06-19): removing the bad
                    # session fixed the self-inflicted YFDataException, but
                    # the underlying 100%-failure pattern persisted with NO
                    # exception text visible — meaning this branch (silent
                    # empty result) IS actually firing, contrary to what was
                    # assumed when this was dialed back to DEBUG minutes
                    # earlier. That was premature. Keeping at WARNING until
                    # we have direct evidence of what's actually happening.
                    log.warning(
                        f"yfinance {symbol} {tf_label} "
                        f"[period={_try_period}]: returned EMPTY (no exception) "
                        f"— ticker={yf_sym}, interval={yf_interval}, "
                        f"rows_returned={0 if r is None else len(r)}"
                    )
            except Exception as e:
                _err_str = str(e)
                _is_network_error = any(
                    s in _err_str
                    for s in (
                        "DNSError",
                        "Could not resolve host",
                        "ConnectionError",
                        "Network is unreachable",
                        "Failed to establish a new connection",
                    )
                )
                if _is_network_error:
                    log.error(
                        f"NETWORK ERROR (not a data issue) — {symbol} {tf_label}: "
                        f"{type(e).__name__}: {e}. Check internet connection."
                    )
                else:
                    _log_fn = log.warning if worked_period is None else log.debug
                    _log_fn(
                        f"yfinance {symbol} {tf_label} "
                        f"[period={_try_period}] {type(e).__name__}: {e}"
                    )

        if raw is None or raw.empty:
            log.debug(
                f"yfinance {symbol} {tf_label}: all periods tried "
                f"({_attempts}) — ticker may be delisted or genuinely "
                f"unavailable at this interval"
            )
            return None

        # Validate returned frequency matches the requested TF.
        # yfinance silently returns daily bars when intraday isn't available.
        # Daily data has ~82800-86400s median gap; 1h expects 3600s.
        # Saving daily data to a 1h/4h cache file is the contamination bug.
        _expected_gap = DataStore._EXPECTED_GAP_SECONDS.get(tf_label)
        if _expected_gap and len(raw) > 10:
            try:
                _idx = pd.to_datetime(raw.index)
                _med = float(
                    _idx.to_series().diff().dt.total_seconds().dropna().median()
                )
                if _med > _expected_gap * 3:
                    log.debug(
                        f"yfinance {symbol} {tf_label}: wrong frequency "
                        f"(expected ~{_expected_gap}s, got {_med:.0f}s) — discarding"
                    )
                    return None
            except Exception:
                pass

        # Cache the attempt label that worked (if it was a fallback, not the primary)
        if worked_period and _attempts and worked_period != _attempts[0][0]:
            try:
                DataStore.save(_pkey, "meta", pd.DataFrame([{"period": worked_period}]))
            except Exception:
                pass

        # Flatten MultiIndex if present (single ticker returns MultiIndex)
        if isinstance(raw.columns, pd.MultiIndex):
            try:
                raw = raw.xs(yf_sym, axis=1, level=1)
            except Exception:
                raw.columns = [
                    c[0].lower() if isinstance(c, tuple) else c.lower()
                    for c in raw.columns
                ]

        # Clean with source tag — tf_ibkr passed as tf_label since yfinance
        # doesn't use IBKR bar size strings; DataCleaner handles both formats
        cleaned, report = DataCleaner.clean(
            raw,
            symbol,
            asset_class,
            tf_label,
            tf_label,
            source=source_tag,
        )
        if cleaned is None:
            return None

        # Resample to target TF if needed
        if needs_resample:
            rule = YFinanceFeed._YF_RESAMPLE_RULES[tf_label]
            resampled = YFinanceFeed._resample(cleaned, rule)
            return resampled

        return cleaned


# =============================================================================
# CLASS 4 — IBKRFeed
# IBKR Gateway connection for futures, forex, crypto, commodities.
# Also handles equity intraday gaps (3m) not available from yfinance.
# =============================================================================


class ConIdCache:
    """
    Caches IBKR contract IDs (conId) to skip the per-request
    symbol-to-exchange string resolution step.

    First successful request: IBKR resolves "AAPL" to conId 265598.
    All subsequent requests: build Contract(conId=265598) directly.
    Saves ~0.5-1s per request = 750-1500s total for 1,500 assets.
    Persisted to output/cache/conid_cache.json between sessions.
    """

    _PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "output",
        "cache",
        "conid_cache.json",
    )
    _cache: Dict[str, int] = {}
    _dirty = False

    @classmethod
    def load(cls) -> None:
        if os.path.exists(cls._PATH):
            try:
                with open(cls._PATH) as f:
                    cls._cache = json.load(f)
                log.debug(f"ConIdCache: {len(cls._cache)} entries loaded")
            except Exception:
                cls._cache = {}

    @classmethod
    def save(cls) -> None:
        if not cls._dirty:
            return
        try:
            os.makedirs(os.path.dirname(cls._PATH), exist_ok=True)
            with open(cls._PATH, "w") as f:
                json.dump(cls._cache, f, indent=2)
            cls._dirty = False
            log.debug(f"ConIdCache: {len(cls._cache)} entries saved")
        except Exception as e:
            log.debug(f"ConIdCache save failed: {e}")

    @classmethod
    def get(cls, symbol: str) -> Optional[int]:
        return cls._cache.get(symbol)

    @classmethod
    def put(cls, symbol: str, con_id: int) -> None:
        if con_id and con_id != 0 and cls._cache.get(symbol) != con_id:
            cls._cache[symbol] = con_id
            cls._dirty = True


class IBKRFeed:
    """
    Pulls historical OHLCV bars from IBKR Gateway.

    Primary use: non-equity asset classes (futures, forex, crypto, commodities)
    Secondary use: equity 3m bars (not available from yfinance)

    Includes:
    - Automatic reconnection on disconnect (retry every 60s, exit after 30min)
    - IBKR maintenance window awareness (11pm-1am ET)
    - Progressive pacing backoff for intraday requests
    - Config-hash-aware permanent cache
    """

    _MAX_DURATION: Dict[str, str] = {
        "1 min": "42 D",
        "2 mins": "42 D",
        "3 mins": "42 D",
        "5 mins": "6 M",
        "15 mins": "1 Y",
        "30 mins": "2 Y",
        "1 hour": "5 Y",
        "4 hours": "10 Y",
        "1 day": "20 Y",
        "1W": "20 Y",
        "1M": "20 Y",
    }

    _FUTURES_EXCHANGE: Dict[str, str] = {
        "ES": "CME",
        "NQ": "CME",
        "RTY": "CME",
        "YM": "CBOT",
        "GC": "COMEX",
        "SI": "COMEX",
        "CL": "NYMEX",
        "NG": "NYMEX",
        "ZC": "CBOT",
        "ZW": "CBOT",
        "ZS": "CBOT",
        "ZN": "CBOT",
        "ZB": "CBOT",
        "HG": "COMEX",
    }

    def __init__(self):
        self._ib = ibi.IB()
        self._connected = False
        self._req_delay = 5.0
        self._intraday_delay = 12.0
        self._intraday_count = 0
        self._total_req_count = 0
        self._last_req = 0.0
        self._consecutive_fails = 0
        self._circuit_open = False
        self._circuit_open_at = 0.0
        self._circuit_open_count = 0
        self._tf_ibkr_disabled: set = set()
        self._tf_ibkr_attempts = 0
        self._tf_ibkr_successes = 0
        self._upstream_broken = False  # set True on Warning 2110 — reconnect futile
        self._session_dead = False  # set True after 30-min reconnect failure

    # ------------------------------------------------------------------
    # Connection management with auto-reconnect
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Connect to IBKR Gateway. Returns True on success."""
        try:
            self._ib.connect(
                Config.IBKR.HOST,
                Config.IBKR.PORT,
                clientId=Config.IBKR.CLIENT_ID,
                readonly=Config.IBKR.READONLY,
                timeout=Config.IBKR.TIMEOUT,
            )
            self._connected = True
            self._ib.errorEvent += self._on_ibkr_error
            log.info(f"IBKR connected  →  {Config.IBKR.HOST}:{Config.IBKR.PORT}")
            return True
        except Exception as e:
            if "refused" in str(e).lower() or "1225" in str(e):
                log.error(
                    "IBKR connection refused — is Gateway running and API enabled?"
                )
            else:
                log.error(f"IBKR connection failed: {e}")
            return False

    def reconnect(self, max_wait_minutes: int = 30) -> bool:
        """
        Attempt to reconnect to IBKR Gateway after a disconnection.

        Retries every 90 seconds for up to max_wait_minutes (default 30 min).
        If reconnect times out, returns False and caller falls back to yfinance.

        Returns True if reconnected, False if timed out.
        """
        # If the session is already known dead (previous reconnect failed),
        # return immediately — don't burn another 30 minutes.
        # This prevents the infinite loop where every asset failure in the
        # last TF (1m) triggers a new 30-minute reconnect cycle.
        if self._session_dead:
            log.debug("Session already dead — skipping reconnect attempt")
            return False

        deadline = time.time() + (max_wait_minutes * 60)
        attempt = 0

        log.warning(
            f"IBKR disconnected — retrying every 90s for up to "
            f"{max_wait_minutes} minutes then falling back to yfinance"
        )

        # Brief initial wait for transient disconnects to self-resolve
        time.sleep(10)

        while time.time() < deadline:
            # Skip during maintenance window
            et_hour = datetime.now(timezone.utc).hour - 4  # rough ET offset
            if (
                _MAINTENANCE_START_ET <= et_hour % 24
                or et_hour % 24 < _MAINTENANCE_END_ET
            ):
                remaining = deadline - time.time()
                log.info(
                    f"  IBKR maintenance window — waiting 5min (reconnect deadline in {remaining/60:.0f}min)"
                )
                time.sleep(300)
                continue

            if self._upstream_broken:
                log.warning("  Warning 2110: TWS upstream dead — exiting reconnect")
                return False

            attempt += 1
            log.info(f"  Reconnect attempt {attempt} ...")

            try:
                if self._ib.isConnected():
                    self._ib.disconnect()
                    time.sleep(2)
                self._ib = ibi.IB()
                self._ib.connect(
                    Config.IBKR.HOST,
                    Config.IBKR.PORT,
                    clientId=Config.IBKR.CLIENT_ID,
                    readonly=Config.IBKR.READONLY,
                    timeout=Config.IBKR.TIMEOUT,
                )
                self._connected = True
                log.info(f"  Reconnected on attempt {attempt}")
                self._upstream_broken = False
                return True
            except Exception as e:
                log.warning(f"  Attempt {attempt} failed: {e}")
                time.sleep(90)

        log.warning(
            f"Could not reconnect after {max_wait_minutes} minutes — "
            f"TWS is down for this session. Setting kill switch: "
            f"all future TFs will skip IBKR immediately."
        )
        self._session_dead = True
        return False

    def _on_ibkr_error(self, reqId, errorCode, errorString, contract) -> None:
        """Handle IBKR 1100/1102 events for circuit breaker."""
        if errorCode == 1100:
            log.warning("Error 1100: IBKR lost — circuit opening")
            self._circuit_open = True
            self._circuit_open_at = time.time()
            self._connected = False
        elif errorCode == 1102:
            log.info("Error 1102: IBKR restored — circuit resets in 30s")
            self._circuit_open_at = time.time() - 270
        elif errorCode == 2110:
            log.warning("Warning 2110: TWS upstream broken — reconnect futile")
            self._upstream_broken = True

    def disconnect(self) -> None:
        if self._connected:
            self._ib.disconnect()
            self._connected = False
            log.info("IBKR disconnected")

    def ensure_connected(self) -> bool:
        """Check connection and attempt reconnect if dropped."""
        if self._ib.isConnected():
            return True
        self._connected = False
        return self.reconnect()

    # ------------------------------------------------------------------
    # Contract construction
    # ------------------------------------------------------------------

    def _build_contract(self, symbol: str, asset_class: str) -> Optional[ibi.Contract]:
        try:
            if asset_class == "equity":
                return ibi.Stock(symbol, "SMART", "USD")
            elif asset_class == "crypto":
                return ibi.Crypto(symbol, "PAXOS", "USD")
            elif asset_class == "forex":
                pair = symbol.replace(".", "")
                return ibi.Forex(pair)
            elif asset_class in ("futures", "commodity"):
                exch = self._FUTURES_EXCHANGE.get(symbol, "CME")
                cached_con = IBKRFeed._load_contract_cache(symbol)
                if cached_con is not None:
                    return cached_con
                contract = ibi.Future(symbol, exchange=exch, currency="USD")
                try:
                    # Use reqContractDetails — unlike qualifyContracts it does NOT
                    # raise an exception when multiple expiry months are found.
                    # Returns a list of ContractDetails objects; extract .contract.
                    details = self._ib.reqContractDetails(contract)
                    if not details:
                        log.warning(f"No contract details for {symbol} on {exch}")
                        return None

                    contracts = [d.contract for d in details]
                    if len(contracts) == 1:
                        return contracts[0]

                    # Select front month: nearest expiry that has not yet passed
                    today = datetime.now().strftime("%Y%m%d")
                    candidates = [
                        c
                        for c in contracts
                        if str(getattr(c, "lastTradeDateOrContractMonth", "0"))[:8]
                        >= today
                    ]
                    pool = candidates if candidates else contracts
                    pool.sort(
                        key=lambda c: str(
                            getattr(c, "lastTradeDateOrContractMonth", "0")
                        )
                    )
                    front = pool[0]
                    log.info(
                        f"{symbol}: front month "
                        f"{getattr(front, 'lastTradeDateOrContractMonth', '')} "
                        f"({getattr(front, 'localSymbol', '')})"
                    )
                    IBKRFeed._save_contract_cache(symbol, front)
                    return front

                except Exception as qe:
                    log.warning(f"Futures contract details error {symbol}: {qe}")
                    return None
            else:
                return None
        except Exception as e:
            log.error(f"Contract build failed for {symbol} ({asset_class}): {e}")
            return None

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _wait_rate_limit(self, tf_ibkr: str = "") -> None:
        """
        Enforce per-request delay with intraday-specific pacing.
        Extra 10s buffer every 3rd consecutive intraday request.
        """
        INTRADAY_SIZES = {
            "1 min",
            "2 mins",
            "3 mins",
            "5 mins",
            "15 mins",
            "30 mins",
            "1 hour",
            "4 hours",
        }
        is_intraday = tf_ibkr in INTRADAY_SIZES

        if is_intraday:
            self._intraday_count += 1
            delay = self._intraday_delay
            if self._intraday_count % 3 == 0:
                delay += 10
                log.debug(
                    f"  Extra pacing buffer after {self._intraday_count} consecutive intraday requests"
                )
        else:
            self._intraday_count = 0
            delay = self._req_delay

        # Session-level cooldown every 5 requests
        self._total_req_count += 1
        if self._total_req_count % 5 == 0:
            delay = max(delay, 15)
        elapsed = time.time() - self._last_req
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_req = time.time()

    # ------------------------------------------------------------------
    # Core data fetch
    # ------------------------------------------------------------------

    _CONTRACT_CACHE_DIR = os.path.join(
        os.path.dirname(__file__), "output", "cache", "contracts"
    )

    @staticmethod
    def _load_contract_cache(symbol: str):
        try:
            path = os.path.join(IBKRFeed._CONTRACT_CACHE_DIR, f"{symbol}.json")
            if not os.path.exists(path):
                return None
            if (time.time() - os.path.getmtime(path)) / 86400 > 30:
                return None
            with open(path) as f:
                d = json.load(f)
            c = ibi.Contract()
            c.conId = d["conId"]
            c.symbol = d["symbol"]
            c.secType = "FUT"
            c.exchange = d["exchange"]
            c.currency = d.get("currency", "USD")
            c.localSymbol = d.get("localSymbol", "")
            c.lastTradeDateOrContractMonth = d.get("expiry", "")
            log.debug(f"Contract cache: {symbol} → {d.get('localSymbol','')}")
            return c
        except Exception:
            return None

    @staticmethod
    def _save_contract_cache(symbol: str, contract) -> None:
        try:
            os.makedirs(IBKRFeed._CONTRACT_CACHE_DIR, exist_ok=True)
            with open(
                os.path.join(IBKRFeed._CONTRACT_CACHE_DIR, f"{symbol}.json"), "w"
            ) as f:
                json.dump(
                    {
                        "symbol": symbol,
                        "conId": getattr(contract, "conId", 0),
                        "exchange": getattr(contract, "exchange", ""),
                        "currency": getattr(contract, "currency", "USD"),
                        "localSymbol": getattr(contract, "localSymbol", ""),
                        "expiry": getattr(contract, "lastTradeDateOrContractMonth", ""),
                        "cached_at": datetime.now().isoformat(),
                    },
                    f,
                )
        except Exception as e:
            log.debug(f"Contract cache save {symbol}: {e}")

    @staticmethod
    def _what_to_show(asset_class: str, tf_ibkr: str) -> str:
        if asset_class == "equity":
            return "ADJUSTED_LAST" if tf_ibkr == "1 day" else "TRADES"
        elif asset_class in ("futures", "commodity"):
            return "TRADES"
        else:
            return "MIDPOINT"

    @staticmethod
    def _shorter_duration(requested: str, maximum: str) -> str:
        unit_days = {"D": 1, "M": 30, "Y": 365}

        def to_days(s: str) -> int:
            parts = s.strip().split()
            if len(parts) != 2:
                return 0
            n, unit = parts
            return int(n) * unit_days.get(unit.upper(), 1)

        return requested if to_days(requested) <= to_days(maximum) else maximum

    def get_bars(
        self,
        symbol: str,
        asset_class: str,
        tf_ibkr: str,
        tf_label: str,
        duration: str,
    ) -> Optional[pd.DataFrame]:
        """
        Fetch historical bars for one symbol + timeframe from IBKR.
        Cache-first, rate-limited, with reconnect on disconnection.
        """
        if DataStore.is_fresh(
            symbol, tf_label, max_age_hours=DataStore.intraday_max_age_hours(tf_label)
        ):
            cached = DataStore.load(symbol, tf_label)
            if cached is not None:
                return cached

        # TF permanently disabled for this session
        if tf_ibkr in self._tf_ibkr_disabled:
            return None  # yfinance fallback will handle it

        if self._circuit_open:
            elapsed = time.time() - self._circuit_open_at
            if elapsed < 300:
                log.debug(f"  Circuit open — skipping IBKR {symbol} {tf_label}")
                return None
            else:
                log.info("  Circuit reset")
                self._circuit_open = False
                self._consecutive_fails = 0
                self._circuit_open_count = 0

        if not self.ensure_connected():
            return None

        # Track IBKR attempt for TF-level success rate
        self._tf_ibkr_attempts += 1

        max_dur = self._MAX_DURATION.get(tf_ibkr, duration)
        effective = self._shorter_duration(duration, max_dur)

        contract = self._build_contract(symbol, asset_class)
        if contract is None:
            return None

        INTRADAY = {
            "1 min",
            "2 mins",
            "3 mins",
            "5 mins",
            "15 mins",
            "30 mins",
            "1 hour",
            "4 hours",
        }
        end_dt = (
            datetime.now(tz=timezone.utc).strftime("%Y%m%d %H:%M:%S UTC")
            if tf_ibkr in INTRADAY
            else ""
        )

        raw_bars = None
        for attempt in range(4):
            try:
                self._wait_rate_limit(tf_ibkr)
                # 15s for intraday (fail fast → yfinance), 30s for daily
                INTRADAY_SET = {
                    "1 min",
                    "2 mins",
                    "3 mins",
                    "5 mins",
                    "15 mins",
                    "30 mins",
                    "1 hour",
                    "4 hours",
                }
                self._ib.RequestTimeout = 15 if tf_ibkr in INTRADAY_SET else 30
                bars = self._ib.reqHistoricalData(
                    contract,
                    endDateTime=end_dt,
                    durationStr=effective,
                    barSizeSetting=tf_ibkr,
                    whatToShow=IBKRFeed._what_to_show(asset_class, tf_ibkr),
                    useRTH=False,
                    formatDate=1,
                    keepUpToDate=False,
                )
                if bars:
                    raw_bars = ibi.util.df(bars)
                    break
                else:
                    wait = 30 * (attempt + 1)
                    log.warning(
                        f"IBKR pacing {symbol} {tf_label} "
                        f"attempt {attempt+1}/4 — waiting {wait}s"
                    )
                    time.sleep(wait)
            except Exception as e:
                # Check for disconnection
                if not self._ib.isConnected():
                    log.warning(
                        f"IBKR disconnected during request — attempting reconnect"
                    )
                    if not self.reconnect():
                        return None
                    continue
                # Shorter waits for intraday — fast failure detection
                # feeds the rolling degraded-mode check in the sweep loop.
                # Intraday: (3, 5, 10s); daily: (5, 10, 20, 40s)
                INTRADAY_TFS = {
                    "1 min",
                    "2 mins",
                    "3 mins",
                    "5 mins",
                    "15 mins",
                    "30 mins",
                    "1 hour",
                    "4 hours",
                }
                if tf_ibkr in INTRADAY_TFS:
                    wait = [3, 5, 10][min(attempt, 2)]
                else:
                    wait = 2**attempt * 5
                log.warning(
                    f"IBKR request failed {symbol} {tf_label} "
                    f"attempt {attempt+1}: {e}. Retrying in {wait}s"
                )
                time.sleep(wait)

        # Fallback: ADJUSTED_LAST → TRADES for equity daily if needed
        if (
            asset_class == "equity"
            and tf_ibkr in ("1 day", "1W", "1M")
            and (raw_bars is None or raw_bars.empty or len(raw_bars) <= 1)
        ):
            log.debug(
                f"  {symbol} {tf_label}: ADJUSTED_LAST empty — retrying with TRADES"
            )
            try:
                self._wait_rate_limit(tf_ibkr)
                self._ib.RequestTimeout = (
                    15
                    if tf_ibkr
                    in {
                        "1 min",
                        "2 mins",
                        "3 mins",
                        "5 mins",
                        "15 mins",
                        "30 mins",
                        "1 hour",
                        "4 hours",
                    }
                    else 30
                )
                bars_retry = self._ib.reqHistoricalData(
                    contract,
                    endDateTime="",
                    durationStr=effective,
                    barSizeSetting=tf_ibkr,
                    whatToShow="TRADES",
                    useRTH=True,
                    formatDate=1,
                    keepUpToDate=False,
                )
                if bars_retry and len(bars_retry) > 1:
                    raw_bars = ibi.util.df(bars_retry)
            except Exception:
                pass

        if raw_bars is None or raw_bars.empty:
            self._consecutive_fails += 1
            # 3-strikes: if 3+ IBKR attempts in this TF with 0 successes, disable immediately
            if (
                self._tf_ibkr_attempts >= 3
                and self._tf_ibkr_successes == 0
                and tf_ibkr not in self._tf_ibkr_disabled
            ):
                self._tf_ibkr_disabled.add(tf_ibkr)
                log.warning(
                    f"3-strikes: IBKR disabled for {tf_ibkr} this session "
                    f"({self._tf_ibkr_attempts} attempts, 0 successes) — routing to yfinance"
                )
            if self._consecutive_fails >= 10 and not self._circuit_open:
                self._circuit_open = True
                self._circuit_open_at = time.time()
                self._circuit_open_count += 1
                log.warning(
                    f"Circuit OPEN (#{self._circuit_open_count}) after {self._consecutive_fails} failures"
                )
                if (
                    self._circuit_open_count >= 2
                    and tf_ibkr not in self._tf_ibkr_disabled
                ):
                    self._tf_ibkr_disabled.add(tf_ibkr)
                    log.warning(
                        f"IBKR disabled for {tf_ibkr} this session — routing to yfinance"
                    )
            if tf_label in YFinanceFeed._YF_INTRADAY_MAP:
                log.info(f"  {symbol} {tf_label}: IBKR failed → trying yfinance")
                yf_df = YFinanceFeed.get_intraday_fallback(
                    symbol, asset_class, tf_label
                )
                if yf_df is not None:
                    DataStore.append(symbol, tf_label, yf_df)
                    log.info(f"  ✓ yfinance {symbol} {tf_label} → {len(yf_df)} bars")
                    # Don't reset consecutive_fails — IBKR is still failing
                    # Only actual IBKR success (below) resets the circuit counter
                    return yf_df
                else:
                    log.warning(
                        f"  yfinance also returned None for {symbol} {tf_label}"
                    )
            log.warning(f"No data  {symbol} {tf_label} — both IBKR and yfinance failed")
            return None

        if len(raw_bars) == 1:
            what = IBKRFeed._what_to_show(asset_class, tf_ibkr)
            log.warning(
                f"Only 1 bar returned for {symbol} {tf_label} "
                f"(whatToShow={what}) — trying yfinance fallback"
            )
            if tf_label in YFinanceFeed._YF_INTRADAY_MAP:
                yf_df = YFinanceFeed.get_intraday_fallback(
                    symbol, asset_class, tf_label
                )
                if yf_df is not None:
                    DataStore.append(symbol, tf_label, yf_df)
                    log.info(
                        f"  ✓ yfinance (1-bar fallback) {symbol} {tf_label} → {len(yf_df)} bars"
                    )
                    return yf_df

        cleaned, report = DataCleaner.clean(
            raw_bars, symbol, asset_class, tf_label, tf_ibkr, source="ibkr"
        )
        if cleaned is not None:
            DataStore.append(symbol, tf_label, cleaned)
            log.info(
                f"Fetched  {symbol} {tf_label}  →  {len(cleaned)} bars  (dropped {report.bars_dropped})"
            )
            self._consecutive_fails = 0
            self._tf_ibkr_successes += 1
        else:
            log.warning(f"Dropped  {symbol} {tf_label}  →  {report.fail_reason}")

        return cleaned

    # Intraday timeframes fetched from IBKR for all asset classes
    # Fetched natively from IBKR — each has unique depth that cannot be
    # recovered by resampling from a finer timeframe:
    #   4h/8h = 10Y,  1h = 5Y,  30m = 2Y,  15m = 1Y,  5m = 6M,  1m = 42D
    # 2m and 3m are derived by resampling from 1m (same 42D depth, no loss).
    INTRADAY_TFS = [
        ("4 hours", "4h", "10 Y"),
        ("1 hour", "1h", "5 Y"),
        ("30 mins", "30m", "2 Y"),
        ("15 mins", "15m", "1 Y"),
        ("5 mins", "5m", "6 M"),
        ("1 min", "1m", "42 D"),
    ]

    # Derived from 1m by resampling — same 42D depth, no information lost
    RESAMPLED_FROM_1M = [
        ("2m", "2min"),
        ("3m", "3min"),
    ]

    def get_intraday(
        self,
        symbol: str,
        asset_class: str,
    ) -> Dict[str, Optional[pd.DataFrame]]:
        """
        Fetch intraday timeframes only for one asset.

        Used for equities where daily/weekly/monthly already downloaded
        via yfinance. Also used standalone for non-equity assets after
        their daily bars are confirmed.

        Returns dict keyed by tf_label with cleaned DataFrames.
        """
        result: Dict[str, Optional[pd.DataFrame]] = {}
        base_duration = Config.DATA.HISTORY_DEPTH.get(asset_class, "10 Y")

        self._intraday_count = 0
        log.debug(f"  {symbol}: pausing {self._intraday_delay}s before intraday block")
        time.sleep(self._intraday_delay)

        for tf_ibkr, tf_label, max_dur in IBKRFeed.INTRADAY_TFS:
            # Skip if already cached AND still fresh (not just present)
            if DataStore.is_fresh(
                symbol, tf_label, max_age_hours=DataStore.intraday_max_age_hours(tf_label)
            ):
                cached = DataStore.load(symbol, tf_label)
                if cached is not None:
                    result[tf_label] = cached
                    continue
            effective = self._shorter_duration(base_duration, max_dur)
            df = self.get_bars(symbol, asset_class, tf_ibkr, tf_label, effective)
            result[tf_label] = df
            if df is None:
                log.debug(f"  {symbol} {tf_label} failed — pausing 20s before next TF")
                time.sleep(20)

        return result

    def get_full_history(
        self,
        symbol: str,
        asset_class: str,
    ) -> Dict[str, Optional[pd.DataFrame]]:
        """
        Fetch all timeframes for one non-equity asset from IBKR.
        Daily + weekly/monthly derived from daily + all intraday.
        """
        result: Dict[str, Optional[pd.DataFrame]] = {}
        base_duration = Config.DATA.HISTORY_DEPTH.get(asset_class, "10 Y")

        # Daily first to validate asset
        daily_dur = self._shorter_duration(base_duration, self._MAX_DURATION["1 day"])
        df_1d = self.get_bars(symbol, asset_class, "1 day", "1D", daily_dur)
        result["1D"] = df_1d

        if df_1d is None:
            log.warning(f"  {symbol}: daily data unavailable — skipping all TFs")
            return result

        # Derive 7D and 1M from daily (no depth loss)
        result["7D"] = IBKRFeed._resample(df_1d, "W-FRI")
        result["1M"] = IBKRFeed._resample(df_1d, "1ME")

        # Fetch all intraday
        intraday = self.get_intraday(symbol, asset_class)
        result.update(intraday)

        return result

    @staticmethod
    def _resample(df: pd.DataFrame, rule: str) -> Optional[pd.DataFrame]:
        try:
            agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
            if "volume" in df.columns:
                agg["volume"] = "sum"
            resampled = df.resample(rule).agg(agg).dropna(subset=["open", "close"])
            return resampled if len(resampled) >= 2 else None
        except Exception as e:
            log.debug(f"Resample failed ({rule}): {e}")
            return None


# =============================================================================
# CLASS 5 — CBOEFeed
# =============================================================================


class CBOEFeed:
    """Fetches options IV surface data from CBOE's public delayed quotes API."""

    _SESSION_CACHE: Dict[str, Optional[pd.DataFrame]] = {}

    @staticmethod
    def get_surface(symbol: str) -> Optional[pd.DataFrame]:
        if symbol in CBOEFeed._SESSION_CACHE:
            return CBOEFeed._SESSION_CACHE[symbol]
        cached = DataStore.load(f"cboe_{symbol}", "surface")
        if cached is not None:
            CBOEFeed._SESSION_CACHE[symbol] = cached
            return cached
        surface = CBOEFeed._fetch(symbol)
        CBOEFeed._SESSION_CACHE[symbol] = surface
        if surface is not None:
            DataStore.save(f"cboe_{symbol}", "surface", surface)
            log.info(f"CBOE surface fetched  {symbol}  →  {len(surface)} strikes")
        return surface

    @staticmethod
    def _fetch(symbol: str) -> Optional[pd.DataFrame]:
        url = f"{Config.DATA.CBOE_BASE_URL}{symbol}.json"
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code != 200:
                return None
            payload = resp.json()
            options_data = payload.get("data", {}).get("options") or payload.get(
                "options"
            )
            if not options_data:
                return None
            spot = (
                payload.get("data", {}).get("current_price")
                or payload.get("current_price")
                or 0
            )
            records = []
            for opt in options_data:
                code = opt.get("option", "")
                iv = opt.get("iv", None)
                if not code or iv is None:
                    continue
                parsed = CBOEFeed._parse_option_code(code)
                if parsed is None:
                    continue
                expiry_date, opt_type, strike = parsed
                dte = (expiry_date - datetime.now(tz=timezone.utc).date()).days
                moneyness = (strike / spot) if spot > 0 else np.nan
                records.append(
                    {
                        "symbol": symbol,
                        "strike": strike,
                        "expiry": expiry_date,
                        "dte": dte,
                        "opt_type": opt_type,
                        "iv": float(iv),
                        "moneyness": moneyness,
                    }
                )
            if not records:
                return None
            df = pd.DataFrame(records)
            calls = df[df.opt_type == "C"][
                ["strike", "expiry", "dte", "moneyness", "iv"]
            ].rename(columns={"iv": "call_iv"})
            puts = df[df.opt_type == "P"][
                ["strike", "expiry", "dte", "moneyness", "iv"]
            ].rename(columns={"iv": "put_iv"})
            merged = pd.merge(
                calls, puts, on=["strike", "expiry", "dte", "moneyness"], how="outer"
            )
            merged["mid_iv"] = merged[["call_iv", "put_iv"]].mean(axis=1)
            mn_lo, mn_hi = Config.OPTIONS.IV_SURFACE_MONEYNESS_RANGE
            dte_lo, dte_hi = Config.OPTIONS.IV_SURFACE_EXPIRY_RANGE
            merged = merged[
                merged.moneyness.between(mn_lo, mn_hi)
                & merged.dte.between(dte_lo, dte_hi)
            ]
            return merged if not merged.empty else None
        except Exception as e:
            log.debug(f"CBOE fetch error for {symbol}: {e}")
            return None

    @staticmethod
    def _parse_option_code(code: str) -> Optional[Tuple]:
        try:
            match = re.search(r"(\d{6})(C|P)(\d{8})", code)
            if not match:
                return None
            expiry = datetime.strptime(match.group(1), "%y%m%d").date()
            opt_type = match.group(2)
            strike = int(match.group(3)) / 1000.0
            return expiry, opt_type, strike
        except Exception:
            return None


# =============================================================================
# CLASS 6 — UniverseBuilder
# =============================================================================


class RunSummary:
    """
    Accumulates key metrics during a data.py run and writes a compact
    structured summary at completion. Upload latest_run_data.log directly
    to an LLM for diagnosis without needing to summarize first.
    """

    _LOG_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "latest_run_data.log"
    )

    def __init__(self):
        self.start_time = time.time()
        self.config_hash = ""
        self.n_universe = 0
        self.n_resumed = 0
        self.n_excluded = 0
        self.contaminated_cleaned = 0
        self.phase1: Dict[str, Any] = {}
        self.tfs: Dict[str, Dict] = {}
        self.ibkr_disconnects = 0
        self.ibkr_session_killed = False
        self.errors: List[str] = []
        self.warnings: Dict[str, int] = {}

    def record_tf(self, tf: str, **kwargs) -> None:
        self.tfs.setdefault(tf, {}).update(kwargs)

    def error(self, msg: str) -> None:
        key = msg[:100]
        if key not in self.errors:
            self.errors.append(key)

    def warn(self, category: str) -> None:
        self.warnings[category] = self.warnings.get(category, 0) + 1

    def write(self) -> None:
        elapsed = (time.time() - self.start_time) / 60
        lines = [
            "=== CAMARF data.py ===",
            f"date:        {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
            f"runtime_min: {elapsed:.1f}",
            f"config_hash: {self.config_hash}",
            "",
            "=== universe ===",
            f"candidates:  {self.n_universe}",
            f"resumed:     {self.n_resumed}",
            f"excluded:    {self.n_excluded}",
            f"cache_contamination_cleared: {self.contaminated_cleaned}",
            "",
            "=== phase1_daily ===",
        ]
        for k, v in self.phase1.items():
            lines.append(f"{k}: {v}")

        lines += ["", "=== intraday_tfs ==="]
        if self.tfs:
            # Dynamic columns: union of all keys actually recorded across TFs,
            # so derivation diagnostics (skip_fresh, no_source, resample_fail,
            # freq_invalid) show up alongside fetch diagnostics (yf_ok, yf_fail)
            # without needing a fixed schema.
            all_keys = []
            for s in self.tfs.values():
                for k in s.keys():
                    if k not in all_keys:
                        all_keys.append(k)
            header = "tf    | " + " | ".join(f"{k:<13}" for k in all_keys)
            lines.append(header)
            for tf, s in self.tfs.items():
                row = f"{tf:<6}| " + " | ".join(f"{s.get(k,0):<13}" for k in all_keys)
                lines.append(row)

        lines += [
            "",
            "=== ibkr ===",
            f"disconnects:    {self.ibkr_disconnects}",
            f"session_killed: {self.ibkr_session_killed}",
        ]

        if self.warnings:
            lines += ["", "=== warnings (top 10) ==="]
            for cat, n in sorted(self.warnings.items(), key=lambda x: -x[1])[:10]:
                lines.append(f"  {n:>4}x  {cat}")

        if self.errors:
            lines += ["", "=== errors ==="]
            for e in self.errors:
                lines.append(f"  {e}")

        lines += ["", "=== end ==="]
        try:
            with open(self._LOG_PATH, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            log.info(f"Run summary → {self._LOG_PATH}")
        except Exception as e:
            log.debug(f"RunSummary write failed: {e}")


class UniverseBuilder:
    """
    Constructs the full CAMARF asset universe and fetches all historical data.

    Equity daily/weekly/monthly/intraday → YFinanceFeed (bulk, fast)
    Futures/forex/crypto/commodities → IBKRFeed (all timeframes)
    Equity 3m bars → IBKRFeed (not available from yfinance)
    """

    def __init__(self):
        self._ibkr = IBKRFeed()

    # Pre-seeded known-unavailable tickers (confirmed across multiple runs)
    _KNOWN_UNAVAILABLE: set = {
        "VLTO",  # Veralto — spun off Sep 2023, no intraday data from any source
        "BNY",  # BNY Mellon ticker variant — use "BK" instead
        "FDXF",  # No daily data from yfinance
    }
    _PERSISTENT_FAIL_THRESHOLD: int = 3  # auto-exclude after N full-run failures
    _EXCLUSION_CACHE: str = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "output",
        "cache",
        "excluded_assets.json",
    )

    @staticmethod
    def _run_cache_migration() -> None:
        """
        One-time migration from old TF filenames (e.g. SYMBOL_1m.parquet)
        to safe names (SYMBOL_1min.parquet). On Windows, "1m" and "1M" are
        case-insensitively the same file — causing monthly data to overwrite
        1-minute data. After migration a flag file is written; the migration
        does not run again on subsequent builds.
        """
        cache_dir = Config.DATA.CACHE_DIR
        # v3 flag: also deletes corrupted 2m/3m files derived from bad 1m cache
        flag = os.path.join(cache_dir, ".cache_v3_migrated")
        if not os.path.exists(cache_dir) or os.path.exists(flag):
            return
        log.info("One-time cache migration v3: safe filenames + 2m/3m cleanup...")
        DataStore.migrate_cache()
        try:
            open(flag, "w").close()
        except OSError:
            pass

    @staticmethod
    def _clean_contaminated_cache() -> None:
        """
        Scan the cache directory and delete files whose actual bar frequency
        doesn't match the expected frequency for their TF suffix.

        This catches the yfinance silent-fallback bug where daily bars are
        written to a 1h or 4h cache file. Without this cleanup, is_fresh()
        returns True on the contaminated file and data.py never re-fetches.

        Only runs the scan once per session (flag file prevents repeated work).
        Deletes contaminated files so they get re-fetched on this run.
        """
        # No flag file — scan runs on every data.py startup.
        # The scan reads only the first 10 rows of each parquet file to check
        # median gap frequency. For 1500 files this takes ~3-5 seconds total.
        # A persistent flag would skip the scan when contaminated files are
        # older than the flag (the common case), defeating the purpose.

        cleaned = 0
        # Map safe TF name → (expected_gap_seconds, tolerance_multiplier)
        checks = {
            safe: (gap, 3)
            for tf, gap in DataStore._EXPECTED_GAP_SECONDS.items()
            if (safe := DataStore._TF_SAFE.get(tf, tf)) and gap
        }

        try:
            for fname in os.listdir(Config.DATA.CACHE_DIR):
                if not fname.endswith(".parquet"):
                    continue
                # Identify which TF this file belongs to
                matched_safe = None
                for safe_tf in checks:
                    if fname.endswith(f"_{safe_tf}.parquet"):
                        matched_safe = safe_tf
                        break
                if matched_safe is None:
                    continue

                expected_gap, tol = checks[matched_safe]
                fpath = os.path.join(Config.DATA.CACHE_DIR, fname)
                try:
                    df = pd.read_parquet(fpath, columns=["close"])
                    if len(df) < 10:
                        continue
                    idx = pd.to_datetime(df.index)
                    gaps = idx.to_series().diff().dt.total_seconds().dropna()
                    # Exclude structural overnight/weekend gaps (>8h) before
                    # computing the median. Fixed 2026-06-21: a correctly
                    # session-aligned 4h file has exactly 2 bars/day, so HALF
                    # its gaps are the legitimate ~20h overnight break —
                    # including them pushed the median right up near the
                    # contamination threshold, so this was silently deleting
                    # good 4h files on every single build() call (data.py
                    # AND analysis.py both call this unconditionally at
                    # startup), confirmed via a live run: 1500+ valid 4h
                    # files written by data.py, only 7 left by the time
                    # analysis.py read the cache moments later.
                    intraday_gaps = gaps[gaps <= 8 * 3600]
                    med = float(
                        (intraday_gaps if len(intraday_gaps) >= 3 else gaps).median()
                    )
                    if med > expected_gap * tol:
                        os.remove(fpath)
                        cleaned += 1
                        log.debug(
                            f"  Removed contaminated cache: {fname} "
                            f"(expected ~{expected_gap}s, got {med:.0f}s)"
                        )
                except Exception:
                    pass  # unreadable or corrupt file — leave it

            if cleaned:
                log.info(
                    f"Cache scan: removed {cleaned} contaminated files "
                    f"(wrong frequency — will be re-fetched this run)"
                )
                # Contamination count logged above via log.info().
                # (RunSummary.contaminated_cleaned updated from build() scope)
            else:
                log.debug("Cache scan: no contaminated files found")

            # Scan complete — no flag file written (scan always runs)
        except Exception as e:
            log.debug(f"Contamination scan failed: {e}")

    @staticmethod
    def load_exclusions() -> set:
        """Load persistent exclusion list from disk, merged with hardcoded."""
        excluded = set(UniverseBuilder._KNOWN_UNAVAILABLE)
        try:
            if os.path.exists(UniverseBuilder._EXCLUSION_CACHE):
                with open(UniverseBuilder._EXCLUSION_CACHE) as f:
                    data = json.load(f)
                # File format: {symbol: {reason, added}} or [symbol, ...]
                if isinstance(data, dict):
                    excluded |= set(data.keys())
                elif isinstance(data, list):
                    excluded |= set(data)
        except Exception:
            pass
        return excluded

    @staticmethod
    def add_exclusion(symbol: str, reason: str = "") -> None:
        """Persist a symbol to the exclusion list so future runs skip it."""
        try:
            Config.ensure_dirs()
            existing = {}
            if os.path.exists(UniverseBuilder._EXCLUSION_CACHE):
                with open(UniverseBuilder._EXCLUSION_CACHE) as f:
                    existing = json.load(f)
            if not isinstance(existing, dict):
                existing = {s: {"reason": "legacy"} for s in existing}
            existing[symbol] = {
                "reason": reason or "persistent failure — both IBKR and yfinance",
                "added_at": datetime.now().isoformat(timespec="seconds"),
            }
            with open(UniverseBuilder._EXCLUSION_CACHE, "w") as f:
                json.dump(existing, f, indent=2)
            log.info(f"Exclusion list: added {symbol} ({reason})")
        except Exception as e:
            log.debug(f"Exclusion persist failed for {symbol}: {e}")

    def build(
        self,
        connect: bool = False,  # yfinance-only by default; True = IBKR mode
        reset_progress: bool = False,
        fetch: bool = True,  # False = read-only — never touch IBKR or yfinance
    ) -> UniverseResult:
        """
        Full pipeline: build universe, fetch data, validate, return result.
        Crash-safe via ProgressLogger. Config-hash-aware cache invalidation.

        fetch=False (used by analysis.py): `connect` alone does NOT make this
        read-only — connect only chooses IBKR vs yfinance as the intraday
        *source*, both branches still fetch. Fixed 2026-06-21: analysis.py
        called build(connect=False) believing that was sufficient to never
        touch yfinance (per CLAUDE.md's "analysis.py must never fetch" rule),
        but connect=False actually ran the full Phase 2A yfinance sweep —
        confirmed directly via a live run. fetch=False is the real "use
        cache as-is, fetch nothing" switch.
        """
        _summary = RunSummary()  # tracks metrics; written to latest_run_data.log at end
        Config.ensure_dirs()
        UniverseBuilder._run_cache_migration()  # one-time safe filename migration
        UniverseBuilder._clean_contaminated_cache()  # delete wrong-freq cache files

        if reset_progress:
            ProgressLogger.reset()

        progress = ProgressLogger.load()
        current_hash = ProgressLogger.compute_config_hash()
        _summary.config_hash = current_hash[:16]
        n_done = sum(
            1
            for sym in progress["completed"]
            if ProgressLogger.is_complete(progress, sym)
        )
        if n_done > 0:
            log.info(
                f"Resuming — {n_done} assets already complete (config hash {current_hash})"
            )
        _summary.n_resumed = n_done

        log.info("Building asset universe...")
        raw_assets_all = self._build_raw_list()
        exclusions = UniverseBuilder.load_exclusions()
        raw_assets = [(s, c) for s, c in raw_assets_all if s not in exclusions]
        n_skipped = len(raw_assets_all) - len(raw_assets)
        if n_skipped:
            skipped_names = sorted(exclusions & {s for s, _ in raw_assets_all})
            log.info(f"Exclusion list: skipping {n_skipped} assets {skipped_names}")
        log.info(f"Universe candidates: {len(raw_assets)} assets")
        _summary.n_universe = len(raw_assets)

        # Loud, impossible-to-miss guard: the full S&P 1500 + crypto/forex/
        # commodities/futures/ETF universe should always be 1400+. A count
        # well below that means one or more constituent scrapers silently
        # failed (confirmed incident: 2026-06-19, universe silently shrank
        # to 86 assets after Wikipedia/iShares both failed in the same run
        # and nothing flagged it). This is impossible to miss in the log
        # or the run summary, even if scrolled past in a terminal.
        if len(raw_assets) < 1000:
            log.error(
                f"\n{'!'*70}\n"
                f"!! UNIVERSE SIZE ABNORMALLY LOW: {len(raw_assets)} assets "
                f"(expected 1400+) !!\n"
                f"!! One or more constituent scrapers (S&P 500/400/600) "
                f"likely failed.\n"
                f"!! Check the log above for 'fetch failed' or 'tickers from "
                f"Wikipedia' lines.\n"
                f"!! Results from this run should NOT be trusted for "
                f"analysis until resolved.\n"
                f"{'!'*70}"
            )
            _summary.error(
                f"UNIVERSE SIZE ABNORMAL: {len(raw_assets)} assets (expected 1400+)"
            )

        all_data: Dict[str, pd.DataFrame] = {}
        all_reports: List[QualityReport] = []
        passed: List[Tuple[str, str]] = []
        excluded: List[Tuple[str, str, str]] = []

        # ---------------------------------------------------------------
        # Phase 1: yfinance bulk download — daily/weekly/monthly
        # Equities + crypto. Fast bulk download, no rate limits.
        # Crypto uses "BTC-USD" yfinance format.
        # ---------------------------------------------------------------
        def to_yf_ticker(symbol: str, asset_class: str) -> str:
            if asset_class == "crypto":
                return f"{symbol}-USD"
            elif asset_class == "forex":
                # yfinance uses EURUSD=X format
                # Our config stores "EUR.USD" — remove dot, add =X
                return symbol.replace(".", "") + "=X"
            return symbol.replace(" ", "-")  # BRK B → BRK-B

        # yfinance handles: equities, crypto (BTC-USD), forex (EURUSD=X)
        # IBKR handles: commodities, futures, and all intraday
        yf_assets = [
            (s, cls)
            for s, cls in raw_assets
            if cls in ("equity", "crypto", "forex", "etf")
        ]
        log.info(
            f"Phase 1 (yfinance daily): "
            f"{sum(1 for _,c in yf_assets if c=='equity')} equities + "
            f"{sum(1 for _,c in yf_assets if c=='crypto')} crypto + "
            f"{sum(1 for _,c in yf_assets if c=='forex')} forex + "
            f"{sum(1 for _,c in yf_assets if c=='etf')} ETFs"
        )

        yf_daily_done = set()  # track which symbols have daily data confirmed

        # Separate into: completely missing vs. stale (has cache but needs update)
        uncached_yf = [
            (s, cls) for s, cls in yf_assets if not DataStore.is_fresh(s, "1D")
        ]
        stale_yf = [
            (s, cls)
            for s, cls in yf_assets
            if DataStore.is_fresh(s, "1D") and DataStore.needs_refresh(s, "1D")
        ]

        if not fetch:
            if uncached_yf or stale_yf:
                log.info(
                    f"  Read-only mode (fetch=False): skipping yfinance fetch "
                    f"for {len(uncached_yf)} uncached + {len(stale_yf)} stale "
                    f"daily assets — using cache as-is"
                )
            uncached_yf = []
            stale_yf = []

        if uncached_yf or stale_yf:
            # Full fetch for uncached; incremental (last 30 days) for stale
            if uncached_yf:
                log.info(
                    f"  Fetching fresh daily data for {len(uncached_yf)} assets..."
                )
                ibkr_list = [s for s, cls in uncached_yf]
                yf_list = [to_yf_ticker(s, cls) for s, cls in uncached_yf]
                yf_results = YFinanceFeed.get_equity_history(
                    ibkr_list,
                    chunk_size=Config.DATA.YF_CHUNK_SIZE,
                    yf_tickers=yf_list,
                )
                for symbol, asset_class in uncached_yf:
                    sym_data = yf_results.get(symbol, {})
                    if sym_data.get("1D") is not None:
                        yf_daily_done.add(symbol)
                        for tf, df in sym_data.items():
                            if df is not None:
                                all_data[f"{symbol}_{tf}"] = df
                    else:
                        excluded.append((symbol, asset_class, "no_daily_data_yfinance"))

            if stale_yf:
                log.info(
                    f"  Incremental refresh for {len(stale_yf)} stale daily assets..."
                )
                ibkr_list = [s for s, cls in stale_yf]
                yf_list = [to_yf_ticker(s, cls) for s, cls in stale_yf]
                # Fetch last 30 days only — enough to catch any missed sessions
                fresh_results = YFinanceFeed.get_equity_history(
                    ibkr_list,
                    chunk_size=Config.DATA.YF_CHUNK_SIZE,
                    yf_tickers=yf_list,
                    period="1mo",  # last 30 calendar days
                )
                n_refreshed = 0
                for symbol, asset_class in stale_yf:
                    sym_data = fresh_results.get(symbol, {})
                    new_df = sym_data.get("1D") if sym_data else None
                    if new_df is not None and not new_df.empty:
                        combined = DataStore.append(symbol, "1D", new_df)
                        if combined is not None:
                            all_data[f"{symbol}_1D"] = combined
                            yf_daily_done.add(symbol)
                            n_refreshed += 1
                    else:
                        # Fall back to existing cache
                        cached = DataStore.load(symbol, "1D")
                        if cached is not None:
                            all_data[f"{symbol}_1D"] = cached
                            yf_daily_done.add(symbol)
                log.info(
                    f"  Incremental refresh: {n_refreshed}/{len(stale_yf)} updated"
                )
        else:
            log.info("  All daily data cached and current — skipping yfinance download")

        # Mark all yf_assets with confirmed daily as having daily complete
        for symbol, asset_class in yf_assets:
            if DataStore.is_fresh(symbol, "1D"):
                yf_daily_done.add(symbol)
                cached = DataStore.load(symbol, "1D")
                if cached is not None:
                    all_data[f"{symbol}_1D"] = cached

        # ---------------------------------------------------------------
        # Phase 2: IBKR intraday for equities + all TFs for non-equities
        # Runs after Phase 1 completes (IBKR rate limits prevent full concurrency)
        # Equities with confirmed daily get intraday from IBKR
        # ---------------------------------------------------------------
        # IBKR Phase 2: commodities and futures only for full history
        # Forex daily comes from yfinance; forex intraday still from IBKR
        non_equity = [
            (s, cls) for s, cls in raw_assets if cls in ("commodity", "futures")
        ]

        # All equities with confirmed daily data need IBKR intraday.
        # This includes equities cached in previous sessions (not just this run).
        # Skip only if all intraday TFs are already fully cached.
        def _intraday_complete(symbol: str) -> bool:
            """True only if every intraday TF (native + derived) is cached and fresh.

            Found 2026-06-23: this gate was missed when intraday_max_age_hours()
            was threaded into every other native-intraday is_fresh() call site
            overnight. Left unguarded, it always returned True for any symbol
            cached even once, emptying equity_needing_intraday/forex_needing_intraday
            and silently skipping the entire Phase 2A yfinance sweep below —
            confirmed via a real run (9.7min, blank intraday_tfs section).
            """
            native_complete = all(
                DataStore.is_fresh(
                    symbol, tf_label,
                    max_age_hours=DataStore.intraday_max_age_hours(tf_label),
                )
                for _, tf_label, _ in IBKRFeed.INTRADAY_TFS
            )
            derived_complete = all(
                DataStore.is_fresh(
                    symbol, tf_label,
                    max_age_hours=DataStore.intraday_max_age_hours(tf_label),
                )
                for tf_label, _ in IBKRFeed.RESAMPLED_FROM_1M
            )
            return native_complete and derived_complete

        equity_needing_intraday = [
            (s, "equity")
            for s, cls in raw_assets
            if cls == "equity"
            and DataStore.is_fresh(s, "1D")
            and not _intraday_complete(s)
        ]

        # Forex intraday also from IBKR (yfinance forex intraday is too shallow)
        forex_needing_intraday = [
            (s, "forex")
            for s, cls in raw_assets
            if cls == "forex"
            and DataStore.is_fresh(s, "1D")
            and not _intraday_complete(s)
        ]

        log.info(
            f"  {len(equity_needing_intraday)} equities + "
            f"{len(forex_needing_intraday)} forex need IBKR intraday"
        )

        ibkr_work = equity_needing_intraday + forex_needing_intraday + non_equity
        if not fetch and ibkr_work:
            log.info(
                f"  Read-only mode (fetch=False): {len(ibkr_work)} assets need "
                f"intraday data but fetching is disabled — using cache as-is "
                f"(expected for analysis.py; run data.py to backfill)"
            )
            ibkr_work = []

        if ibkr_work:
            if not connect:
                log.info("  Phase 2A: yfinance intraday sweep (primary pipeline)")
                # yfinance intraday depth limits:
                #   1h:  730 days (deepest intraday available)
                #   5m/15m/30m/2m: 60 days
                #   1m/3m: 7 days (Yahoo hard limit)
                # 4h: no native yfinance 4h — derived from 1h via resample.
                # All TFs fetched regardless of depth. IBKR (data_ibkr.py)
                # deepens confirmed pairs to 10 years after analysis.py runs.
                # Full TF list — ordered longest-to-shortest depth so the
                # most analytically valuable data is prioritised if a run is
                # interrupted. 1m/2m/3m are last: short windows (7-60 days)
                # but still real signal for intraday pair screening.
                _YF_INTRADAY_TFS = ["1h", "30m", "15m", "5m", "2m", "1m", "3m"]
                _phase2a_fail_registry: Dict[str, List[Tuple[str, str]]] = {}
                _all_intraday_assets = [
                    (s, cls)
                    for s, cls in raw_assets
                    if cls in ("equity", "etf", "crypto")
                ]
                for _tf in _YF_INTRADAY_TFS:
                    _cutoff = compute_canonical_cutoff(_tf)
                    _needs = [
                        (s, cls)
                        for s, cls in _all_intraday_assets
                        # Found overnight (2026-06-23): was a bare exists
                        # check with no max_age_hours — once a symbol/TF was
                        # cached even once, it was skipped on every future
                        # run forever, regardless of staleness. This is the
                        # primary fetch loop the scheduled daily data.py run
                        # depends on to actually accumulate intraday history.
                        if not DataStore.is_fresh(
                            s, _tf, max_age_hours=DataStore.intraday_max_age_hours(_tf)
                        )
                    ]
                    if not _needs:
                        log.info(f"    [{_tf}] all assets current — skip")
                        _summary.record_tf(
                            _tf,
                            yf_ok=0,
                            yf_fail=0,
                            saved=0,
                            skipped_fresh=len(_all_intraday_assets),
                        )
                        continue
                    log.info(f"    [{_tf}] {len(_needs)} assets to fetch")
                    _saved = 0
                    _fail_fetch = 0  # get_intraday_fallback returned None/empty
                    _fail_snap = 0  # snap_timestamps produced empty
                    _fail_cutoff = 0  # truncate_to_cutoff produced empty
                    _first_fail = None

                    # Light per-request delay for high-frequency intervals —
                    # politeness toward the API, not a workaround for a
                    # diagnosed problem. (Root cause of the earlier 1m/2m
                    # 100% failure was a request-construction bug — see
                    # get_intraday_fallback — not a Yahoo-side block. A user
                    # test script using plain yf.Ticker().history(period=...)
                    # succeeded immediately for 1m with zero failures,
                    # confirming there was never a session-level rate limit.)
                    # Small universal delay across ALL intraday TFs, not just
                    # 1m/2m — the cookie/crumb-renegotiation throttling that
                    # caused 100% failure was observed on 1h too (87/87
                    # failed), so this isn't a high-frequency-only problem.
                    # The shared session (above) is the primary fix; this
                    # delay is additional insurance against burst-rate
                    # triggers in Yahoo's anti-bot detection.
                    _inter_request_delay = 0.15
                    _checkpoint_done = False

                    for _idx, (_sym, _cls) in enumerate(_needs):
                        if _idx > 0 and _idx % 200 == 0:
                            log.info(
                                f"    [{_tf}] {_idx}/{len(_needs)} "
                                f"({_saved} saved | "
                                f"fetch_fail={_fail_fetch} snap_fail={_fail_snap} "
                                f"cutoff_fail={_fail_cutoff})"
                            )

                        # Sanity checkpoint at idx=50: if still failing at a
                        # high rate after the get_intraday_fallback fix, this
                        # would indicate a genuinely new problem (not the old
                        # request-construction bug) — surfaced clearly rather
                        # than silently burning through the rest of the list.
                        if not _checkpoint_done and _idx == 50:
                            _checkpoint_done = True
                            _fail_rate = _fail_fetch / max(_idx, 1)
                            if _fail_rate > 0.85:
                                log.warning(
                                    f"    [{_tf}] {_fail_fetch}/{_idx} failed "
                                    f"({_fail_rate:.0%}) early on — if this "
                                    f"persists, check the WARNING-level "
                                    f"yfinance exception logged above for the "
                                    f"actual error (not assumed to be a rate "
                                    f"limit; could be network or API change)."
                                )

                        if _inter_request_delay:
                            time.sleep(_inter_request_delay)

                        _df = YFinanceFeed.get_intraday_fallback(_sym, _cls, _tf)
                        if _df is None or _df.empty:
                            _fail_fetch += 1
                            if _first_fail is None:
                                _first_fail = f"fetch:{_sym}"
                            _phase2a_fail_registry.setdefault(_tf, []).append(
                                (_sym, _cls)
                            )
                            continue
                        _df2 = snap_timestamps(_df, _tf, "yfinance")
                        if _df2 is None or _df2.empty:
                            _fail_snap += 1
                            if _first_fail is None:
                                _first_fail = (
                                    f"snap:{_sym} "
                                    f"(input {len(_df)} rows, "
                                    f"tz={getattr(_df.index, 'tz', None)}, "
                                    f"first={_df.index[0] if len(_df) else 'empty'})"
                                )
                            continue
                        _df3 = truncate_to_cutoff(_df2, _cutoff)
                        if _df3 is None or _df3.empty:
                            _fail_cutoff += 1
                            if _first_fail is None:
                                _first_fail = (
                                    f"cutoff:{_sym} "
                                    f"(cutoff={_cutoff}, "
                                    f"data_end={_df2.index[-1] if len(_df2) else 'empty'})"
                                )
                            continue
                        DataStore.append(_sym, _tf, _df3)
                        all_data[f"{_sym}_{_tf}"] = _df3
                        _saved += 1
                    log.info(
                        f"    [{_tf}] complete: {_saved}/{len(_needs)} saved | "
                        f"fail_fetch={_fail_fetch} fail_snap={_fail_snap} "
                        f"fail_cutoff={_fail_cutoff}"
                    )
                    if _first_fail:
                        log.warning(f"    [{_tf}] first failure: {_first_fail}")
                    _summary.record_tf(
                        _tf,
                        saved=_saved,
                        fail_fetch=_fail_fetch,
                        fail_snap=_fail_snap,
                        fail_cutoff=_fail_cutoff,
                    )

                # ── 4h derived from 1h supplement ──────────────────────────
                # yfinance has no native 4h interval; derived via OHLCV resample.
                # Failure reasons tracked explicitly (no more silent swallowing) —
                # the previous version's bare `except: pass` made a systemic
                # resample failure indistinguishable from normal skips.
                _4h_no_1h_data = 0
                _4h_resample_err = 0
                _4h_freq_invalid = 0
                _4h_saved = 0
                _4h_first_error = None

                # No is_fresh() skip here, deliberately: 1h now accumulates
                # (DataStore.append, not save), so 4h must be re-derived from
                # the FULL accumulated 1h every run for its own depth to grow
                # — skipping derivation once 4h existed would silently freeze
                # 4h's depth at whatever it was on the first run forever.
                # append()'s dedup makes re-deriving from an unchanged 1h
                # source a harmless no-op, not wasted work worth guarding.
                for _sym, _cls in _all_intraday_assets:
                    _df1h = all_data.get(f"{_sym}_1h")
                    if _df1h is None:
                        _df1h = DataStore.load(_sym, "1h")
                    if _df1h is None or _df1h.empty:
                        _4h_no_1h_data += 1
                        continue

                    try:
                        # Ensure clean DatetimeIndex before resampling —
                        # duplicate or unsorted timestamps silently corrupt
                        # resample() output without raising an exception.
                        _src = _df1h[~_df1h.index.duplicated(keep="last")].sort_index()
                        # CRITICAL: pandas resample("4h") bins to CLOCK-aligned
                        # boundaries (00:00, 04:00, 08:00, 12:00...) by default,
                        # NOT to market open. A 9:30-16:00 session only produces
                        # ~2 non-empty clock-aligned buckets/day, creating an
                        # alternating ~4h / ~20h gap pattern where the ~20h
                        # overnight gap dominates the median (confirmed via
                        # diagnostic: src_gap=3600s correct, derived gap=72000s
                        # = exactly the overnight-bucket-to-overnight-bucket
                        # span under clock alignment). Fix: align bins to
                        # market open (9:30) via origin/offset instead of
                        # midnight, so each session cleanly produces bins
                        # starting at 9:30 and 13:30 — matching how the data
                        # actually trades.
                        _df4h = (
                            _src.resample(
                                "4h",
                                closed="left",
                                label="left",
                                origin="start_day",
                                offset="9h30min",
                            )
                            .agg(
                                {
                                    "open": "first",
                                    "high": "max",
                                    "low": "min",
                                    "close": "last",
                                    "volume": "sum",
                                }
                            )
                            .dropna(subset=["close"])
                        )
                    except Exception as e:
                        _4h_resample_err += 1
                        if _4h_first_error is None:
                            _4h_first_error = f"{_sym}: {type(e).__name__}: {e}"
                        continue

                    if _df4h.empty:
                        _4h_resample_err += 1
                        continue

                    # Validate derived frequency before saving. Even with
                    # correct session-aligned bins, the overnight gap between
                    # a session's last bin and the next session's first bin
                    # (~20h) is LEGITIMATE — with only ~2 bins/day, it's not
                    # a rare outlier the way it is for 1h (6 bins/day), so it
                    # must be excluded before computing the validation median.
                    # Filter to intra-day gaps only (< 8h) before checking.
                    _all_gaps = (
                        _df4h.index.to_series().diff().dt.total_seconds().dropna()
                    )
                    _intraday_gaps = _all_gaps[_all_gaps < 8 * 3600]
                    _gap = (
                        float(_intraday_gaps.median())
                        if len(_intraday_gaps) > 3
                        else 14400.0
                    )
                    if _gap > 14400 * 3:
                        _4h_freq_invalid += 1
                        if _4h_first_error is None:
                            # Diagnose the SOURCE data directly — was it freshly
                            # fetched this run (all_data) or loaded from disk?
                            # And what's the source's own bar-gap, independent
                            # of the resample step, to isolate where the
                            # corruption actually originates.
                            _src_origin = (
                                "all_data(this-run)"
                                if all_data.get(f"{_sym}_1h") is not None
                                else "disk(DataStore.load)"
                            )
                            _src_gap = (
                                float(
                                    _src.index.to_series()
                                    .diff()
                                    .dt.total_seconds()
                                    .dropna()
                                    .median()
                                )
                                if len(_src) > 5
                                else float("nan")
                            )
                            _4h_first_error = (
                                f"{_sym}: derived 4h gap={_gap:.0f}s (expected ~14400s). "
                                f"source={_src_origin}, src_rows={len(_src)}, "
                                f"src_gap={_src_gap:.0f}s, "
                                f"src_range={_src.index.min()}→{_src.index.max()}"
                            )
                        continue

                    DataStore.append(_sym, "4h", _df4h)
                    all_data[f"{_sym}_4h"] = _df4h
                    _4h_saved += 1

                log.info(
                    f"    [4h] derived: {_4h_saved} saved | "
                    f"{_4h_no_1h_data} no 1h source | "
                    f"{_4h_resample_err} resample failed | "
                    f"{_4h_freq_invalid} wrong frequency after resample"
                )
                if _4h_first_error:
                    log.warning(f"    [4h] first failure detail: {_4h_first_error}")
                    _summary.error(f"4h derivation: {_4h_first_error}")
                _summary.record_tf(
                    "4h",
                    saved=_4h_saved,
                    no_source=_4h_no_1h_data,
                    resample_fail=_4h_resample_err,
                    freq_invalid=_4h_freq_invalid,
                )

                log.info(
                    "  Phase 2A complete. "
                    "Run data_ibkr.py for deep IBKR history on confirmed pairs."
                )
            if connect:
                success = self._ibkr.connect()
                if not success:
                    log.error(
                        "IBKR connection failed — intraday and non-equity assets skipped"
                    )
                    for s, cls in ibkr_work:
                        if cls != "equity":
                            excluded.append((s, cls, "ibkr_connection_failed"))
                else:
                    n_intraday = len(equity_needing_intraday)
                    n_non_eq = len(non_equity)
                    log.info(
                        f"Phase 2 (IBKR): {n_intraday} equity intraday + "
                        f"{n_non_eq} non-equity assets"
                    )

                    # -------------------------------------------------------
                    # Non-equity assets: fetch daily first (validates contract)
                    # then intraday interleaved with equity intraday below
                    # -------------------------------------------------------
                    non_eq_assets = [
                        (s, cls) for s, cls in ibkr_work if cls != "equity"
                    ]
                    for symbol, asset_class in non_eq_assets:
                        if ProgressLogger.is_complete(progress, symbol):
                            tfs_done = progress["completed"][symbol].get(
                                "timeframes_fetched", []
                            )
                            for tf in tfs_done:
                                cached = DataStore.load(symbol, tf)
                                if cached is not None:
                                    all_data[f"{symbol}_{tf}"] = cached
                            passed.append((symbol, asset_class))
                            log.info(f"  Resumed   {symbol} ({asset_class})")
                            continue

                        log.info(f"  Daily     {symbol} ({asset_class})")
                        time.sleep(
                            2
                        )  # avoid rapid-fire contract lookups during farm reconnect
                        base_dur = Config.DATA.HISTORY_DEPTH.get(asset_class, "10 Y")
                        daily_dur = self._ibkr._shorter_duration(
                            base_dur, self._ibkr._MAX_DURATION["1 day"]
                        )
                        df_1d = self._ibkr.get_bars(
                            symbol, asset_class, "1 day", "1D", daily_dur
                        )
                        if df_1d is None:
                            excluded.append((symbol, asset_class, "no_daily_data"))
                            continue
                        all_data[f"{symbol}_1D"] = df_1d
                        df_7d = IBKRFeed._resample(df_1d, "W-FRI")
                        df_1m_res = IBKRFeed._resample(df_1d, "1ME")
                        if df_7d is not None:
                            all_data[f"{symbol}_7D"] = df_7d
                        if df_1m_res is not None:
                            all_data[f"{symbol}_1M"] = df_1m_res

                    # -------------------------------------------------------
                    # INTERLEAVED intraday: iterate timeframes as outer loop,
                    # assets as inner loop. This prevents same-contract pacing.
                    # IBKR sees: ABT-4h, ACN-4h, ... then ABT-1h, ACN-1h, ...
                    # By the time we return to the same asset for the next TF,
                    # the same-contract pacing window has cleared.
                    # -------------------------------------------------------
                    all_intraday_assets = []
                    for symbol, asset_class in ibkr_work:
                        if asset_class == "equity":
                            # Include if any intraday TF is still missing
                            if not _intraday_complete(symbol):
                                all_intraday_assets.append((symbol, asset_class))
                            else:
                                # Fully cached — load into all_data
                                for _, tf_lbl, _ in IBKRFeed.INTRADAY_TFS:
                                    cached = DataStore.load(symbol, tf_lbl)
                                    if cached is not None:
                                        all_data[f"{symbol}_{tf_lbl}"] = cached
                        else:
                            if not ProgressLogger.is_complete(progress, symbol):
                                all_intraday_assets.append((symbol, asset_class))

                    if all_intraday_assets:
                        log.info(
                            f"  Interleaved intraday: {len(IBKRFeed.INTRADAY_TFS)} TFs "
                            f"× {len(all_intraday_assets)} assets"
                        )

                    # Wait for HMDS to be fully active before starting
                    # HMDS often connects 30-60s after Gateway link establishes.
                    # Firing intraday requests into an inactive HMDS causes
                    # the first N assets to fail before the farm catches up.
                    # Pause to let IBKR pacing window clear after non-equity daily fetches
                    # 24 rapid daily requests can trigger throttling on subsequent intraday
                    log.info(
                        "  Pausing 30s before intraday sweep (pacing clearance)..."
                    )
                    time.sleep(30)
                    log.info("  Starting interleaved intraday sweep")

                    _bn = 0
                    for tf_ibkr, tf_label, max_dur in IBKRFeed.INTRADAY_TFS:
                        log.info(
                            f"  TF: {tf_label} — {len(all_intraday_assets)} assets"
                        )

                        # Canonical cutoff: computed first so it's always in scope
                        # regardless of which code path (session_dead, normal, etc.)
                        # handles this TF.
                        _canonical_cutoff = compute_canonical_cutoff(tf_label)

                        # Session kill switch: TWS crashed and couldn't recover.
                        # Route all unfetched assets directly to yfinance for this TF.
                        if getattr(self._ibkr, "_session_dead", False):
                            _dead_assets = [
                                (s, cls)
                                for s, cls in all_intraday_assets
                                if not DataStore.is_fresh(
                                    s, tf_label,
                                    max_age_hours=DataStore.intraday_max_age_hours(tf_label),
                                )
                                and cls in ("equity", "etf", "crypto")
                            ]
                            if _dead_assets:
                                log.warning(
                                    f"  [{tf_label}] IBKR session dead — "
                                    f"routing {len(_dead_assets)} assets directly to yfinance"
                                )
                                _dead_cutoff = compute_canonical_cutoff(tf_label)
                                n_dead = 0
                                for sym, cls in _dead_assets:
                                    yf_df = YFinanceFeed.get_intraday_fallback(
                                        sym, cls, tf_label
                                    )
                                    if yf_df is not None and not yf_df.empty:
                                        yf_df = snap_timestamps(
                                            yf_df, tf_label, source="yfinance"
                                        )
                                        yf_df = truncate_to_cutoff(yf_df, _dead_cutoff)
                                    if yf_df is not None and not yf_df.empty:
                                        DataStore.append(sym, tf_label, yf_df)
                                        all_data[f"{sym}_{tf_label}"] = yf_df
                                        n_dead += 1
                                log.info(
                                    f"  [{tf_label}] Dead-session: {n_dead}/{len(_dead_assets)} saved via yfinance"
                                )
                            continue  # skip IBKR sweep for this TF
                        # Reset per-TF counters and rolling failure window
                        self._ibkr._consecutive_fails = 0
                        self._ibkr._circuit_open = False
                        self._ibkr._circuit_open_count = 0
                        self._ibkr._tf_ibkr_attempts = 0
                        self._ibkr._tf_ibkr_successes = 0
                        from collections import deque

                        _rolling = deque(
                            maxlen=10
                        )  # track last 10 IBKR outcomes per TF
                        _ibkr_degraded = False  # True = IBKR too flaky, use batch yf
                        _pending_yf: List[Tuple[str, str]] = []
                        _dual_fail_queue: Dict[str, List[Tuple[str, str]]] = {}

                        for symbol, asset_class in all_intraday_assets:
                            _bn += 1
                            if _bn % 50 == 0:
                                log.info(f"  Batch rest #{_bn} — 60s cooldown")
                                time.sleep(60)
                            if DataStore.is_fresh(
                                symbol, tf_label,
                                max_age_hours=DataStore.intraday_max_age_hours(tf_label),
                            ):
                                cached = DataStore.load(symbol, tf_label)
                                if cached is not None:
                                    all_data[f"{symbol}_{tf_label}"] = cached
                                    # Data exists but may be truncated (yf fallback).
                                    # Track for IBKR upgrade pass after main sweep.
                                    if not DataStore.is_data_sufficient(
                                        symbol, tf_label
                                    ):
                                        _upgrade_queue = getattr(
                                            self, "_ibkr_upgrade_queue", {}
                                        )
                                        _upgrade_queue.setdefault(tf_label, []).append(
                                            (symbol, asset_class)
                                        )
                                        self._ibkr_upgrade_queue = _upgrade_queue
                                continue

                            # When IBKR is degraded, queue for batch yfinance
                            if _ibkr_degraded and asset_class in (
                                "equity",
                                "etf",
                                "crypto",
                            ):
                                _pending_yf.append((symbol, asset_class))
                                continue

                            # Check session kill switch here too (may be set mid-TF)
                            if getattr(self._ibkr, "_session_dead", False):
                                if asset_class in ("equity", "etf", "crypto"):
                                    _pending_yf.append((symbol, asset_class))
                                    _ibkr_degraded = True
                                continue

                            base_dur = Config.DATA.HISTORY_DEPTH.get(
                                asset_class, "10 Y"
                            )
                            effective = self._ibkr._shorter_duration(base_dur, max_dur)
                            df = self._ibkr.get_bars(
                                symbol, asset_class, tf_ibkr, tf_label, effective
                            )

                            if df is None:
                                _rolling.append(False)
                                # Check rolling failure rate — trigger degraded mode
                                if (
                                    not _ibkr_degraded
                                    and len(_rolling) >= 5
                                    and _rolling.count(False) / len(_rolling) >= 0.70
                                ):
                                    _ibkr_degraded = True
                                    log.warning(
                                        f"  [{tf_label}] IBKR failure rate "
                                        f"{_rolling.count(False)/len(_rolling):.0%} over last "
                                        f"{len(_rolling)} assets — switching to batch yfinance. "
                                        f"Pausing 90s for IBKR to recover..."
                                    )
                                    time.sleep(90)
                                    # Queue this asset too (already failed)
                                    if asset_class in ("equity", "etf", "crypto"):
                                        _pending_yf.append((symbol, asset_class))
                                    continue
                                # Individual yfinance fallback (not yet degraded)
                                if tf_label in YFinanceFeed._YF_INTRADAY_MAP:
                                    df = YFinanceFeed.get_intraday_fallback(
                                        symbol, asset_class, tf_label
                                    )
                            else:
                                _rolling.append(True)

                            if df is not None:
                                df = snap_timestamps(df, tf_label)
                                df = truncate_to_cutoff(df, _canonical_cutoff)
                            if df is not None and not df.empty:
                                DataStore.append(symbol, tf_label, df)
                                all_data[f"{symbol}_{tf_label}"] = df
                            elif df is None:
                                # Both sources failed — queue for end-of-sweep retry
                                _dual_fail_queue.setdefault(tf_label, []).append(
                                    (symbol, asset_class)
                                )

                        # Batch yfinance download for assets queued during degraded mode.
                        # Uses get_intraday_fallback() — the correct path for intraday TFs.
                        # get_equity_history() only returns 1D keys; calling it for
                        # "8h"/"1h"/etc. then looking up sym_data.get("8h") always gives None.
                        if _pending_yf:
                            log.info(
                                f"  [{tf_label}] Batch yfinance fallback: "
                                f"{len(_pending_yf)} assets (IBKR was degraded)..."
                            )
                            n_saved = 0
                            for _bi, (sym, cls) in enumerate(_pending_yf):
                                if _bi > 0 and _bi % 50 == 0:
                                    log.info(
                                        f"  [{tf_label}] batch yf progress: "
                                        f"{_bi}/{len(_pending_yf)} ({n_saved} saved)"
                                    )
                                yf_df = YFinanceFeed.get_intraday_fallback(
                                    sym, cls, tf_label
                                )
                                if yf_df is not None and not yf_df.empty:
                                    yf_df = snap_timestamps(
                                        yf_df, tf_label, source="yfinance"
                                    )
                                    yf_df = truncate_to_cutoff(yf_df, _canonical_cutoff)
                                if yf_df is not None and not yf_df.empty:
                                    DataStore.append(sym, tf_label, yf_df)
                                    all_data[f"{sym}_{tf_label}"] = yf_df
                                    n_saved += 1
                            log.info(
                                f"  [{tf_label}] Batch yf complete: "
                                f"{n_saved}/{len(_pending_yf)} saved"
                            )

                    # Save conId cache (new resolutions from this sweep)
                    ConIdCache.save()

                    # ── Dual-failure retry ───────────────────────────────────
                    # Assets where both IBKR and yfinance returned nothing.
                    # IBKR may have recovered; yfinance may have been transiently
                    # rate-limited. One retry pass at end of sweep.
                    # Persistent multi-run failures trigger auto-exclusion.
                    _all_dual = [
                        (tf_f, s, c)
                        for tf_f, pairs in _dual_fail_queue.items()
                        for s, c in pairs
                    ]
                    if _all_dual:
                        log.info(
                            f"  Dual-fail retry: {len(_all_dual)} asset-TF combos..."
                        )
                        _n_recovered = 0
                        _fail_path = os.path.join(
                            Config.DATA.CACHE_DIR, "persistent_failures.json"
                        )
                        _pfails: Dict[str, int] = {}
                        if os.path.exists(_fail_path):
                            try:
                                with open(_fail_path) as _f:
                                    _pfails = json.load(_f)
                            except Exception:
                                pass

                        for tf_f, sym_f, cls_f in _all_dual:
                            r = YFinanceFeed.get_intraday_fallback(sym_f, cls_f, tf_f)
                            if r is not None and not r.empty:
                                r = snap_timestamps(r, tf_f, "yfinance")
                                r = truncate_to_cutoff(
                                    r, compute_canonical_cutoff(tf_f)
                                )
                            if r is not None and not r.empty:
                                DataStore.append(sym_f, tf_f, r)
                                all_data[f"{sym_f}_{tf_f}"] = r
                                _n_recovered += 1
                            else:
                                key = f"{sym_f}:{tf_f}"
                                _pfails[key] = _pfails.get(key, 0) + 1
                                # Auto-exclude when ALL TFs for this symbol have
                                # failed >= _PERSISTENT_FAIL_THRESHOLD times
                                _sym_total = sum(
                                    v
                                    for k, v in _pfails.items()
                                    if k.startswith(f"{sym_f}:")
                                )
                                if (
                                    _sym_total
                                    >= UniverseBuilder._PERSISTENT_FAIL_THRESHOLD
                                ):
                                    UniverseBuilder.add_exclusion(
                                        sym_f,
                                        f"Auto-excluded: {_sym_total} run failures",
                                    )
                                    log.warning(
                                        f"  Auto-excluded {sym_f} after "
                                        f"{_sym_total} persistent failures"
                                    )
                        try:
                            with open(_fail_path, "w") as _f:
                                json.dump(_pfails, _f, indent=2)
                        except Exception:
                            pass
                        log.info(
                            f"  Dual-fail retry: {_n_recovered}/{len(_all_dual)} recovered"
                        )

                    # IBKR upgrade pass: re-try assets where yfinance gave
                    # truncated history. IBKR congestion typically clears after
                    # a full TF sweep; wait 60s then retry for deeper history.
                    upgrade_queue = getattr(self, "_ibkr_upgrade_queue", {})
                    if upgrade_queue:
                        log.info(
                            f"  IBKR upgrade pass: {sum(len(v) for v in upgrade_queue.values())} "
                            f"assets have insufficient bar counts — retrying after 60s cooldown..."
                        )
                        time.sleep(60)
                        for up_tf, up_assets in upgrade_queue.items():
                            up_tf_ibkr = next(
                                (
                                    ib
                                    for ib, lbl, _ in IBKRFeed.INTRADAY_TFS
                                    if lbl == up_tf
                                ),
                                None,
                            )
                            if up_tf_ibkr is None:
                                continue
                            up_max_dur = next(
                                (
                                    d
                                    for _, lbl, d in IBKRFeed.INTRADAY_TFS
                                    if lbl == up_tf
                                ),
                                "1 Y",
                            )
                            n_upgraded = 0
                            for sym, cls in up_assets:
                                base_dur = Config.DATA.HISTORY_DEPTH.get(cls, "10 Y")
                                eff_dur = self._ibkr._shorter_duration(
                                    base_dur, up_max_dur
                                )
                                df_new = self._ibkr.get_bars(
                                    sym, cls, up_tf_ibkr, up_tf, eff_dur
                                )
                                if df_new is not None and not df_new.empty:
                                    # No longer gated on "only if longer than what's
                                    # cached" — now that the cache accumulates,
                                    # append's own dedup (keep latest overlapping
                                    # bar) is the correct merge regardless of which
                                    # fetch happens to be longer in isolation.
                                    DataStore.append(sym, up_tf, df_new)
                                    all_data[f"{sym}_{up_tf}"] = df_new
                                    n_upgraded += 1
                            if n_upgraded:
                                log.info(
                                    f"  Upgraded {n_upgraded}/{len(up_assets)} assets "
                                    f"at {up_tf} with deeper IBKR history"
                                )
                        self._ibkr_upgrade_queue = {}

                    # Derive 2m and 3m from 1m for all assets that have 1m data.
                    # Always re-derive from the FULL accumulated 1m (DataStore.load
                    # returns everything on disk, not just this run's fresh fetch)
                    # — no is_fresh() skip here, deliberately, for the same reason
                    # as the 4h-from-1h derivation above: 1m now accumulates, so
                    # 2m/3m must be re-derived every run for their own depth to
                    # grow, and append()'s dedup makes re-deriving from an
                    # unchanged source a harmless no-op.
                    log.info("  Deriving 2m and 3m from 1m bars...")
                    for symbol, asset_class in all_intraday_assets:
                        df_1m = DataStore.load(symbol, "1m")
                        if df_1m is not None:
                            for tf_label, rule in IBKRFeed.RESAMPLED_FROM_1M:
                                resampled = IBKRFeed._resample(df_1m, rule)
                                if resampled is not None:
                                    DataStore.append(symbol, tf_label, resampled)
                                    all_data[f"{symbol}_{tf_label}"] = resampled
                                    log.debug(
                                        f"  Resampled {symbol} {tf_label} from 1m"
                                    )

                    # Mark all assets complete and add to passed
                    all_derived = [tf for tf, _ in IBKRFeed.RESAMPLED_FROM_1M]
                    passed_set = {s for s, _ in passed}
                    for symbol, asset_class in ibkr_work:
                        if symbol in passed_set:
                            continue
                        tfs_done = [
                            tf
                            for tf in (
                                ["1D", "7D", "1M"]
                                + [t for _, t, _ in IBKRFeed.INTRADAY_TFS]
                                + all_derived
                            )
                            if DataStore.is_fresh(symbol, tf)
                        ]
                        if tfs_done:
                            passed.append((symbol, asset_class))
                            ProgressLogger.mark_complete(
                                progress, symbol, asset_class, tfs_done
                            )

                    self._ibkr.disconnect()

        # Add all yfinance assets with daily data to passed list if not already there
        passed_symbols = {s for s, _ in passed}
        for symbol, asset_class in yf_assets:
            if symbol in yf_daily_done and symbol not in passed_symbols:
                passed.append((symbol, asset_class))

        # ---------------------------------------------------------------
        # Post-build incremental refresh for COMPLETED assets
        # The progress-based resume skips completed assets entirely —
        # freshness is never checked for them. Run a post-pass to append
        # new daily bars for yf assets whose cache is stale (> 2 days old).
        # This ensures every run has the latest available daily data,
        # even if the asset was "completed" weeks or months ago.
        # ---------------------------------------------------------------
        stale_completed = [
            (s, cls)
            for s, cls in yf_assets
            if s in {sym for sym, _ in passed}  # successfully built
            and s not in yf_daily_done  # wasn't freshly fetched this session
            and DataStore.needs_refresh(s, "1D")  # daily cache is stale
            and s not in exclusions  # not in exclusion list
        ]
        if stale_completed:
            log.info(
                f"Post-build incremental refresh: {len(stale_completed)} completed "
                f"assets have stale daily data — fetching last 30 days..."
            )
            _ibkr_stale = [s for s, _ in stale_completed]
            _yf_stale = [to_yf_ticker(s, cls) for s, cls in stale_completed]
            _fresh = YFinanceFeed.get_equity_history(
                _ibkr_stale,
                chunk_size=Config.DATA.YF_CHUNK_SIZE,
                yf_tickers=_yf_stale,
                period="1mo",
            )
            n_appended = 0
            for symbol, asset_class in stale_completed:
                sym_data = _fresh.get(symbol, {})
                new_df = sym_data.get("1D") if sym_data else None
                if new_df is not None and not new_df.empty:
                    combined = DataStore.append(symbol, "1D", new_df)
                    if combined is not None:
                        all_data[f"{symbol}_1D"] = combined
                        n_appended += 1
                else:
                    # Refresh failed — load existing cache as-is
                    cached = DataStore.load(symbol, "1D")
                    if cached is not None:
                        all_data[f"{symbol}_1D"] = cached
            log.info(
                f"  Post-build refresh: {n_appended}/{len(stale_completed)} updated"
            )

        # Backfill all_data from DataStore cache.
        # Excluded symbols are explicitly skipped — they must not enter the universe
        # even if cached parquet files exist from before they were excluded.
        all_tf_labels = Config.DATA.TIMEFRAME_LABELS
        backfill_count = 0
        for symbol, asset_class in passed:
            if symbol in exclusions:  # belt-and-suspenders exclusion guard
                continue
            for tf_label in all_tf_labels:
                key = f"{symbol}_{tf_label}"
                if key not in all_data:
                    cached = DataStore.load(symbol, tf_label)
                    if cached is not None:
                        all_data[key] = cached
                        backfill_count += 1

        log.info(
            f"Universe complete: {len(passed)} assets passed, "
            f"{len(excluded)} excluded"
        )
        log.info(
            f"Data keys: {len(all_data)} symbol-timeframe combinations "
            f"({backfill_count} loaded from cache)"
        )

        _summary.write()
        return UniverseResult(
            assets=passed,
            excluded=excluded,
            data=all_data,
            quality_reports=all_reports,
            exclusion_set=exclusions,
        )

    def _build_raw_list(self) -> List[Tuple[str, str]]:
        raw: List[Tuple[str, str]] = []
        seen: set = set()

        def add(symbol: str, asset_class: str):
            key = (symbol.upper(), asset_class)
            if key not in seen:
                seen.add(key)
                raw.append(key)

        for ticker in self._fetch_sp500_tickers():
            add(ticker, "equity")
        for sym in Config.UNIVERSE.CRYPTO:
            add(sym, "crypto")
        for sym in Config.UNIVERSE.FOREX:
            add(sym, "forex")
        for sym in Config.UNIVERSE.COMMODITIES:
            add(sym, "commodity")
        for sym in Config.UNIVERSE.FUTURES:
            add(sym, "futures")
        # ETFs: QQQ, IWM, SPY, VOO, GLD, SLV, USO
        for sym in Config.UNIVERSE.ETFS:
            add(sym, "etf")
        # -----------------------------------------------------------------------
        # S&P Composite 1500 expansion
        # S&P 500 (large-cap) + MidCap 400 + SmallCap 600 = 1500 equities.
        # All quality-screened (profitability, float, liquidity thresholds).
        # Overlap is handled by the seen set — no asset added twice.
        # Together with crypto/forex/commodities/futures/ETFs: ~1531 total.
        # Estimated overnight compute: 12-18 hours at 12 workers.
        # -----------------------------------------------------------------------

        # S&P MidCap 400
        if getattr(Config.UNIVERSE, "INCLUDE_MIDCAP400", True):
            midcap = self._fetch_constituents_cached("sp400", self._fetch_sp400_tickers)
            for ticker in midcap:
                add(ticker, "equity")
            n_added = sum(1 for s, _ in raw) - 500  # approximate
            log.info(
                f"  S&P MidCap 400: fetched {len(midcap)} tickers "
                f"(net new after S&P 500 overlap removed by dedup)"
            )

        # S&P SmallCap 600
        if getattr(Config.UNIVERSE, "INCLUDE_SMALLCAP600", True):
            smallcap = self._fetch_constituents_cached(
                "sp600", self._fetch_sp600_tickers
            )
            for ticker in smallcap:
                add(ticker, "equity")
            log.info(
                f"  S&P SmallCap 600: fetched {len(smallcap)} tickers "
                f"(net new after dedup)"
            )

        log.info(
            f"  S&P 1500 total equities in universe: "
            f"{sum(1 for _, cls in raw if cls == 'equity')}"
        )

        return raw

    # -----------------------------------------------------------------------
    # Constituent fetchers — same approach as _fetch_sp500_tickers()
    # -----------------------------------------------------------------------

    _CONSTITUENT_CACHE_DIR = os.path.join(os.path.dirname(__file__), "output", "cache")

    @staticmethod
    def _fetch_constituents_cached(
        cache_name: str,
        fetch_fn,
        max_age_hours: float = 24,
    ) -> List[str]:
        """
        Generic cached constituent fetcher with 24-hour staleness check.

        Safety net: if the live fetch_fn() returns suspiciously few tickers
        (or zero) — e.g. from a transient Wikipedia/network failure — fall
        back to the last-known-good cache EVEN IF IT'S STALE, rather than
        silently caching/returning a broken result. A 2-day-old complete
        list (e.g. 600 SmallCap tickers) is far more useful than a fresh
        but empty/truncated one. This prevents a single bad network moment
        from silently shrinking the entire universe (confirmed incident:
        2026-06-19, SmallCap 600 returned 0 tickers, S&P 500 fell through
        to its 50-name emergency fallback — both scrapers failed in the
        same run, most likely from heavy repeated usage that day).
        """
        Config.ensure_dirs()
        cache_path = os.path.join(
            UniverseBuilder._CONSTITUENT_CACHE_DIR, f"{cache_name}.json"
        )

        # Load whatever cache exists, regardless of age, as a fallback
        # candidate and (if fresh enough) as the immediate return value.
        cached_tickers: List[str] = []
        cache_age_h = float("inf")
        if os.path.exists(cache_path):
            cache_age_h = (time.time() - os.path.getmtime(cache_path)) / 3600
            try:
                with open(cache_path) as f:
                    cached_tickers = json.load(f) or []
            except Exception:
                cached_tickers = []

        if cached_tickers and cache_age_h < max_age_hours:
            log.info(
                f"  {cache_name}: {len(cached_tickers)} tickers from cache "
                f"({cache_age_h:.1f}h old)"
            )
            return cached_tickers

        # Cache missing or stale — attempt a live fetch
        fresh_tickers = fetch_fn()

        # Sanity check: a live result with fewer than half the previously
        # cached count (or zero, with no prior cache) is treated as a
        # failed fetch, not a legitimate small universe.
        _suspiciously_small = len(fresh_tickers) == 0 or (
            cached_tickers and len(fresh_tickers) < len(cached_tickers) * 0.5
        )

        if _suspiciously_small and cached_tickers:
            log.warning(
                f"  {cache_name}: live fetch returned {len(fresh_tickers)} "
                f"tickers (suspiciously low vs {len(cached_tickers)} in "
                f"last-known-good cache, {cache_age_h:.1f}h old) — "
                f"using stale cache instead of broken fresh result"
            )
            return cached_tickers

        if _suspiciously_small:
            log.warning(
                f"  {cache_name}: live fetch returned {len(fresh_tickers)} "
                f"tickers and no prior cache exists to fall back on — "
                f"using this result anyway, but it is likely incomplete"
            )

        # CRITICAL: never write an empty result to the cache file.
        # Bug found 2026-06-20: this function previously cached
        # fresh_tickers unconditionally, including empty lists — which
        # overwrote a perfectly good manually-seeded cache (written by
        # seed_sp_caches.py) the moment a single transient live-fetch
        # failure occurred on a later run. An empty result is never worth
        # persisting: either leave an existing good cache file untouched,
        # or simply don't create one — next run will just retry the live
        # fetch again, exactly as if no cache attempt had been made.
        if fresh_tickers:
            try:
                with open(cache_path, "w") as f:
                    json.dump(fresh_tickers, f)
            except Exception:
                pass
        else:
            log.debug(
                f"  {cache_name}: empty result — leaving cache file "
                f"untouched (not overwriting with empty data)"
            )
        return fresh_tickers

    @staticmethod
    def _fetch_nasdaq100_tickers() -> List[str]:
        """Fetch Nasdaq-100 components from Wikipedia."""
        try:
            import requests

            url = "https://en.wikipedia.org/wiki/Nasdaq-100"
            resp = requests.get(
                url,
                headers={
                    # Realistic browser User-Agent (fixes 2026-06-19 incident:
                    # the old bot-identifying string was being blocked/
                    # degraded by Wikipedia — S&P 400/600 scrapers consistently
                    # returned 0 tickers while S&P 500's scraper, which already
                    # used a realistic browser UA, worked reliably throughout).
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                },
                timeout=15,
            )
            tables = pd.read_html(StringIO(resp.text))
            for t in tables:
                for col in t.columns:
                    if "ticker" in str(col).lower() or "symbol" in str(col).lower():
                        tickers = [
                            str(x).strip().upper()
                            for x in t[col]
                            if str(x).strip()
                            and len(str(x).strip()) <= 6
                            and str(x).strip()[0].isalpha()
                        ]
                        if len(tickers) > 50:
                            log.info(
                                f"  Nasdaq-100: {len(tickers)} tickers from Wikipedia"
                            )
                            return tickers
        except Exception as e:
            log.warning(f"Nasdaq-100 fetch failed: {e}")
        return []

    @staticmethod
    def _fetch_russell2000_tickers() -> List[str]:
        """
        Fetch Russell 2000 components from iShares IWM holdings CSV.
        The iShares CSV is publicly available and contains all ~2000 components.
        Falls back to a Wikipedia scrape if the CSV is unavailable.
        """
        try:
            import requests, io

            # iShares publicly accessible holdings CSV for IWM
            url = (
                "https://www.ishares.com/us/products/239710/ishares-russell-2000-etf/"
                "1521561966099.ajax?fileType=csv&fileName=IWM_holdings&dataType=fund"
            )
            resp = requests.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                },
                timeout=30,
            )
            if resp.status_code == 200:
                # iShares CSV has a 2-row header before the actual data
                text = resp.text
                # Find the header row containing "Ticker"
                lines = text.splitlines()
                header_idx = next(
                    (i for i, l in enumerate(lines) if "Ticker" in l or "CUSIP" in l),
                    None,
                )
                if header_idx is not None:
                    csv_text = "\n".join(lines[header_idx:])
                    df_iw = pd.read_csv(io.StringIO(csv_text))
                    # Find ticker column
                    for col in df_iw.columns:
                        if "ticker" in str(col).lower():
                            tickers = [
                                str(x).strip().upper()
                                for x in df_iw[col]
                                if str(x).strip()
                                and len(str(x).strip()) <= 6
                                and str(x).strip()[0].isalpha()
                                and str(x).strip() not in ("-", "NaN", "")
                            ]
                            tickers = [t for t in tickers if t]
                            log.info(
                                f"  Russell 2000: {len(tickers)} tickers from iShares CSV"
                            )
                            return tickers
        except Exception as e:
            log.warning(f"Russell 2000 iShares fetch failed: {e} — trying fallback")

        # Fallback: Wikipedia list of Russell 2000 (partial, top components)
        try:
            import requests

            # Wikipedia doesn't have the full 2000 but has notable components
            url = "https://en.wikipedia.org/wiki/Russell_2000_Index"
            resp = requests.get(
                url,
                headers={
                    # Realistic browser User-Agent (fixes 2026-06-19 incident:
                    # the old bot-identifying string was being blocked/
                    # degraded by Wikipedia — S&P 400/600 scrapers consistently
                    # returned 0 tickers while S&P 500's scraper, which already
                    # used a realistic browser UA, worked reliably throughout).
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                },
                timeout=15,
            )
            tables = pd.read_html(StringIO(resp.text))
            for t in tables:
                for col in t.columns:
                    if "ticker" in str(col).lower() or "symbol" in str(col).lower():
                        tickers = [
                            str(x).strip().upper()
                            for x in t[col]
                            if str(x).strip()
                            and len(str(x).strip()) <= 6
                            and str(x).strip()[0].isalpha()
                        ]
                        if tickers:
                            log.info(f"  Russell 2000 fallback: {len(tickers)} tickers")
                            return tickers
        except Exception as e:
            log.warning(f"Russell 2000 fallback also failed: {e}")

        return []

    @staticmethod
    def _fetch_brk_holdings() -> List[str]:
        """
        Fetch Berkshire Hathaway's publicly disclosed equity holdings from Wikipedia.
        These are the portfolio stocks disclosed in 13F filings (~40-50 names).
        Most are already in S&P 500; deduplication removes overlap.
        """
        try:
            import requests

            url = "https://en.wikipedia.org/wiki/Berkshire_Hathaway"
            resp = requests.get(
                url,
                headers={
                    # Realistic browser User-Agent (fixes 2026-06-19 incident:
                    # the old bot-identifying string was being blocked/
                    # degraded by Wikipedia — S&P 400/600 scrapers consistently
                    # returned 0 tickers while S&P 500's scraper, which already
                    # used a realistic browser UA, worked reliably throughout).
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                },
                timeout=15,
            )
            tables = pd.read_html(StringIO(resp.text))
            for t in tables:
                for col in t.columns:
                    if "ticker" in str(col).lower() or "symbol" in str(col).lower():
                        tickers = [
                            str(x).strip().upper()
                            for x in t[col]
                            if str(x).strip()
                            and len(str(x).strip()) <= 6
                            and str(x).strip()[0].isalpha()
                        ]
                        if len(tickers) > 5:
                            log.info(
                                f"  BRK holdings: {len(tickers)} tickers from Wikipedia"
                            )
                            return tickers
        except Exception as e:
            log.warning(f"BRK holdings fetch failed: {e}")
        return []

    @staticmethod
    def _fetch_qqq_extras(sp500_tickers: List[str]) -> List[str]:
        """Return Nasdaq-100 tickers not already in S&P 500."""
        qqq_tickers = UniverseBuilder._fetch_constituents_cached(
            "nasdaq100", UniverseBuilder._fetch_nasdaq100_tickers
        )
        sp500_set = set(sp500_tickers)
        extras = [t for t in qqq_tickers if t not in sp500_set]
        log.info(f"  QQQ extras: {len(extras)} Nasdaq-100 names not in S&P 500")
        return extras

    _SP500_CACHE = os.path.join(
        os.path.dirname(__file__), "output", "cache", "sp500_tickers.json"
    )

    @staticmethod
    def _fetch_sp_index_wikipedia(
        url: str,
        cache_name: str,
        expected_min: int = 50,
    ) -> List[str]:
        """
        Generic Wikipedia scraper for S&P index constituent tables.
        All three S&P indices (500, 400, 600) share the same Wikipedia
        table format with a Symbol/Ticker column.
        """
        import requests

        _UA = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        try:
            resp = requests.get(url, headers={"User-Agent": _UA}, timeout=15)
            log.debug(
                f"  {cache_name}: HTTP {resp.status_code}, "
                f"{len(resp.text)} chars received"
            )
            if resp.status_code != 200:
                log.warning(
                    f"  {cache_name}: HTTP {resp.status_code} (expected 200) "
                    f"— Wikipedia may be blocking or redirecting this request"
                )
                return []

            tables = pd.read_html(StringIO(resp.text))
            log.debug(f"  {cache_name}: pd.read_html found {len(tables)} tables")

            # Track the best candidate even if below expected_min, so we can
            # report exactly why nothing qualified instead of returning a
            # silent empty list with zero diagnostic information.
            best_tickers: List[str] = []
            best_col_desc = "none"
            candidates_seen = []

            for ti, t in enumerate(tables):
                for col in t.columns:
                    col_s = str(col).lower()
                    if "symbol" in col_s or "ticker" in col_s:
                        tickers = [
                            str(x).strip().upper().replace(".", "-")
                            for x in t[col]
                            if str(x).strip()
                            and len(str(x).strip()) <= 6
                            and str(x).strip()[0].isalpha()
                        ]
                        candidates_seen.append(
                            f"table[{ti}] col={col!r} -> {len(tickers)} tickers"
                        )
                        if len(tickers) >= expected_min:
                            log.info(
                                f"  {cache_name}: {len(tickers)} tickers from Wikipedia"
                            )
                            return tickers
                        if len(tickers) > len(best_tickers):
                            best_tickers = tickers
                            best_col_desc = f"table[{ti}] col={col!r}"

            # Nothing met expected_min — log exactly what WAS found so the
            # next run's log shows the real reason instead of silence.
            if candidates_seen:
                log.warning(
                    f"  {cache_name}: no symbol/ticker column reached "
                    f"expected_min={expected_min}. Candidates found: "
                    f"{'; '.join(candidates_seen)}"
                )
            else:
                log.warning(
                    f"  {cache_name}: scanned {len(tables)} tables, found "
                    f"{sum(len(t.columns) for t in tables)} total columns, "
                    f"NONE matched 'symbol' or 'ticker' in the column name. "
                    f"Page structure may have changed. First table columns "
                    f"(if any): {list(tables[0].columns) if tables else 'no tables found'}"
                )

            # Best-effort fallback: if the closest candidate is at least
            # half of expected_min, use it rather than returning nothing —
            # a slightly-short list is still far more useful than empty,
            # and this is clearly logged so it's never mistaken for a
            # full, verified result.
            if len(best_tickers) >= expected_min * 0.5:
                log.warning(
                    f"  {cache_name}: using best-effort partial result "
                    f"({best_col_desc}, {len(best_tickers)} tickers, below "
                    f"the {expected_min} threshold) rather than nothing"
                )
                return best_tickers

        except Exception as e:
            log.warning(
                f"Wikipedia fetch failed for {cache_name}: {type(e).__name__}: {e}"
            )
        return []

    @staticmethod
    def _fetch_sp400_tickers() -> List[str]:
        """Fetch S&P MidCap 400 constituents from Wikipedia."""
        return UniverseBuilder._fetch_sp_index_wikipedia(
            "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
            "S&P MidCap 400",
            expected_min=350,
        )

    @staticmethod
    def _fetch_sp600_tickers() -> List[str]:
        """Fetch S&P SmallCap 600 constituents from Wikipedia."""
        return UniverseBuilder._fetch_sp_index_wikipedia(
            "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
            "S&P SmallCap 600",
            expected_min=500,
        )

    @staticmethod
    def _save_sp500_cache(tickers):
        try:
            Config.ensure_dirs()
            with open(UniverseBuilder._SP500_CACHE, "w") as f:
                json.dump(tickers, f)
        except Exception:
            pass

    @staticmethod
    def _fetch_sp500_tickers() -> List[str]:
        Config.ensure_dirs()
        cache = UniverseBuilder._SP500_CACHE
        if os.path.exists(cache):
            age_h = (time.time() - os.path.getmtime(cache)) / 3600
            if age_h < 24:
                try:
                    with open(cache) as f:
                        tickers = json.load(f)
                    if len(tickers) > 400:
                        log.info(
                            f"S&P 500: {len(tickers)} tickers from cache ({age_h:.1f}h old)"
                        )
                        return tickers
                except Exception:
                    pass
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
            url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            tables = pd.read_html(StringIO(resp.text), header=0)
            tickers = tables[0]["Symbol"].tolist()
            tickers = [str(t).replace(".", " ") for t in tickers]
            log.info(f"S&P 500: {len(tickers)} tickers from Wikipedia")
            UniverseBuilder._save_sp500_cache(tickers)
            return tickers
        except Exception as e:
            log.warning(f"Wikipedia S&P 500 failed: {e}")

        try:
            url = (
                "https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf/"
                "1467271812596.ajax?fileType=csv&fileName=IVV_holdings&dataType=fund"
            )
            df = pd.read_csv(url, skiprows=9, header=0)
            tickers = df["Ticker"].dropna().tolist()
            tickers = [
                str(t).strip().replace(".", " ")
                for t in tickers
                if str(t).strip() not in ("", "nan", "-")
            ]
            if len(tickers) > 400:
                log.info(f"S&P 500: {len(tickers)} tickers from iShares IVV")
                UniverseBuilder._save_sp500_cache(tickers)
                return tickers
        except Exception as e:
            log.warning(f"iShares IVV fetch failed: {e}")

        # Both Wikipedia and iShares failed. Before falling all the way
        # to the 50-name emergency list, check for ANY existing cache —
        # even badly stale — since a week-old complete 503-ticker list
        # is far better than a hardcoded 50-name placeholder. This is
        # what should have triggered on 2026-06-19 when both live
        # sources failed in the same run (likely from heavy repeated
        # usage that day) — instead the run silently used the 50-name
        # fallback and shrank the entire universe without warning.
        if os.path.exists(cache):
            try:
                with open(cache) as f:
                    stale_tickers = json.load(f)
                if len(stale_tickers) > 400:
                    stale_age_h = (time.time() - os.path.getmtime(cache)) / 3600
                    log.warning(
                        f"S&P 500: both live sources failed. Using stale "
                        f"cache ({len(stale_tickers)} tickers, "
                        f"{stale_age_h:.1f}h old) instead of the 50-name "
                        f"emergency fallback."
                    )
                    return stale_tickers
            except Exception:
                pass

        log.error(
            "S&P 500: ALL sources failed (Wikipedia, iShares, AND no "
            "usable cache) — falling back to hardcoded 50-name emergency "
            "list. The universe for this run will be severely incomplete. "
            "Check network connectivity before trusting results."
        )
        return [
            "AAPL",
            "MSFT",
            "NVDA",
            "AMZN",
            "GOOGL",
            "GOOG",
            "META",
            "TSLA",
            "BRK B",
            "LLY",
            "JPM",
            "V",
            "UNH",
            "XOM",
            "MA",
            "AVGO",
            "JNJ",
            "PG",
            "HD",
            "COST",
            "MRK",
            "ABBV",
            "CVX",
            "CRM",
            "NFLX",
            "AMD",
            "BAC",
            "KO",
            "PEP",
            "TMO",
            "ORCL",
            "ACN",
            "MCD",
            "CSCO",
            "ABT",
            "GE",
            "DHR",
            "TXN",
            "ADBE",
            "WMT",
            "PM",
            "IBM",
            "CAT",
            "INTU",
            "AMGN",
            "GS",
            "SPGI",
            "RTX",
            "ISRG",
            "NOW",
        ]


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    log.info("=" * 60)
    log.info("CAMARF  —  data.py  —  Universe Build")
    log.info("=" * 60)

    builder = UniverseBuilder()
    result = builder.build(connect=False)  # yfinance-only; use data_ibkr.py for IBKR

    log.info(f"\nFinal universe: {len(result.assets)} assets")
    log.info(f"Excluded:       {len(result.excluded)} assets")
    log.info(f"Data keys:      {len(result.data)} symbol-timeframe combinations")

    if result.excluded:
        log.info("\nExclusion summary (first 20):")
        for sym, cls, reason in result.excluded[:20]:
            log.info(f"  {sym:12s} ({cls:10s})  →  {reason}")
        if len(result.excluded) > 20:
            log.info(f"  ... and {len(result.excluded) - 20} more")
