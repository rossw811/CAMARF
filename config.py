# =============================================================================
# CAMARF — Cross-Asset Co-Movement Arbitrage Research Framework
# config.py — Central configuration: all parameters, universe lists, flags
# github.com/rossw811/CAMARF
# =============================================================================

from dataclasses import dataclass, field
from typing import List, Dict, Tuple
import os

# =============================================================================
# IBKR CONNECTION
# =============================================================================


class IBKRConfig:
    HOST = "127.0.0.1"
    PORT = 4001  # Gateway port (7497 for TWS paper)
    CLIENT_ID = 1  # data.py uses this
    CLIENT_ID_ANALYSIS = 2  # analysis.py uses this (avoids clash when both run)
    TIMEOUT = 30  # seconds
    READONLY = True  # data-only mode for research runs


# =============================================================================
# DATA CONFIGURATION
# =============================================================================


class DataConfig:
    # Output and cache directories
    OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
    CACHE_DIR = os.path.join(OUTPUT_DIR, "cache")
    REPORT_DIR = os.path.join(OUTPUT_DIR, "reports")

    # Timeframes to analyze (IBKR bar size strings)
    # 12 hours removed — not a valid IBKR bar size (confirmed via Error 321)
    # 1W and 1M use IBKR's exact format for weekly/monthly bars
    # Valid IBKR bar sizes confirmed: 1 min, 5 mins, 15 mins, 30 mins,
    #   1 hour, 4 hours, 1 day, 1W, 1M
    TIMEFRAMES: List[str] = [
        "1 min",
        "2 mins",
        "3 mins",
        "5 mins",
        "15 mins",
        "30 mins",
        "1 hour",
        "4 hours",
        "1 day",
        "1W",
        "1M",
    ]

    # Human-readable labels used throughout the analysis pipeline (14 TFs — superset
    # of IBKR's TIMEFRAMES; includes 7D/3M/6M which IBKR names differently or
    # doesn't expose as standalone bar sizes)
    TIMEFRAME_LABELS: List[str] = [
        "1m",
        "2m",
        "3m",
        "5m",
        "15m",
        "30m",
        "1h",
        "4h",
        "1D",
        "7D",
        "1M",
        "3M",
        "6M",
    ]

    # Historical depth per asset class — calibrated to actual IBKR account limits
    # Confirmed via diagnose.py on 2026-06-11:
    #   Daily equity (AAPL): 2006-06-16, depth = ~20 years confirmed
    #   Weekly/Monthly: ADJUSTED_LAST unsupported — data.py uses TRADES fallback
    #   Intraday: requires explicit endDateTime — handled in IBKRFeed.get_bars
    HISTORY_DEPTH: Dict[str, str] = {
        "equity": "20 Y",
        "crypto": "3 Y",
        "forex": "10 Y",
        "commodity": "20 Y",
        "futures": "20 Y",
    }

    # CBOE options surface data
    CBOE_DATA_DIR = os.path.join(CACHE_DIR, "cboe")
    CBOE_BASE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/"

    # Data quality filters
    # Minimum bar count per timeframe.
    # Equities: set to ~2 years of expected data depth per TF.
    # Futures/commodities: lower floor because front-month contracts
    # naturally have 300-400 bars of history — that is valid data.
    MIN_BARS_REQUIRED: Dict[str, int] = {
        # 1m/2m/3m fixed AGAIN 2026-06-22 (previous 2026-06-20 fix at
        # 1500/5000/500 was itself still miscalibrated — verified live, not
        # guessed). yfinance's period="5d" for 1m means 5 CALENDAR days,
        # not 5 trading days as the prior fix's comment assumed — when
        # fetched on a Monday/Tuesday, the weekend eats 2 of those days, so
        # the achievable ceiling is far below the naive "5 trading days *
        # 390 bars/day = 1950" estimate. Direct live test (2026-06-22):
        # ALGN (liquid) got 1169 raw 1m bars; ERIE (less liquid) got only
        # 383 — both genuinely fetched (HTTP 200, real OHLC data), both
        # silently rejected by the old 1500/500 thresholds with ZERO
        # exceptions raised, which is exactly why this looked like Yahoo-
        # side throttling from the run logs alone (96-100% "fail_fetch"
        # with no visible reason) until traced directly to
        # DataCleaner.clean()'s fail_reason. Same issue independently
        # confirmed for 2m (its own native yfinance interval, period=55d,
        # NOT derived from 1m): ALGN got 5343 bars (barely above the old
        # 5000 floor), ERIE got 2407 (well below it).
        #
        # New thresholds are calibrated to ALGN/ERIE's actual observed
        # counts with real margin, not a theoretical maximum: liquid names
        # comfortably pass at every TF; less-liquid names like ERIE are
        # intentionally excluded from 1m (383 bars is genuinely thin for
        # minute-bar statistical work) but DO qualify at 2m/3m, where the
        # same calendar window naturally yields proportionally more usable
        # bars. This is a deliberate liquidity-tier distinction, not an
        # oversight — see DEVELOPMENT.md Session 9 for the full trace.
        "1m": 900,  # below ALGN's 1169; above ERIE's 383 (excluded at 1m by design)
        "2m": 2200,  # below ERIE's 2407; ALGN's 5343 passes easily
        "3m": 300,  # below ERIE's 383 (included at 3m, unlike 1m)
        "5m": 2000,  # ~6 months of 5m bars
        "15m": 1000,  # ~6 months of 15m bars
        "30m": 500,  # ~6 months of 30m bars
        "1h": 500,  # ~1 year of hourly bars
        "4h": 200,  # ~2 years of 4h bars
        "1D": 100,  # lowered from 500 — futures front-month ~300 bars is valid
        "7D": 50,  # ~1 year of weekly bars
        "1M": 24,  # ~2 years of monthly bars
    }
    MAX_MISSING_PCT = 0.10  # drop asset if >10% bars are missing
    # 3.6% is normal for US equities due to market holidays
    # pandas 'B' frequency excludes weekends only, not holidays
    MIN_DOLLAR_VOLUME = 1_000_000  # minimum avg daily dollar volume (equity)
    YF_CHUNK_SIZE = 50  # tickers per yfinance batch download


