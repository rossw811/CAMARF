# =============================================================================
# CAMARF — Cross-Asset Co-Movement Arbitrage Research Framework
# data.py — Universe building, IBKR feed, CBOE feed, local caching
# github.com/rossw811/CAMARF
# =============================================================================

import os
import time
import logging
import requests
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import ib_insync as ibi

from config import Config

warnings.filterwarnings("ignore", category=FutureWarning)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("CAMARF.data")


# =============================================================================
# DATACLASSES — shared result containers
# =============================================================================


@dataclass
class QualityReport:
    """Per-asset data cleaning summary."""

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


@dataclass
class UniverseResult:
    """
    Output of UniverseBuilder.build().
    Passed as the single input object to every downstream module.
    """

    assets: List[Tuple[str, str]]  # (symbol, asset_class)
    excluded: List[Tuple[str, str, str]]  # (symbol, asset_class, reason)
    data: Dict[str, pd.DataFrame]  # key: "SYMBOL_TF"
    quality_reports: List[QualityReport]


# =============================================================================
# CLASS 1 — DataStore
# Local Parquet cache. All other classes read/write through here.
# =============================================================================


class DataStore:
    """
    Manages the local Parquet cache for all bar data.

    File naming convention:  {CACHE_DIR}/{symbol}_{timeframe_label}.parquet
    e.g.  output/cache/AAPL_1D.parquet

    No class holds DataStore as an attribute — they call it as a static
    utility so there is exactly one cache location and zero state duplication.
    """

    @staticmethod
    def _path(symbol: str, tf_label: str) -> str:
        """Construct the full file path for a given symbol + timeframe."""
        Config.ensure_dirs()
        fname = f"{symbol}_{tf_label}.parquet".replace("/", "-").replace(" ", "_")
        return os.path.join(Config.DATA.CACHE_DIR, fname)

    @staticmethod
    def save(symbol: str, tf_label: str, df: pd.DataFrame) -> None:
        """
        Write a DataFrame to Parquet.
        Overwrites any existing file for the same symbol + timeframe.
        """
        if df is None or df.empty:
            return
        path = DataStore._path(symbol, tf_label)
        df.to_parquet(path, index=True, compression="snappy")
        log.debug(f"Cached  {symbol} {tf_label}  →  {len(df)} bars")

    @staticmethod
    def load(symbol: str, tf_label: str) -> Optional[pd.DataFrame]:
        """
        Load a DataFrame from Parquet.
        Returns None if the file does not exist.
        """
        path = DataStore._path(symbol, tf_label)
        if not os.path.exists(path):
            return None
        return pd.read_parquet(path)

    @staticmethod
    def is_fresh(symbol: str, tf_label: str, max_age_hours: float = 23.0) -> bool:
        """
        Returns True if the cached file exists and was written within
        max_age_hours hours.  Used to skip re-fetching on daily reruns.
        """
        path = DataStore._path(symbol, tf_label)
        if not os.path.exists(path):
            return False
        age_hours = (time.time() - os.path.getmtime(path)) / 3600
        return age_hours < max_age_hours

    @staticmethod
    def list_cached() -> List[str]:
        """Return all cached file stems (symbol_tf) currently on disk."""
        Config.ensure_dirs()
        files = os.listdir(Config.DATA.CACHE_DIR)
        return [f.replace(".parquet", "") for f in files if f.endswith(".parquet")]


# =============================================================================
# CLASS 2 — DataCleaner
# Pure static methods.  Accepts a raw OHLCV DataFrame, returns a cleaned
# DataFrame plus a QualityReport.  No IBKR or cache dependency.
# =============================================================================


