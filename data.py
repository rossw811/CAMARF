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
import asyncio
import numpy as np
import pandas as pd
import yfinance as yf
import pandas_market_calendars as mcal
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

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
    assets: List[Tuple[str, str]]
    excluded: List[Tuple[str, str, str]]
    data: Dict[str, pd.DataFrame]
    quality_reports: List[QualityReport]


# =============================================================================
# CLASS 1 — DataStore
# =============================================================================


class DataStore:
    """Parquet cache. All classes read/write through here."""

    @staticmethod
    def _path(symbol: str, tf_label: str) -> str:
        Config.ensure_dirs()
        fname = f"{symbol}_{tf_label}.parquet".replace("/", "-").replace(" ", "_")
        return os.path.join(Config.DATA.CACHE_DIR, fname)

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
    def is_fresh(symbol: str, tf_label: str, max_age_hours: float = None) -> bool:
        path = DataStore._path(symbol, tf_label)
        if not os.path.exists(path):
            return False
        if max_age_hours is not None:
            age_hours = (time.time() - os.path.getmtime(path)) / 3600
            return age_hours < max_age_hours
        return True

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
        try:
            with open(ProgressLogger.PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            log.warning("Progress file corrupt — starting fresh")
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
        if stored_hash != current_hash:
            log.info(
                f"Config changed since {symbol} was last fetched "
                f"({stored_hash[:8]} → {current_hash[:8]}) — re-fetching"
            )
            return False
        return True

    @staticmethod
    def reset() -> None:
        if os.path.exists(ProgressLogger.PROGRESS_FILE):
            os.remove(ProgressLogger.PROGRESS_FILE)
            log.info("Progress file reset — next build will re-fetch all assets")


# =============================================================================
# CLASS 1c — DataAligner
# Aligns all assets to a common NYSE calendar timeline with gap flagging.
# =============================================================================


class DataAligner:
    """
    Aligns OHLCV DataFrames across all assets to a common timeline.

    Strategy:
      - Master calendar: NYSE trading sessions (Option A)
        All asset classes — equities, forex, crypto, futures, commodities —
        are aligned to the NYSE daily calendar. Non-equity assets that trade
        on NYSE holidays are forward-filled to that date. This ensures every
        asset has an identical DatetimeIndex, which is required for pairwise
        cointegration and spread calculations in analysis.py.

      - Gap handling: forward-fill + flag
        Missing bars (asset not traded, data unavailable) are forward-filled
        using the last known price. A boolean `is_gap` column is added to mark
        filled bars so the analysis layer can condition on data quality.
        Volume is set to 0 for filled bars.

      - Intraday alignment:
        For sub-daily timeframes, alignment is to the asset's own trading
        session calendar rather than NYSE — overnight gaps and weekends are
        already excluded by DataCleaner._fill_gaps(). The `is_gap` flag
        marks within-session gaps (e.g. thinly-traded stocks with no prints
        for 15 minutes).

    The aligned data is cached to DataStore with a "_aligned" suffix so
    downstream modules always consume the aligned version.
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
        start_date: str = None,
        end_date: str = None,
    ) -> Dict[str, pd.DataFrame]:
        """
        Align all daily DataFrames to the NYSE master calendar.

        Parameters
        ----------
        data       : dict of {symbol: DataFrame} with DatetimeIndex
        start_date : earliest date to include (None = min across all assets)
        end_date   : latest date to include (None = max across all assets)

        Returns
        -------
        Dict of aligned DataFrames, each with an added boolean `is_gap` column.
        Assets missing more than 50% of the master calendar are excluded
        and logged as data-quality failures.
        """
        if not data:
            return {}

        # Determine common date range
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
        log.info(
            f"DataAligner: aligning {len(data)} assets to NYSE calendar "
            f"({start} → {end}, {len(master_idx)} sessions)"
        )

        aligned: Dict[str, pd.DataFrame] = {}
        for symbol, df in data.items():
            if df is None or df.empty:
                continue

            # Normalize index to date-only (strip intraday time component)
            df = df.copy()
            df.index = df.index.normalize()

            # Reindex to master calendar
            df_aligned = df.reindex(master_idx)

            # Flag gaps before filling
            df_aligned["is_gap"] = df_aligned["close"].isna()

            # Forward-fill price columns
            for col in ["open", "high", "low", "close"]:
                if col in df_aligned.columns:
                    df_aligned[col] = df_aligned[col].ffill()

            # Zero-fill volume for gap bars (no trades occurred)
            if "volume" in df_aligned.columns:
                df_aligned["volume"] = df_aligned["volume"].fillna(0)

            # Drop leading NaN rows (asset didn't exist yet at master start)
            first_valid = df_aligned["close"].first_valid_index()
            if first_valid is not None:
                df_aligned = df_aligned.loc[first_valid:]

            # Quality check: exclude assets with >50% gaps
            gap_pct = df_aligned["is_gap"].mean()
            if gap_pct > 0.50:
                log.warning(
                    f"DataAligner: {symbol} has {gap_pct:.1%} gap rate "
                    f"on master calendar — excluded from aligned dataset"
                )
                continue

            aligned[symbol] = df_aligned
            if gap_pct > 0.05:
                log.debug(
                    f"DataAligner: {symbol} gap rate {gap_pct:.1%} (flagged, kept)"
                )

        log.info(
            f"DataAligner: {len(aligned)}/{len(data)} assets aligned "
            f"({len(data)-len(aligned)} excluded for excessive gaps)"
        )
        return aligned

    @staticmethod
    def align_intraday(
        data: Dict[str, pd.DataFrame],
        tf_label: str,
    ) -> Dict[str, pd.DataFrame]:
        """
        Align intraday DataFrames within each asset's own trading session.

        For intraday, we don't impose a cross-asset master calendar since
        assets have different trading hours. Instead we:
          1. Forward-fill within-session gaps (missing bars due to no trades)
          2. Add is_gap flag
          3. Ensure all assets share the same frequency (no irregular spacing)

        Returns aligned DataFrames with is_gap column added.
        """
        freq_map = {
            "4h": "4h",
            "8h": "8h",
            "1h": "1h",
            "30m": "30min",
            "15m": "15min",
            "5m": "5min",
            "3m": "3min",
            "2m": "2min",
            "1m": "1min",
        }
        freq = freq_map.get(tf_label)

        aligned: Dict[str, pd.DataFrame] = {}
        for symbol, df in data.items():
            if df is None or df.empty:
                continue

            df = df.copy()

            if freq and len(df) > 10:
                # Reindex to regular frequency within the existing range
                full_idx = pd.date_range(df.index.min(), df.index.max(), freq=freq)
                df_aligned = df.reindex(full_idx)

                # Flag gaps
                df_aligned["is_gap"] = df_aligned["close"].isna()

                # Forward-fill price within session
                for col in ["open", "high", "low", "close"]:
                    if col in df_aligned.columns:
                        df_aligned[col] = df_aligned[col].ffill()

                if "volume" in df_aligned.columns:
                    df_aligned["volume"] = df_aligned["volume"].fillna(0)

                # Drop overnight and weekend gaps (large time jumps > 12h are natural breaks)
                time_diffs = df_aligned.index.to_series().diff()
                natural_break = time_diffs > pd.Timedelta("12h")
                df_aligned = df_aligned[
                    ~natural_break | df_aligned["is_gap"].shift(-1).fillna(False)
                ]

                aligned[symbol] = df_aligned.dropna(subset=["close"])
            else:
                df["is_gap"] = False
                aligned[symbol] = df

        return aligned

    @staticmethod
    def align_universe(
        universe_data: Dict[str, pd.DataFrame],
        tf_label: str = "1D",
    ) -> Dict[str, pd.DataFrame]:
        """
        Top-level alignment method. Routes to daily or intraday aligner
        based on tf_label. Returns aligned dict ready for analysis.py.

        Keys in universe_data are "SYMBOL_TFLABEL" format.
        Returns same format with is_gap column added to each DataFrame.
        """
        # Extract only the requested timeframe
        tf_data = {
            k.replace(f"_{tf_label}", ""): v
            for k, v in universe_data.items()
            if k.endswith(f"_{tf_label}") and v is not None
        }

        if tf_label == "1D":
            return DataAligner.align_daily(tf_data)
        else:
            return DataAligner.align_intraday(tf_data, tf_label)


# =============================================================================
# CLASS 2 — DataCleaner
# =============================================================================


class DataCleaner:
    """
    Cleans raw OHLCV bar data for analytical use.

    Pipeline:
        1. Standardize columns and promote date column to DatetimeIndex
        2. Remove duplicate timestamps
        3. Gap detection and forward-fill (NYSE calendar for daily equities,
           skipped for intraday — markets are genuinely closed overnight)
        4. Roll adjustment for futures
        5. Dollar-volume liquidity filter for equities
        6. Minimum bar count validation (per-timeframe threshold)
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
            "8 hours",
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
    """

    # yfinance fetches daily/weekly/monthly only.
    # Intraday (1m through 8h) fetched from IBKR for proper historical depth:
    #   IBKR 1h  → 5Y,  IBKR 4h/8h → 10Y,  IBKR 1m → 42D
    # yfinance intraday depths are too shallow for meaningful analysis:
    #   yfinance 1h → 730D,  yfinance 5m → 60D,  yfinance 1m → 7D
    _YF_INTERVALS: List[Tuple[str, str, str]] = [
        # (yf_interval, tf_label, max_period)
        ("1d", "1D", "max"),
        ("1wk", "7D", "max"),
        ("1mo", "1M", "max"),
    ]

    @staticmethod
    def get_equity_history(
        tickers: List[str],
        chunk_size: int = 50,
        yf_tickers: List[str] = None,
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
                chunk_data = YFinanceFeed._download_chunk(
                    chunk_ibkr,
                    yf_interval,
                    tf_label,
                    max_period,
                    yf_tickers=chunk_yf,
                )
                for symbol, df in chunk_data.items():
                    if symbol not in results:
                        results[symbol] = {}
                    results[symbol][tf_label] = df

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
                            import contextlib, io

                            with contextlib.redirect_stderr(io.StringIO()):
                                raw = yf.download(
                                    yf_sym,
                                    period=max_period,
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
            if not DataStore.is_fresh(ibkr, tf_label)
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
            return {t: None for t in uncached}

        if raw is None or raw.empty:
            log.warning(f"    yfinance returned empty for {tf_label}")
            return {t: None for t in uncached}

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
            resampled = df.resample(rule).agg(agg).dropna(subset=["open", "close"])
            return resampled if len(resampled) >= 2 else None
        except Exception as e:
            log.debug(f"Resample failed ({rule}): {e}")
            return None

    # yfinance intraday interval mapping: tf_label → (yf_interval, max_period)
    _YF_INTRADAY_MAP: Dict[str, Tuple[str, str]] = {
        "4h": ("1h", "730d"),  # resample from 1h
        "8h": ("1h", "730d"),  # resample from 1h
        "1h": ("1h", "730d"),
        "30m": ("30m", "60d"),
        "15m": ("15m", "60d"),
        "5m": ("5m", "60d"),
        "3m": ("1m", "5d"),  # resample from 1m; Yahoo 1m limit = 8 days
        "2m": ("2m", "60d"),
        "1m": ("1m", "5d"),  # Yahoo 1m hard limit = 8 days; 5d is safe
    }

    # TFs that require resampling from their yfinance source interval
    _YF_RESAMPLE_RULES: Dict[str, str] = {
        "4h": "4h",
        "8h": "8h",
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
        resampling to the target TF where necessary (4h/8h from 1h, 3m from 1m).
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

        periods_to_try = [period, "60d"] if period != "60d" else ["60d"]
        raw = None
        worked_period = None
        for try_period in periods_to_try:
            try:
                import contextlib, io

                with contextlib.redirect_stderr(io.StringIO()):
                    r = yf.download(
                        yf_sym,
                        period=try_period,
                        interval=yf_interval,
                        auto_adjust=True,
                        progress=False,
                        threads=False,
                    )
                if r is not None and not r.empty:
                    raw = r
                    worked_period = try_period
                    break
            except Exception as e:
                log.debug(
                    f"yfinance {symbol} {tf_label} period={try_period} {type(e).__name__}: {e}"
                )

        if raw is None or raw.empty:
            return None

        # Cache the period that worked if different from default
        if worked_period and periods_to_try and worked_period != periods_to_try[0]:
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
        "8 hours": "10 Y",
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
            f"falling back to yfinance for remaining assets"
        )
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
            "8 hours",
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
        if DataStore.is_fresh(symbol, tf_label):
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
            "8 hours",
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
                    "8 hours",
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
                        "8 hours",
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
                    DataStore.save(symbol, tf_label, yf_df)
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
                    DataStore.save(symbol, tf_label, yf_df)
                    log.info(
                        f"  ✓ yfinance (1-bar fallback) {symbol} {tf_label} → {len(yf_df)} bars"
                    )
                    return yf_df

        cleaned, report = DataCleaner.clean(
            raw_bars, symbol, asset_class, tf_label, tf_ibkr, source="ibkr"
        )
        if cleaned is not None:
            DataStore.save(symbol, tf_label, cleaned)
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
        ("8 hours", "8h", "10 Y"),
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
            # Skip if already cached
            if DataStore.is_fresh(symbol, tf_label):
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


class UniverseBuilder:
    """
    Constructs the full CAMARF asset universe and fetches all historical data.

    Equity daily/weekly/monthly/intraday → YFinanceFeed (bulk, fast)
    Futures/forex/crypto/commodities → IBKRFeed (all timeframes)
    Equity 3m bars → IBKRFeed (not available from yfinance)
    """

    def __init__(self):
        self._ibkr = IBKRFeed()

    def build(
        self,
        connect: bool = True,
        reset_progress: bool = False,
    ) -> UniverseResult:
        """
        Full pipeline: build universe, fetch data, validate, return result.
        Crash-safe via ProgressLogger. Config-hash-aware cache invalidation.
        """
        Config.ensure_dirs()

        if reset_progress:
            ProgressLogger.reset()

        progress = ProgressLogger.load()
        current_hash = ProgressLogger.compute_config_hash()
        n_done = sum(
            1
            for sym in progress["completed"]
            if ProgressLogger.is_complete(progress, sym)
        )
        if n_done > 0:
            log.info(
                f"Resuming — {n_done} assets already complete (config hash {current_hash})"
            )

        log.info("Building asset universe...")
        raw_assets = self._build_raw_list()
        log.info(f"Universe candidates: {len(raw_assets)} assets")

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
            (s, cls) for s, cls in raw_assets if cls in ("equity", "crypto", "forex")
        ]
        log.info(
            f"Phase 1 (yfinance daily): "
            f"{sum(1 for _,c in yf_assets if c=='equity')} equities + "
            f"{sum(1 for _,c in yf_assets if c=='crypto')} crypto + "
            f"{sum(1 for _,c in yf_assets if c=='forex')} forex"
        )

        yf_daily_done = set()  # track which symbols have daily data confirmed

        uncached_yf = [
            (s, cls) for s, cls in yf_assets if not DataStore.is_fresh(s, "1D")
        ]

        if uncached_yf:
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
        else:
            log.info("  All daily data cached — skipping yfinance download")

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
            """True only if every intraday TF (native + derived) is cached."""
            native_complete = all(
                DataStore.is_fresh(symbol, tf_label)
                for _, tf_label, _ in IBKRFeed.INTRADAY_TFS
            )
            derived_complete = all(
                DataStore.is_fresh(symbol, tf_label)
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
        if ibkr_work:
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
                        # Reset circuit consecutive counter at start of each TF
                        # A bad TF (e.g. 4h failing) shouldn't poison 1h sweep
                        self._ibkr._consecutive_fails = 0
                        self._ibkr._circuit_open = False
                        self._ibkr._circuit_open_count = 0
                        self._ibkr._tf_ibkr_attempts = 0
                        self._ibkr._tf_ibkr_successes = 0
                        # _tf_ibkr_disabled persists across TF sweeps intentionally
                        for symbol, asset_class in all_intraday_assets:
                            _bn += 1
                            if _bn % 50 == 0:
                                log.info(f"  Batch rest #{_bn} — 60s cooldown")
                                time.sleep(60)
                            if DataStore.is_fresh(symbol, tf_label):
                                cached = DataStore.load(symbol, tf_label)
                                if cached is not None:
                                    all_data[f"{symbol}_{tf_label}"] = cached
                                continue

                            base_dur = Config.DATA.HISTORY_DEPTH.get(
                                asset_class, "10 Y"
                            )
                            effective = self._ibkr._shorter_duration(base_dur, max_dur)
                            df = self._ibkr.get_bars(
                                symbol, asset_class, tf_ibkr, tf_label, effective
                            )
                            if df is None and tf_label in YFinanceFeed._YF_INTRADAY_MAP:
                                # IBKR failed — try yfinance fallback immediately
                                df = YFinanceFeed.get_intraday_fallback(
                                    symbol, asset_class, tf_label
                                )
                                if df is not None:
                                    DataStore.save(symbol, tf_label, df)
                                    log.debug(
                                        f"  yf fallback {symbol} {tf_label}: {len(df)} bars"
                                    )
                            if df is not None:
                                all_data[f"{symbol}_{tf_label}"] = df

                    # Derive 2m and 3m from 1m for all assets that have 1m data
                    log.info("  Deriving 2m and 3m from 1m bars...")
                    for symbol, asset_class in all_intraday_assets:
                        df_1m = DataStore.load(symbol, "1m")
                        if df_1m is not None:
                            for tf_label, rule in IBKRFeed.RESAMPLED_FROM_1M:
                                if not DataStore.is_fresh(symbol, tf_label):
                                    resampled = IBKRFeed._resample(df_1m, rule)
                                    if resampled is not None:
                                        DataStore.save(symbol, tf_label, resampled)
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

        # Backfill all_data from DataStore cache.
        # The resume logic skips complete assets during the session loop, so their
        # cached data is never added to all_data. We load everything from disk now
        # so analysis.py receives the full universe — not just this session's fetches.
        all_tf_labels = Config.DATA.TIMEFRAME_LABELS  # ["1m","2m",...,"1D","7D","1M"]
        backfill_count = 0
        for symbol, asset_class in passed:
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

        return UniverseResult(
            assets=passed,
            excluded=excluded,
            data=all_data,
            quality_reports=all_reports,
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

        return raw

    _SP500_CACHE = os.path.join(
        os.path.dirname(__file__), "output", "cache", "sp500_tickers.json"
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
            tables = pd.read_html(resp.text, header=0)
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

        log.warning("Using hardcoded S&P 500 fallback (top 50)")
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
    result = builder.build(connect=True)

    log.info(f"\nFinal universe: {len(result.assets)} assets")
    log.info(f"Excluded:       {len(result.excluded)} assets")
    log.info(f"Data keys:      {len(result.data)} symbol-timeframe combinations")

    if result.excluded:
        log.info("\nExclusion summary (first 20):")
        for sym, cls, reason in result.excluded[:20]:
            log.info(f"  {sym:12s} ({cls:10s})  →  {reason}")
        if len(result.excluded) > 20:
            log.info(f"  ... and {len(result.excluded) - 20} more")