# =============================================================================
# ASSET UNIVERSE
# =============================================================================


class UniverseConfig:
    # --- S&P 500 tickers loaded dynamically from Wikipedia in data.py ---
    # SP500_TICKERS populated at runtime

    # Crypto assets (IBKR supported)
    CRYPTO: List[str] = ["BTC", "ETH", "LTC", "BCH", "XRP"]

    # Forex pairs (IBKR format: base.quote)
    FOREX: List[str] = [
        "EUR.USD",
        "GBP.USD",
        "USD.JPY",
        "USD.CHF",
        "AUD.USD",
        "USD.CAD",
        "NZD.USD",
        "EUR.GBP",
        "EUR.JPY",
        "GBP.JPY",
    ]

    # Commodity futures (continuous contracts)
    COMMODITIES: List[str] = [
        "GC",  # Gold
        "SI",  # Silver
        "CL",  # Crude Oil WTI
        "NG",  # Natural Gas
        "ZC",  # Corn
        "ZW",  # Wheat
        "ZS",  # Soybeans
        "HG",  # Copper
    ]

    # Equity index futures (continuous)
    FUTURES: List[str] = [
        "ES",  # S&P 500
        "NQ",  # Nasdaq 100
        "RTY",  # Russell 2000
        "YM",  # Dow Jones
        "ZN",  # 10-Year T-Note
        "ZB",  # 30-Year T-Bond
        # GC and CL excluded here — already in COMMODITIES list
    ]

    # ETFs: included as individual assets for cross-instrument cointegration.
    # These provide exposure to index-level dynamics that equity pairs may not
    # capture individually. QQQ adds Nasdaq-100 exposure distinct from ES/NQ
    # futures; IWM (Russell 2000 ETF) adds small-cap factor exposure; SPY
    # tracks S&P 500 alongside ES futures — the SPY↔ES relationship is itself
    # a cointegration finding (futures basis/roll dynamics).
    # Note: BRK.B is already in S&P 500 constituent list (no need to add).
    # VOO = S&P 500 ETF — its holdings are identical to SP500_TICKERS, but
    # VOO as an INSTRUMENT may trade at a premium/discount to NAV.
    ETFS: List[str] = [
        "QQQ",  # Invesco QQQ — Nasdaq-100 ETF
        "IWM",  # iShares Russell 2000 ETF
        "SPY",  # SPDR S&P 500 ETF
        "VOO",  # Vanguard S&P 500 ETF
        "GLD",  # SPDR Gold Shares (ETF proxy for GC futures)
        "SLV",  # iShares Silver Trust (ETF proxy for SI futures)
        "USO",  # United States Oil Fund (ETF proxy for CL futures)
    ]

    # -----------------------------------------------------------------------
    # S&P Composite 1500 = S&P 500 + MidCap 400 + SmallCap 600
    # All quality-screened; ~1536 total with non-equities.
    # Overnight compute: 12-18 hours at 12 workers.
    # -----------------------------------------------------------------------
    INCLUDE_MIDCAP400: bool = True
    INCLUDE_SMALLCAP600: bool = True
    # Nasdaq-100 extras: ~10-15 stocks in QQQ but not any S&P index
    INCLUDE_QQQ_EXTRAS: bool = True
    # Berkshire Hathaway 13F holdings (mostly already in S&P 500)
    INCLUDE_BRK_HOLDINGS: bool = True
    # Russell 2000: disabled by default (add later if compute allows)
    RUSSELL_TOP_N: int = 0  # 0=disabled, -1=all, N=top-N

    # Pre-filter thresholds (applied before any cointegration test)
    MIN_PEARSON_CORR = 0.40  # minimum absolute correlation to proceed
    # 0.40 surfaces equity pairs (0.60 was too
    # restrictive — filtered all equities at daily)
    MIN_ADF_PVALUE = 0.10  # spread must show ADF p < 0.10 to proceed
    MAX_HALF_LIFE_DAYS = 90  # OU half-life ceiling — beyond this, not tradeable
    MIN_HALF_LIFE_DAYS = 1  # OU half-life floor — below this, too noisy

    # Episodic-cointegration defense (post-EG, applied in analysis.py's
    # coint_frac filter). Documented design has always said 0.70; this
    # constant didn't actually exist here, so the filter silently ran on
    # its getattr(..., 0.40) fallback instead — a deliberate stopgap from
    # when 0.70 filtered out everything before BUG-D42/D45 were fixed, never
    # reconciled with the doc afterward (caught by the improve-skill audit,
    # 2026-06-22). Restored to the documented 0.70 now that real sensitivity
    # data shows it's achievable: 11/14 confirmed pairs already clear it
    # (the other 3 are NaN — exempt from this filter by design, not affected
    # by this value either way). Only D/NEE (0.41) and SPY/VOO (0.45) drop.
    MIN_COINT_FRAC = 0.70