class DataCleaner:
    """
    Cleans raw OHLCV bar data for analytical use.

    Pipeline (applied in order):
        1. Standardize column names and index
        2. Remove duplicate timestamps
        3. Detect and forward-fill gaps (up to MAX_MISSING_PCT threshold)
        4. Apply backward ratio roll adjustment for futures
        5. Apply dollar-volume liquidity filter for equities
        6. Validate minimum bar count
        7. Return (cleaned_df, QualityReport)
    """

    # Expected IBKR column names after ib_insync conversion
    _REQUIRED_COLS = {"open", "high", "low", "close", "volume"}

    @staticmethod
    def clean(
        df: pd.DataFrame,
        symbol: str,
        asset_class: str,
        tf_label: str,
        tf_ibkr: str,
    ) -> Tuple[Optional[pd.DataFrame], QualityReport]:
        """
        Master cleaning method.  Call this — do not call sub-methods directly.

        Parameters
        ----------
        df          : raw OHLCV DataFrame from IBKRFeed
        symbol      : ticker string
        asset_class : one of equity / crypto / forex / commodity / futures
        tf_label    : human label e.g. "1D"
        tf_ibkr     : IBKR bar size string e.g. "1 day"

        Returns
        -------
        (cleaned_df, QualityReport)
        cleaned_df is None if the asset fails validation.
        """
        original_bars = len(df)
        roll_dates: List[str] = []

        # --- Step 1: standardize ---
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
            )

        # --- Step 2: remove duplicates ---
        df = df[~df.index.duplicated(keep="last")]

        # --- Step 3: gap detection and forward-fill ---
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
            )

        # --- Step 4: futures roll adjustment ---
        if asset_class in ("futures", "commodity"):
            df, roll_dates = DataCleaner._roll_adjust(df)

        # --- Step 5: equity liquidity filter ---
        if asset_class == "equity":
            df = DataCleaner._liquidity_filter(df)

        # --- Step 6: minimum bar count ---
        if len(df) < Config.DATA.MIN_BARS_REQUIRED:
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
                fail_reason=f"insufficient_bars_{len(df)}",
            )

        bars_dropped = original_bars - len(df)
        report = QualityReport(
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
        )
        return df, report

    @staticmethod
    def _standardize(df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """
        Normalize column names to lowercase.
        Ensure DatetimeIndex.
        Keep only OHLCV columns.
        """
        df = df.copy()
        df.columns = [c.lower() for c in df.columns]

        # ib_insync uses 'barCount' and 'average' — drop non-OHLCV
        keep = [c for c in df.columns if c in DataCleaner._REQUIRED_COLS]
        if not all(c in keep for c in ["open", "high", "low", "close"]):
            return None
        df = df[keep]

        # Ensure DatetimeIndex
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)

        df = df.sort_index()
        df = df.dropna(subset=["open", "high", "low", "close"])
        return df

    @staticmethod
    def _fill_gaps(
        df: pd.DataFrame,
        tf_ibkr: str,
    ) -> Tuple[pd.DataFrame, int, float]:
        """
        Detect missing bars relative to expected frequency.
        Forward-fill up to the config threshold.

        Returns (filled_df, gap_count, missing_fraction).
        """
        # Map IBKR bar size strings to pandas frequency aliases
        freq_map = {
            "1 min": "1min",
            "5 mins": "5min",
            "15 mins": "15min",
            "30 mins": "30min",
            "1 hour": "1h",
            "4 hours": "4h",
            "8 hours": "8h",
            "12 hours": "12h",
            "1 day": "B",  # business days
            "1 week": "W-FRI",
            "1 month": "MS",
        }
        freq = freq_map.get(tf_ibkr)
        if freq is None:
            # Unknown frequency — skip gap filling, report 0 gaps
            return df, 0, 0.0

        # Build the expected full index and reindex
        full_idx = pd.date_range(df.index.min(), df.index.max(), freq=freq)
        gap_count = len(full_idx) - len(df)
        missing_pct = gap_count / max(len(full_idx), 1)

        df = df.reindex(full_idx)
        df = df.ffill()  # forward-fill price
        if "volume" in df.columns:
            df["volume"] = df["volume"].fillna(
                0
            )  # missing volume = 0 not forward-filled

        return df, gap_count, missing_pct

    @staticmethod
    def _roll_adjust(
        df: pd.DataFrame,
    ) -> Tuple[pd.DataFrame, List[str]]:
        """
        Backward ratio adjustment for continuous futures contracts.

        A roll discontinuity appears as a sudden price jump that is not a
        real price move — it is an artifact of switching contract months.
        Without adjustment, these jumps contaminate every spread and
        cointegration calculation downstream.

        Detection: any single-bar close-to-close return that exceeds 5%
        on a daily or coarser timeframe is flagged as a candidate roll date.
        We then apply a backward ratio multiplier so the historical series
        is continuous in log-return space.

        Note: for intraday timeframes, roll adjustment is skipped because
        IBKR continuous contracts handle this internally at the daily level.
        """
        roll_dates: List[str] = []
        df = df.copy()

        returns = df["close"].pct_change().abs()
        roll_threshold = 0.05  # 5% single-bar return = candidate roll
        roll_idx = returns[returns > roll_threshold].index

        for roll_date in roll_idx:
            roll_dates.append(str(roll_date.date()))
            loc = df.index.get_loc(roll_date)
            if loc == 0:
                continue

            # Ratio between the bar before and the bar at the roll date
            price_before = df["close"].iloc[loc - 1]
            price_after = df["close"].iloc[loc]
            if price_after == 0:
                continue
            ratio = price_before / price_after

            # Apply ratio to all bars before the roll date (backward adjustment)
            df.iloc[:loc, df.columns.get_loc("open")] *= ratio
            df.iloc[:loc, df.columns.get_loc("high")] *= ratio
            df.iloc[:loc, df.columns.get_loc("low")] *= ratio
            df.iloc[:loc, df.columns.get_loc("close")] *= ratio

        return df, roll_dates

    @staticmethod
    def _liquidity_filter(df: pd.DataFrame) -> pd.DataFrame:
        """
        For equities: zero out (NaN) bars where dollar volume is below the
        minimum threshold, then forward-fill.  This prevents illiquid
        periods from generating false spread signals without dropping bars
        (which would create artificial gaps).
        """
        if "volume" not in df.columns:
            return df
        df = df.copy()
        dollar_vol = df["close"] * df["volume"]
        illiquid = dollar_vol < Config.DATA.MIN_DOLLAR_VOLUME
        df.loc[illiquid, ["open", "high", "low", "close"]] = np.nan
        df = df.ffill()
        return df