# =============================================================================
# CO-MOVEMENT ANALYSIS
# =============================================================================


class AnalysisConfig:
    # Engle-Granger cointegration
    EG_MAX_LAG = 10  # max lag for ADF test on residuals
    EG_SIGNIFICANCE = 0.05  # p-value threshold

    # Johansen cointegration (trios)
    JOHANSEN_DET_ORDER = -1  # -1 = no deterministic terms
    JOHANSEN_K_AR_DIFF = 1  # lag order
    JOHANSEN_SIGNIFICANCE = 0.05

    # Ornstein-Uhlenbeck spread model
    OU_LOOKBACK_DAYS = 252  # ceiling on the rolling window (bars), used when
    # half-life is NaN/degenerate; otherwise the window adapts per pair, see
    # OU_WINDOW_HALFLIFE_MULT_MEAN below.
    OU_ZSCORE_ENTRY = 2.0  # z-score threshold to flag divergence event
    OU_ZSCORE_EXIT = 0.5  # z-score threshold for mean reversion target

    # Adaptive rolling-window sizing for z-score/half-life (replaces a single
    # fixed bar count applied uniformly across all TFs and pairs): window ~=
    # OU_WINDOW_HALFLIFE_MULT_MEAN x half-life, spanning several reversion
    # cycles for a stable mean/std estimate. Mean and std deliberately use
    # the SAME window (tested decoupling a shorter vol-only window — biased
    # the z-score on real data instead of helping, see SpreadModel.fit_pair's
    # docstring / DEVELOPMENT.md BUG-D45). A separate volatility-regime
    # diagnostic (short/long vol ratio, same convention as relative_vol_ratio
    # below) is a candidate future feature, not wired into this z-score.
    OU_WINDOW_HALFLIFE_MULT_MEAN = 8  # window ~= 8x half-life
    OU_WINDOW_MIN_BARS = 30  # floor — below this, the estimate is too noisy

    # Trio construction (derivative method)
    # A↔B confirmed + B↔C confirmed → test A↔B↔C
    TRIO_MIN_PAIR_SHARPE = 1.0  # both constituent pairs must exceed this
    TRIO_MAX_CANDIDATES = 500  # cap trio candidates for compute reasons

    # Volatility framework
    VOL_LOOKBACK_SHORT = 20  # short-term vol window (bars)
    VOL_LOOKBACK_LONG = 252  # long-term vol window (bars, ~1yr daily)
    VOL_RELATIVE_THRESHOLD = 1.5  # flag if current vol > 1.5x long-term mean

    # Regime classification
    N_REGIMES = 4  # k-means / HMM states
    REGIME_FEATURES = [  # features used to define regimes
        "realized_vol",
        "trend_strength",
        "mean_reversion_speed",
        "spread_vol",
    ]


# =============================================================================
# MACHINE LEARNING
# =============================================================================


class MLConfig:
    # Target variable definition
    # Spread "resolves" if it returns to within RESOLUTION_THRESHOLD * sigma
    # of the mean within RESOLUTION_BARS bars (bars derived from OU half-life)
    RESOLUTION_THRESHOLD = 0.5  # fraction of sigma for resolution
    RESOLUTION_BARS_MULT = 2.0  # max bars = MULT * OU half-life

    # Multiclass labels — at horizon N = RESOLUTION_BARS_MULT * half_life bars
    # ahead of entry, classify by where |z-score| lands (see ml.py's
    # _classify_outcome() for the exact priority-ordered rule; these
    # comments previously described a different, never-implemented
    # time-to-resolve scheme — corrected 2026-06-21 to match the definition
    # actually locked in DEVELOPMENT.md's ml.py section).
    CLASS_LABELS = [
        "strong_converge",  # |z_future| <= RESOLUTION_THRESHOLD (0.5)
        "weak_converge",  # RESOLUTION_THRESHOLD < |z_future| <= 1.0
        "no_move",  # 1.0 < |z_future| < |z_entry| (improved, not enough)
        "diverge_further",  # |z_future| >= |z_entry| (no improvement at all)
    ]

    # Label scheme actually used for class-count checks and training (2026-06-22,
    # decided given the current data-scarcity bottleneck). "binary" collapses
    # the 4 granular CLASS_LABELS above down to 2 (converged vs not) so the
    # MIN_CLASS_SAMPLES gate needs less data to clear; the granular label is
    # still stored on every EntryEvent regardless, so nothing is lost — this
    # only changes what the model trains on, not what gets recorded. Switch
    # back to "4class" once there's enough volume. Deliberately NOT the same
    # decision as switching to Lopez de Prado's triple-barrier method (a
    # different labeling MECHANISM, not just a different class count,
    # already noted elsewhere in Development.md as a stronger but bigger
    # methodology change) — that stays a separate, dedicated discussion.
    LABEL_SCHEME = "binary"  # "binary" | "4class"
    BINARY_LABEL_MAP = {
        "strong_converge": "converged",
        "weak_converge": "converged",
        "no_move": "not_converged",
        "diverge_further": "not_converged",
    }

    # Entry threshold used ONLY for generating ml.py training examples —
    # deliberately separate from Config.ANALYSIS.OU_ZSCORE_ENTRY (2.0), which
    # remains the live/production entry signal. Lower here on purpose so the
    # meta-labeler sees a broader range of divergence outcomes while data is
    # scarce (standard Lopez de Prado meta-labeling practice: train broader
    # than you trade). Revisit this value once there's enough volume to
    # afford training only on the live threshold's own examples.
    TRAINING_ENTRY_THRESHOLD = 1.5

    # Feature engineering
    RSI_PERIOD = 14
    ATR_PERIOD = 14
    BBANDS_PERIOD = 20
    BBANDS_STD = 2.0
    VOLUME_SMA_PERIOD = 20
    MOMENTUM_PERIOD = 10
    STOCH_PERIOD = 14

    # Inter-indicator correlation filter
    # Features with pairwise correlation > threshold are treated as redundant
    INDICATOR_CORR_THRESHOLD = 0.85

    # Cross-asset divergence features
    # Built for each confirmed pair: diff of indicator values between leg A and leg B
    DIVERGENCE_INDICATORS = ["rsi", "momentum", "atr_ratio", "vol_ratio"]

    # Model configuration
    RF_N_ESTIMATORS = 500
    RF_MAX_DEPTH = 6
    RF_MIN_SAMPLES_LEAF = 20
    GBM_N_ESTIMATORS = 500
    GBM_LEARNING_RATE = 0.05
    GBM_MAX_DEPTH = 4

    # Train / validation / test split (no overlap, time-ordered)
    TRAIN_PCT = 0.60
    VAL_PCT = 0.20
    TEST_PCT = 0.20

    # Minimum class count to train (skip pair if any class has fewer samples)
    MIN_CLASS_SAMPLES = 30