# =============================================================================
# CLASS 3 — IBKRFeed
# Historical bar data via ib_insync.  Rate-limited, cache-aware.
# =============================================================================


class IBKRFeed:
    """
    Pulls historical OHLCV bars from IBKR Gateway.

    Design principles:
    - Cache-first: checks DataStore before every request
    - Rate-limited: enforces minimum 2s between requests with exponential backoff
    - Graceful degradation: logs failures and returns None without crashing
    - Asset-class-aware: constructs correct Contract object per class

    Usage:
        feed = IBKRFeed()
        feed.connect()
        result = feed.get_full_history("AAPL", "equity")
        feed.disconnect()
    """

    # IBKR maximum duration per bar size — enforced by the API
    # Requesting more than this returns an error
    _MAX_DURATION: Dict[str, str] = {
        "1 min": "30 D",
        "5 mins": "6 M",
        "15 mins": "1 Y",
        "30 mins": "2 Y",
        "1 hour": "5 Y",
        "4 hours": "10 Y",
        "8 hours": "10 Y",
        "12 hours": "10 Y",
        "1 day": "20 Y",
        "1 week": "20 Y",
        "1 month": "20 Y",
    }

    # Futures exchange mapping
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
        self._last_req = 0.0  # timestamp of last IBKR request
        self._req_delay = 2.0  # minimum seconds between requests

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Connect to IBKR Gateway.  Returns True on success."""
        try:
            self._ib.connect(
                Config.IBKR.HOST,
                Config.IBKR.PORT,
                clientId=Config.IBKR.CLIENT_ID,
                readonly=Config.IBKR.READONLY,
                timeout=Config.IBKR.TIMEOUT,
            )
            self._connected = True
            log.info(f"IBKR connected  →  {Config.IBKR.HOST}:{Config.IBKR.PORT}")
            return True
        except Exception as e:
            log.error(f"IBKR connection failed: {e}")
            return False

    def disconnect(self) -> None:
        """Disconnect cleanly."""
        if self._connected:
            self._ib.disconnect()
            self._connected = False
            log.info("IBKR disconnected")

    # ------------------------------------------------------------------
    # Contract construction
    # ------------------------------------------------------------------

    def _build_contract(self, symbol: str, asset_class: str) -> Optional[ibi.Contract]:
        """
        Build the correct ib_insync Contract object for each asset class.

        Equity  → Stock(symbol, SMART, USD)
        Crypto  → Crypto(symbol, PAXOS, USD)
        Forex   → Forex(BASEQUOTE) — period removed from symbol
        Futures/Commodity → Future(symbol, exchange, USD) with front-month

        Returns None if the contract type is unknown.
        """
        try:
            if asset_class == "equity":
                return ibi.Stock(symbol, "SMART", "USD")

            elif asset_class == "crypto":
                return ibi.Crypto(symbol, "PAXOS", "USD")

            elif asset_class == "forex":
                # UniverseConfig stores "EUR.USD" — IBKR wants "EURUSD"
                pair = symbol.replace(".", "")
                return ibi.Forex(pair)

            elif asset_class in ("futures", "commodity"):
                exch = self._FUTURES_EXCHANGE.get(symbol, "CME")
                contract = ibi.Future(symbol, exchange=exch, currency="USD")
                # Qualify to resolve to front-month
                qualified = self._ib.qualifyContracts(contract)
                if qualified:
                    return qualified[0]
                return contract

            else:
                log.warning(f"Unknown asset class '{asset_class}' for {symbol}")
                return None

        except Exception as e:
            log.error(f"Contract build failed for {symbol} ({asset_class}): {e}")
            return None

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _wait_rate_limit(self) -> None:
        """
        Enforce minimum delay between IBKR requests.
        IBKR allows ~50 historical requests per 10 minutes.
        2 seconds between requests keeps us well within that limit.
        """
        elapsed = time.time() - self._last_req
        if elapsed < self._req_delay:
            time.sleep(self._req_delay - elapsed)
        self._last_req = time.time()

    # ------------------------------------------------------------------
    # Core data fetch
    # ------------------------------------------------------------------

    def get_bars(
        self,
        symbol: str,
        asset_class: str,
        tf_ibkr: str,
        tf_label: str,
        duration: str,
    ) -> Optional[pd.DataFrame]:
        """
        Fetch historical OHLCV bars for one symbol + timeframe.

        Cache-first: returns cached data immediately if fresh.
        Falls back to IBKR request if cache is stale or missing.
        Applies DataCleaner and saves result to cache before returning.

        Parameters
        ----------
        symbol      : ticker string
        asset_class : equity / crypto / forex / commodity / futures
        tf_ibkr     : IBKR bar size string e.g. "1 day"
        tf_label    : human label e.g. "1D"
        duration    : IBKR duration string e.g. "20 Y"

        Returns
        -------
        Cleaned OHLCV DataFrame or None if fetch/clean failed.
        """
        # --- Cache check ---
        if DataStore.is_fresh(symbol, tf_label):
            cached = DataStore.load(symbol, tf_label)
            if cached is not None:
                log.debug(f"Cache hit  {symbol} {tf_label}")
                return cached

        if not self._connected:
            log.error("IBKRFeed.get_bars called without active connection")
            return None

        # --- Enforce IBKR duration limits per bar size ---
        max_dur = self._MAX_DURATION.get(tf_ibkr, duration)
        effective_duration = self._shorter_duration(duration, max_dur)

        contract = self._build_contract(symbol, asset_class)
        if contract is None:
            return None

        # --- Request with retry and exponential backoff ---
        raw_bars = None
        for attempt in range(3):
            try:
                self._wait_rate_limit()
                bars = self._ib.reqHistoricalData(
                    contract,
                    endDateTime="",
                    durationStr=effective_duration,
                    barSizeSetting=tf_ibkr,
                    whatToShow=(
                        "TRADES"
                        if asset_class in ("equity", "futures", "commodity")
                        else "MIDPOINT"
                    ),
                    useRTH=False,
                    formatDate=1,
                    keepUpToDate=False,
                    timeout=60,
                )
                if bars:
                    raw_bars = ibi.util.df(bars)
                    break
            except Exception as e:
                wait = 2**attempt * 5
                log.warning(
                    f"IBKR request failed {symbol} {tf_label} attempt {attempt+1}: {e}. Retrying in {wait}s"
                )
                time.sleep(wait)

        if raw_bars is None or raw_bars.empty:
            log.warning(f"No data returned  {symbol} {tf_label}")
            return None

        # --- Clean and cache ---
        cleaned, report = DataCleaner.clean(
            raw_bars, symbol, asset_class, tf_label, tf_ibkr
        )

        if cleaned is not None:
            DataStore.save(symbol, tf_label, cleaned)
            log.info(
                f"Fetched  {symbol} {tf_label}  →  {len(cleaned)} bars  (dropped {report.bars_dropped})"
            )
        else:
            log.warning(f"Dropped  {symbol} {tf_label}  →  {report.fail_reason}")

        return cleaned

    def get_full_history(
        self,
        symbol: str,
        asset_class: str,
    ) -> Dict[str, Optional[pd.DataFrame]]:
        """
        Fetch all 11 timeframes for one asset.

        Returns a dict keyed by tf_label (e.g. "1D") with DataFrame values.
        Any timeframe that fails returns None for that key — the asset is not
        dropped entirely just because one timeframe fails.

        Effective duration per timeframe is always capped by _MAX_DURATION,
        which reflects IBKR's hard per-bar-size history limits.  For example,
        1-minute bars are capped at 30 days regardless of asset class depth.
        """
        result: Dict[str, Optional[pd.DataFrame]] = {}
        base_duration = Config.DATA.HISTORY_DEPTH.get(asset_class, "10 Y")

        for tf_ibkr, tf_label in zip(
            Config.DATA.TIMEFRAMES, Config.DATA.TIMEFRAME_LABELS
        ):
            # _MAX_DURATION caps are enforced inside get_bars via _shorter_duration.
            # We log the effective ceiling here for transparency.
            max_dur = self._MAX_DURATION.get(tf_ibkr, base_duration)
            effective = self._shorter_duration(base_duration, max_dur)
            log.debug(f"  {symbol} {tf_label}: requesting {effective} of history")
            df = self.get_bars(symbol, asset_class, tf_ibkr, tf_label, base_duration)
            result[tf_label] = df

        return result

    @staticmethod
    def _shorter_duration(requested: str, maximum: str) -> str:
        """
        Compare two IBKR duration strings and return the shorter one.
        Prevents requesting more history than IBKR allows per bar size.

        Duration string format: "N UNIT" where UNIT is D / M / Y
        """
        unit_days = {"D": 1, "M": 30, "Y": 365}

        def to_days(s: str) -> int:
            parts = s.strip().split()
            if len(parts) != 2:
                return 0
            n, unit = parts
            return int(n) * unit_days.get(unit.upper(), 1)

        return requested if to_days(requested) <= to_days(maximum) else maximum


# =============================================================================
# CLASS 4 — CBOEFeed
# Options IV surface data from CBOE delayed public endpoint.
# =============================================================================


class CBOEFeed:
    """
    Fetches and parses options IV surface data from CBOE's public delayed
    quotes API.

    The IV surface is a 2D structure:
        rows    = moneyness buckets  (strike / spot, filtered to config range)
        columns = DTE buckets        (days to expiry, filtered to config range)
        values  = mid implied volatility (average of call IV and put IV)

    This surface is used in options.py to:
        1. Compute IV spread between cointegrated asset pairs
        2. Detect IV-based divergence as an additional signal layer

    For assets where CBOE data is unavailable, get_surface() returns None
    and options.py skips the IV signal layer for that pair gracefully.
    """

    # Known CBOE-listed symbols with public delayed data
    # This is not exhaustive — CBOEFeed attempts any symbol and caches
    # the result so failures are only attempted once per session
    _CBOE_SUPPORTED = {
        "SPY",
        "QQQ",
        "IWM",
        "DIA",
        "GLD",
        "SLV",
        "USO",
        "SPX",
        "NDX",
        "VIX",
        "RUT",
        "AAPL",
        "MSFT",
        "AMZN",
        "GOOGL",
        "META",
        "NVDA",
        "TSLA",
    }

    _SESSION_CACHE: Dict[str, Optional[pd.DataFrame]] = {}  # in-memory cache per run

    @staticmethod
    def get_surface(symbol: str) -> Optional[pd.DataFrame]:
        """
        Fetch and return the IV surface for a symbol.

        Returns
        -------
        DataFrame with columns [strike, expiry, dte, call_iv, put_iv, mid_iv,
        moneyness], filtered to config moneyness and DTE ranges.
        Returns None if data is unavailable or fetch fails.
        """
        # In-memory cache check (avoid repeat fetches within one run)
        if symbol in CBOEFeed._SESSION_CACHE:
            return CBOEFeed._SESSION_CACHE[symbol]

        # Disk cache check
        cached = DataStore.load(f"cboe_{symbol}", "surface")
        if cached is not None:
            CBOEFeed._SESSION_CACHE[symbol] = cached
            return cached

        surface = CBOEFeed._fetch(symbol)
        CBOEFeed._SESSION_CACHE[symbol] = surface

        if surface is not None:
            DataStore.save(f"cboe_{symbol}", "surface", surface)
            log.info(f"CBOE surface fetched  {symbol}  →  {len(surface)} strikes")
        else:
            log.debug(f"CBOE surface unavailable  {symbol}")

        return surface

    @staticmethod
    def _fetch(symbol: str) -> Optional[pd.DataFrame]:
        """
        Hit the CBOE delayed quotes endpoint and parse the response.

        CBOE returns a JSON with a 'data' key containing 'options' —
        a list of option records each with: option (code), bid, ask,
        iv, delta, gamma, vega, theta, openInterest, volume.

        The option code encodes: symbol + expiry (YYMMDD) + C/P + strike*1000
        We parse this code to extract expiry, type, and strike.
        """
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
                dte = (expiry_date - datetime.utcnow().date()).days
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

            # Pivot to mid IV (average call + put IV per strike/expiry)
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

            # Apply moneyness and DTE filters from config
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
        """
        Parse a CBOE option code string into (expiry_date, type, strike).

        Standard OCC format: SYMBOL + YYMMDD + C/P + 8-digit strike (strike * 1000)
        Example: "AAPL251219C00250000"
            symbol  = AAPL
            expiry  = 25-12-19  →  2025-12-19
            type    = C
            strike  = 00250000 / 1000 = 250.0
        """
        try:
            # OCC format: variable-length symbol + 6-digit date + C/P + 8-digit strike
            # We locate the option type by finding the C or P that is immediately
            # preceded by a 6-digit date string (all digits) and followed by 8 digits.
            import re

            match = re.search(r"(\d{6})(C|P)(\d{8})", code)
            if not match:
                return None
            date_str = match.group(1)
            opt_type = match.group(2)
            strike_str = match.group(3)
            expiry = datetime.strptime(date_str, "%y%m%d").date()
            strike = int(strike_str) / 1000.0
            return expiry, opt_type, strike
        except Exception:
            return None


# =============================================================================
# CLASS 5 — UniverseBuilder
# Builds the full validated asset list and fetches all data.
# Returns a UniverseResult that every downstream module consumes.
# =============================================================================


class UniverseBuilder:
    """
    Constructs the full CAMARF asset universe and fetches historical data
    for every asset across all configured timeframes.

    Process:
        1. Fetch S&P 500 tickers dynamically from Wikipedia
        2. Append static alt-asset lists (crypto, forex, commodities, futures)
        3. Deduplicate across asset classes
        4. For each asset: fetch full history via IBKRFeed
        5. Apply QualityReport filter — exclude assets that fail
        6. Return UniverseResult

    The returned UniverseResult.data dict is the single source of truth
    for all downstream modules.  Keys are formatted as "SYMBOL_TFLABEL"
    e.g. "AAPL_1D", "BTC_1h".
    """

    def __init__(self):
        self._feed = IBKRFeed()

    def build(self, connect: bool = True) -> UniverseResult:
        """
        Full pipeline: build universe, fetch data, validate, return result.

        Parameters
        ----------
        connect : if True, establishes IBKR connection automatically.
                  Set False for testing with cached data only.
        """
        Config.ensure_dirs()

        if connect:
            success = self._feed.connect()
            if not success:
                raise RuntimeError("Cannot build universe — IBKR connection failed")

        log.info("Building asset universe...")

        # --- Step 1: construct full raw list ---
        raw_assets = self._build_raw_list()
        log.info(f"Universe candidates: {len(raw_assets)} assets")

        # --- Step 2: fetch data for each asset ---
        all_data: Dict[str, pd.DataFrame] = {}
        all_reports: List[QualityReport] = []
        passed: List[Tuple[str, str]] = []
        excluded: List[Tuple[str, str, str]] = []

        for i, (symbol, asset_class) in enumerate(raw_assets):
            log.info(f"[{i+1}/{len(raw_assets)}]  Fetching  {symbol}  ({asset_class})")

            tf_data = self._feed.get_full_history(symbol, asset_class)

            # Asset passes if at least the daily timeframe has valid data
            daily_df = tf_data.get("1D")
            if daily_df is None:
                excluded.append((symbol, asset_class, "no_daily_data"))
                log.warning(f"Excluded  {symbol}  →  no daily data")
                continue

            # Store all available timeframes
            asset_passed = False
            for tf_label, df in tf_data.items():
                if df is not None:
                    all_data[f"{symbol}_{tf_label}"] = df
                    asset_passed = True

            if asset_passed:
                passed.append((symbol, asset_class))
            else:
                excluded.append((symbol, asset_class, "all_timeframes_failed"))

        if connect:
            self._feed.disconnect()

        log.info(
            f"Universe complete: {len(passed)} assets passed, "
            f"{len(excluded)} excluded"
        )

        return UniverseResult(
            assets=passed,
            excluded=excluded,
            data=all_data,
            quality_reports=all_reports,
        )

    def _build_raw_list(self) -> List[Tuple[str, str]]:
        """
        Construct deduplicated (symbol, asset_class) list.

        S&P 500 pulled dynamically from Wikipedia.
        Alt assets from UniverseConfig static lists.
        """
        raw: List[Tuple[str, str]] = []
        seen: set = set()

        def add(symbol: str, asset_class: str):
            key = (symbol.upper(), asset_class)
            if key not in seen:
                seen.add(key)
                raw.append(key)

        # --- S&P 500 from Wikipedia ---
        sp500 = self._fetch_sp500_tickers()
        for ticker in sp500:
            add(ticker, "equity")

        # --- Alt assets ---
        for sym in Config.UNIVERSE.CRYPTO:
            add(sym, "crypto")
        for sym in Config.UNIVERSE.FOREX:
            add(sym, "forex")
        for sym in Config.UNIVERSE.COMMODITIES:
            add(sym, "commodity")
        for sym in Config.UNIVERSE.FUTURES:
            add(sym, "futures")

        return raw

    @staticmethod
    def _fetch_sp500_tickers() -> List[str]:
        """
        Fetch the current S&P 500 constituent list.

        Attempts three sources in order, falling back on each failure:
          1. Wikipedia (with browser User-Agent header to avoid 403)
          2. iShares IVV holdings CSV (State Street public data)
          3. Hardcoded top-50 fallback

        Wikipedia blocks plain urllib requests with a 403 — the User-Agent
        header makes the request appear as a normal browser visit.
        """
        # --- Source 1: Wikipedia with browser header ---
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
            sp500_table = tables[0]
            tickers = sp500_table["Symbol"].tolist()
            # Wikipedia uses periods for BRK.B — IBKR uses spaces: "BRK B"
            tickers = [str(t).replace(".", " ") for t in tickers]
            log.info(f"S&P 500: {len(tickers)} tickers from Wikipedia")
            return tickers
        except Exception as e:
            log.warning(f"Wikipedia S&P 500 failed: {e}")

        # --- Source 2: iShares IVV holdings (reliable, publicly accessible) ---
        try:
            url = (
                "https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf/"
                "1467271812596.ajax?fileType=csv&fileName=IVV_holdings&dataType=fund"
            )
            df = pd.read_csv(url, skiprows=9, header=0)
            tickers = df["Ticker"].dropna().tolist()
            tickers = [str(t).strip() for t in tickers if str(t).strip()]
            tickers = [
                t.replace(".", " ") for t in tickers if t not in ("", "nan", "-")
            ]
            if len(tickers) > 400:
                log.info(f"S&P 500: {len(tickers)} tickers from iShares IVV")
                return tickers
        except Exception as e:
            log.warning(f"iShares IVV fetch failed: {e}")

        # --- Source 3: hardcoded top-50 fallback ---
        log.warning("Using hardcoded S&P 500 fallback list (top 50 by market cap)")
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
# ENTRY POINT — run data.py directly to execute a full universe build
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

    # Print exclusion summary
    if result.excluded:
        log.info("\nExclusion summary:")
        for sym, cls, reason in result.excluded[:20]:
            log.info(f"  {sym:12s} ({cls:10s})  →  {reason}")
        if len(result.excluded) > 20:
            log.info(f"  ... and {len(result.excluded) - 20} more")