# =============================================================================
# BACKTEST
# =============================================================================


class BacktestConfig:
    # Account sizes to test
    ACCOUNT_SIZES: List[float] = [10_000, 100_000, 1_000_000]

    # Position sizing methods
    SIZING_METHODS: List[str] = ["flat_2pct", "half_kelly", "full_kelly"]

    # Flat risk: risk_pct * account / (entry - stop)
    FLAT_RISK_PCT = 0.02

    # Direction testing
    TEST_LONG = True
    TEST_SHORT = True
    TEST_COMBINED = True  # long + short simultaneously

    # Commission and slippage model
    COMMISSION_PER_SHARE = 0.005  # USD per share
    SLIPPAGE_BPS = 5  # basis points per side

    # Coarse-to-fine grid search — Phase 1 (coarse)
    COARSE_ENTRY_ZSCORE = [1.5, 2.0, 2.5, 3.0]
    COARSE_EXIT_ZSCORE = [0.0, 0.25, 0.5, 0.75]
    COARSE_STOP_ZSCORE = [3.0, 3.5, 4.0, 4.5]
    COARSE_TRAIL_PCT = [0.01, 0.02, 0.05]

    # Phase 2 (fine) — populated programmatically around best coarse region
    FINE_GRID_STEPS = 5  # steps per dimension in fine search
    FINE_GRID_RADIUS = 0.25  # ± radius around coarse optimum

    # Primary optimization target for combinatoric search
    OPTIMIZE_TARGET = "profit_factor"

    # Secondary metrics to record (not optimized, but reported)
    SECONDARY_METRICS = [
        "sharpe",
        "sortino",
        "calmar",
        "max_drawdown",
        "win_rate",
        "total_pnl",
        "cagr",
        "omega",
    ]

    # Walk-forward analysis
    WFA_N_WINDOWS = 10
    WFA_TRAIN_PCT = 0.70
    WFA_TEST_PCT = 0.30

    # Circuit breakers (applied during backtest simulation)
    DAILY_LOSS_LIMIT_PCT = 0.03  # halt day if drawdown > 3% of account
    CONSECUTIVE_LOSS_LIMIT = 5  # halt if 5 consecutive losses


# =============================================================================
# OPTIONS
# =============================================================================


class OptionsConfig:
    # IV surface interpolation
    IV_INTERPOLATION_METHOD = "cubic"  # scipy interpolation method
    IV_SURFACE_MONEYNESS_RANGE = (0.80, 1.20)  # OTM/ITM range to include
    IV_SURFACE_EXPIRY_RANGE = (7, 90)  # DTE range to include (days)

    # IV spread signal
    # For a confirmed cointegrated pair, flag if IV differential exceeds threshold
    IV_SPREAD_ZSCORE_THRESHOLD = 1.5
    IV_LOOKBACK_DAYS = 60  # rolling window for IV spread z-score


# =============================================================================
# STATISTICAL VALIDATION
# =============================================================================


class StatsConfig:
    # Monte Carlo
    MC_N_SIMULATIONS = 10_000
    MC_BLOCK_SIZE = 20  # bars per block for block bootstrap
    MC_STUDENT_T_DF = 5  # degrees of freedom for Student-t

    # Drawdown at risk
    DAR_CONFIDENCE = [0.95, 0.99]

    # PSR / Deflated Sharpe
    PSR_BENCHMARK_SHARPE = 0.0  # null hypothesis Sharpe
    MIN_TRACK_RECORD_ALPHA = 0.05  # significance level for MTL test

    # PBO
    PBO_N_PARTITIONS = 16  # combinatorial cross-validation partitions

    # Multiple comparison correction
    FDR_ALPHA = 0.05  # Benjamini-Hochberg FDR threshold

    # KS test
    KS_ALPHA = 0.05

    # PCA
    PCA_VARIANCE_EXPLAINED = 0.95  # keep components explaining 95% of variance


# =============================================================================
# MACRO REGIME CONTEXT
# =============================================================================


class MacroConfig:
    # FRED series fetched, split by native release frequency. Daily series
    # are reindexed/ffilled onto the NYSE calendar as-is; monthly series get
    # the same treatment plus a *_days_stale column (see macro.py) since a
    # monthly print held flat for ~21 trading days is expected, not a gap.
    #
    # BAA10Y is a deliberate addition beyond the original spec's 7 series:
    # BAMLH0A0HYM2 (the spec's HY-IG credit spread) is capped to a ~3yr
    # rolling window by FRED's keyless CSV endpoint (confirmed via repeated
    # live probes with explicit date-range params — looks like an ICE
    # data-licensing restriction on the public route specifically, not a
    # bug). BAA10Y (Moody's Baa corporate yield minus 10Y Treasury) has full
    # history since 1986 with no such restriction, but is a DIFFERENT
    # metric — investment-grade corporate-Treasury spread, not a high-yield
    # option-adjusted spread — so it is fetched and classified as its own
    # `credit_regime_proxy` column, never merged into or treated as
    # interchangeable with the primary `credit_regime`. See
    # CREDIT_PROXY_TIGHT_PCT/CREDIT_PROXY_WIDE_PCT below for its
    # independently-calibrated thresholds.
    #
    # DTWEXBGS (Fed broad trade-weighted dollar index), DFII10 (10Y TIPS
    # real yield), and T10YIE (10Y breakeven inflation) are a second
    # deliberate addition (2026-06-21), beyond the original 7-series spec —
    # full breadth per Ross's direction. All three confirmed via live probe
    # to need no API key and carry no licensing restriction (unlike
    # BAMLH0A0HYM2). DTWEXBGS only starts 2006 (the broad index wasn't
    # compiled before then — the older "major currencies" DTWEXM series
    # runs 1973-2019 but is discontinued; not added here, same
    # proxy-extension option as BAA10Y if deeper dollar history is wanted
    # later). DFII10/T10YIE start 2003 (TIPS market maturity).
    #
    # UNRATE feeds the derived Sahm Rule recession signal (see macro.py
    # build()) — a real-time complement to USREC's NBER-lagged call.
    FRED_SERIES_DAILY: List[str] = [
        "T10Y2Y",
        "BAMLH0A0HYM2",
        "VIXCLS",
        "VXVCLS",   # CBOE VXV — 3-month implied vol; VXV/VIX ratio = term structure
        "DCOILWTICO",
        "BAA10Y",
        "DTWEXBGS",
        "DFII10",
        "T10YIE",
    ]
    FRED_SERIES_MONTHLY: List[str] = ["FEDFUNDS", "CPIAUCSL", "USREC", "UNRATE"]

    # Public, keyless CSV endpoint — confirmed via live probe (2026-06-21) to
    # need no API key/account. Missing observations come back as an empty
    # field (e.g. bond-market holidays); a few older FRED series have used a
    # literal "." for the same purpose — macro.py's parser handles both.
    FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"

    FETCH_RETRY_ATTEMPTS = 3
    FETCH_RETRY_DELAY_SEC = 5
    CACHE_MAX_AGE_HOURS = 20.0  # re-fetch at most once per day

    # 1986-01-02 matches BAA10Y's/DCOILWTICO's actual start — extended back
    # from VIXCLS's 1990-01-02 start specifically so BAA10Y's full history
    # (the reason it was added) actually gets used, including 1987 Black
    # Monday. vix_close/vix_regime/credit_regime correctly show NaN before
    # their own series' real start (1990 / ~2023 respectively) rather than
    # a fabricated value — that's the leading-NaN guard working as intended,
    # not a regression.
    MIN_HISTORY_START = "1986-01-02"

    # Regime thresholds — DEVELOPMENT.md "Planned: FRED Macro Regime Context".
    # T10Y2Y and VIXCLS are published by FRED in the same units the spec used
    # (percentage points / index points) — no conversion needed.
    YIELD_CURVE_STEEP = 1.5  # T10Y2Y > 1.5  -> steep
    YIELD_CURVE_INVERTED = 0.0  # T10Y2Y < 0.0  -> flat_inverted

    # BAMLH0A0HYM2 is published by FRED in PERCENT (e.g. 4.15 = 4.15% =
    # 415bp), not basis points — confirmed via live probe. The original
    # 300bp/500bp spec is expressed here in percent to match the raw series.
    CREDIT_TIGHT_PCT = 3.0  # BAMLH0A0HYM2 < 3.0% (300bp) -> tight
    CREDIT_WIDE_PCT = 5.0  # > 5.0% (500bp) -> wide

    # BAA10Y proxy thresholds — independently calibrated against real BAA10Y
    # history (live-probed 2026-06-21), NOT a unit conversion of the
    # BAMLH0A0HYM2 thresholds above (different instrument, different scale:
    # BAA10Y troughs ~1.5% in calm markets and peaked at 6.16% in the 2008
    # GFC vs. BAMLH0A0HYM2's much wider high-yield range).
    # Calibration points: calm 2006 ~1.6%, calm 2026 ~1.5%; 1987 Black
    # Monday ~2.7%, 1998 LTCM ~2.8% (equity/liquidity shocks, mild on this
    # IG-credit measure); 2011 US downgrade/Eurozone ~3.4%, 2015-16 oil
    # crash ~3.6% (genuine credit-stress episodes); 2020 COVID ~4.3%, 2008
    # GFC ~6.2% (systemic crises).
    CREDIT_PROXY_TIGHT_PCT = 2.0  # BAA10Y < 2.0% -> tight
    CREDIT_PROXY_WIDE_PCT = 3.0  # BAA10Y >= 3.0% -> wide (captures 2011/2015-16/2020/2008)

    VIX_CALM = 15.0
    VIX_NORMAL_HI = 25.0
    VIX_ELEVATED_HI = 35.0  # > 35 -> crisis

    # VIX term structure (VXV/VIX ratio): VXV = 3-month implied vol (VXVCLS
    # on FRED). Ratio > 1.0 = contango (normal; market pricing in FUTURE
    # uncertainty higher than current). Ratio < 1.0 = backwardation/inverted
    # (crisis; current fear higher than expected future). Thresholds calibrated
    # against VXV history (FRED VXVCLS starts 2007-12-04):
    #   Deep contango (ratio >= 1.10): calm/complacent regime
    #   Normal contango (1.00 <= ratio < 1.10): standard risk-on
    #   Flat (~0.95-1.00): transitional/uncertain
    #   Backwardation (< 0.95): stress/crisis episode
    VIX_TS_BACKWARDATION = 0.95   # VXV/VIX < 0.95 -> backwardation (stress)
    VIX_TS_FLAT_HI = 1.00         # 0.95-1.00 -> flat
    VIX_TS_CONTANGO_HI = 1.10     # 1.00-1.10 -> contango; >= 1.10 -> deep_contango

    # CFTC COT net-speculative-position thresholds: net = (long - short) / OI.
    # Positive = net long speculators, negative = net short. Thresholds are
    # symmetric around zero with a neutral band. Calibrated to ES futures
    # historical extremes: crowded long peaks ~25-30% net, crowded short troughs
    # ~-15 to -20% during 2018/2022 selloffs.
    COT_NET_LONG_THRESHOLD = 0.15   # >= 15% net long -> crowded_long (crowding risk)
    COT_NET_SHORT_THRESHOLD = -0.10  # <= -10% net short -> crowded_short

    # Sahm Rule (Claudia Sahm, Fed/Brookings) — real-time recession-risk
    # signal: triggers when the 3-month moving average of UNRATE rises this
    # many points above its own trailing-12-month low. Standard published
    # trigger value; not a CAMARF-specific calibration.
    SAHM_TRIGGER = 0.50

    # Rolling-percentile regime classification window for series whose
    # "normal" level drifts structurally over a multi-year horizon (dollar
    # index, real yields, breakeven inflation) — an absolute-level
    # threshold (like VIX's) would misclassify across different eras (e.g.
    # post-2008 ZIRP vs. now for real yields). 504 trading days = ~2yr
    # trailing reference window; MIN_PERIODS = 1yr so classification starts
    # after 1yr of history rather than waiting the full 2yr window.
    RELATIVE_LEVEL_WINDOW = 504
    RELATIVE_LEVEL_MIN_PERIODS = 252
    RELATIVE_LEVEL_LOW_PCTILE = 0.25
    RELATIVE_LEVEL_HIGH_PCTILE = 0.75


# =============================================================================
# REPORT
# =============================================================================


class ReportConfig:
    TITLE = "Cross-Asset Co-Movement Arbitrage Research Framework"
    SUBTITLE = (
        "Multi-Asset Statistical Co-Movement Detection, "
        "ML-Based Signal Discovery, and Institutional-Grade Validation"
    )
    AUTHOR = "Ross W."
    INSTITUTION = "Washington State University"
    VERSION = "1.0.0"

    # Page layout
    PAGE_WIDTH_IN = 8.5
    PAGE_HEIGHT_IN = 11.0
    MARGIN_IN = 1.0
    DPI = 150

    # Color palette (institutional)
    COLOR_PRIMARY = "#1B2A4A"  # deep navy
    COLOR_SECONDARY = "#2E6DA4"  # medium blue
    COLOR_ACCENT = "#C8A951"  # gold
    COLOR_POSITIVE = "#2E7D32"  # green
    COLOR_NEGATIVE = "#C62828"  # red
    COLOR_NEUTRAL = "#546E7A"  # slate

    OUTPUT_FILENAME = "CAMARF_Research_Report_v1.0.0.pdf"


# =============================================================================
# MASTER CONFIG — single import point for all modules
# =============================================================================


class Config:
    IBKR = IBKRConfig
    DATA = DataConfig
    UNIVERSE = UniverseConfig
    ANALYSIS = AnalysisConfig
    ML = MLConfig
    BACKTEST = BacktestConfig
    OPTIONS = OptionsConfig
    STATS = StatsConfig
    REPORT = ReportConfig
    MACRO = MacroConfig

    @staticmethod
    def ensure_dirs():
        """Create all required output directories if they don't exist."""
        for path in [
            DataConfig.OUTPUT_DIR,
            DataConfig.CACHE_DIR,
            DataConfig.REPORT_DIR,
            DataConfig.CBOE_DATA_DIR,
        ]:
            os.makedirs(path, exist_ok=True)
