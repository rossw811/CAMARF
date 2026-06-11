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
    HOST                    = "127.0.0.1"
    PORT                    = 4001              # Gateway port (7497 for TWS paper)
    CLIENT_ID               = 1
    TIMEOUT                 = 30                # seconds
    READONLY                = True              # data-only mode for research runs


# =============================================================================
# DATA CONFIGURATION
# =============================================================================

class DataConfig:
    # Output and cache directories
    OUTPUT_DIR              = os.path.join(os.path.dirname(__file__), "output")
    CACHE_DIR               = os.path.join(OUTPUT_DIR, "cache")
    REPORT_DIR              = os.path.join(OUTPUT_DIR, "reports")

    # Timeframes to analyze (IBKR bar size strings)
    TIMEFRAMES: List[str]   = [
        "1 min",
        "5 mins",
        "15 mins",
        "30 mins",
        "1 hour",
        "4 hours",
        "8 hours",
        "12 hours",
        "1 day",
        "1 week",
        "1 month",
    ]

    # Human-readable labels aligned to TIMEFRAMES list
    TIMEFRAME_LABELS: List[str] = [
        "1m", "5m", "15m", "30m", "1h", "4h", "8h", "12h", "1D", "7D", "1M"
    ]

    # Maximum historical depth to request per asset class (IBKR duration strings)
    # IBKR enforces per-asset limits — data.py handles graceful fallback
    HISTORY_DEPTH: Dict[str, str] = {
        "equity":       "20 Y",
        "crypto":       "5 Y",
        "forex":        "20 Y",
        "commodity":    "20 Y",
        "futures":      "20 Y",
    }

    # CBOE options surface data
    CBOE_DATA_DIR           = os.path.join(CACHE_DIR, "cboe")
    CBOE_BASE_URL           = "https://cdn.cboe.com/api/global/delayed_quotes/options/"

    # Data quality filters
    MIN_BARS_REQUIRED       = 500               # minimum bar count to include an asset
    MAX_MISSING_PCT         = 0.02              # drop asset if >2% bars are missing
    MIN_DOLLAR_VOLUME       = 1_000_000         # minimum avg daily dollar volume (equity)


# =============================================================================
# ASSET UNIVERSE
# =============================================================================

class UniverseConfig:
    # --- S&P 500 tickers loaded dynamically from Wikipedia in data.py ---
    # SP500_TICKERS populated at runtime

    # Crypto assets (IBKR supported)
    CRYPTO: List[str]       = [
        "BTC", "ETH", "LTC", "BCH", "XRP"
    ]

    # Forex pairs (IBKR format: base.quote)
    FOREX: List[str]        = [
        "EUR.USD", "GBP.USD", "USD.JPY", "USD.CHF",
        "AUD.USD", "USD.CAD", "NZD.USD", "EUR.GBP",
        "EUR.JPY", "GBP.JPY",
    ]

    # Commodity futures (continuous contracts)
    COMMODITIES: List[str]  = [
        "GC",   # Gold
        "SI",   # Silver
        "CL",   # Crude Oil WTI
        "NG",   # Natural Gas
        "ZC",   # Corn
        "ZW",   # Wheat
        "ZS",   # Soybeans
        "HG",   # Copper
    ]

    # Equity index futures (continuous)
    FUTURES: List[str]      = [
        "ES",   # S&P 500
        "NQ",   # Nasdaq 100
        "RTY",  # Russell 2000
        "YM",   # Dow Jones
        "GC",   # Gold (also commodity — deduped at runtime)
        "CL",   # Crude Oil
        "ZN",   # 10-Year T-Note
        "ZB",   # 30-Year T-Bond
    ]

    # Pre-filter thresholds (applied before any cointegration test)
    MIN_PEARSON_CORR        = 0.60              # minimum absolute correlation to proceed
    MIN_ADF_PVALUE          = 0.10              # spread must show ADF p < 0.10 to proceed
    MAX_HALF_LIFE_DAYS      = 90                # OU half-life ceiling — beyond this, not tradeable
    MIN_HALF_LIFE_DAYS      = 1                 # OU half-life floor — below this, too noisy


# =============================================================================
# CO-MOVEMENT ANALYSIS
# =============================================================================

class AnalysisConfig:
    # Engle-Granger cointegration
    EG_MAX_LAG              = 10                # max lag for ADF test on residuals
    EG_SIGNIFICANCE         = 0.05              # p-value threshold

    # Johansen cointegration (trios)
    JOHANSEN_DET_ORDER      = -1                # -1 = no deterministic terms
    JOHANSEN_K_AR_DIFF      = 1                 # lag order
    JOHANSEN_SIGNIFICANCE   = 0.05

    # Ornstein-Uhlenbeck spread model
    OU_LOOKBACK_DAYS        = 252               # rolling window for OU parameter estimation
    OU_ZSCORE_ENTRY         = 2.0               # z-score threshold to flag divergence event
    OU_ZSCORE_EXIT          = 0.5               # z-score threshold for mean reversion target

    # Trio construction (derivative method)
    # A↔B confirmed + B↔C confirmed → test A↔B↔C
    TRIO_MIN_PAIR_SHARPE    = 1.0               # both constituent pairs must exceed this
    TRIO_MAX_CANDIDATES     = 500               # cap trio candidates for compute reasons

    # Volatility framework
    VOL_LOOKBACK_SHORT      = 20                # short-term vol window (bars)
    VOL_LOOKBACK_LONG       = 252               # long-term vol window (bars, ~1yr daily)
    VOL_RELATIVE_THRESHOLD  = 1.5               # flag if current vol > 1.5x long-term mean

    # Regime classification
    N_REGIMES               = 4                 # k-means / HMM states
    REGIME_FEATURES         = [                 # features used to define regimes
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
    RESOLUTION_THRESHOLD    = 0.5               # fraction of sigma for resolution
    RESOLUTION_BARS_MULT    = 2.0               # max bars = MULT * OU half-life

    # Multiclass labels
    CLASS_LABELS            = [
        "strong_converge",      # spread resolves within 0.5 * half-life
        "weak_converge",        # spread resolves within 1.0 * half-life
        "no_move",              # spread does not resolve within 2.0 * half-life
        "diverge_further",      # spread widens beyond 3.0 sigma
    ]

    # Feature engineering
    RSI_PERIOD              = 14
    ATR_PERIOD              = 14
    BBANDS_PERIOD           = 20
    BBANDS_STD              = 2.0
    VOLUME_SMA_PERIOD       = 20
    MOMENTUM_PERIOD         = 10
    STOCH_PERIOD            = 14

    # Inter-indicator correlation filter
    # Features with pairwise correlation > threshold are treated as redundant
    INDICATOR_CORR_THRESHOLD = 0.85

    # Cross-asset divergence features
    # Built for each confirmed pair: diff of indicator values between leg A and leg B
    DIVERGENCE_INDICATORS   = ["rsi", "momentum", "atr_ratio", "vol_ratio"]

    # Model configuration
    RF_N_ESTIMATORS         = 500
    RF_MAX_DEPTH            = 6
    RF_MIN_SAMPLES_LEAF     = 20
    GBM_N_ESTIMATORS        = 500
    GBM_LEARNING_RATE       = 0.05
    GBM_MAX_DEPTH           = 4

    # Train / validation / test split (no overlap, time-ordered)
    TRAIN_PCT               = 0.60
    VAL_PCT                 = 0.20
    TEST_PCT                = 0.20

    # Minimum class count to train (skip pair if any class has fewer samples)
    MIN_CLASS_SAMPLES       = 30


# =============================================================================
# BACKTEST
# =============================================================================

class BacktestConfig:
    # Account sizes to test
    ACCOUNT_SIZES: List[float]  = [10_000, 100_000, 1_000_000]

    # Position sizing methods
    SIZING_METHODS: List[str]   = ["flat_2pct", "half_kelly", "full_kelly"]

    # Flat risk: risk_pct * account / (entry - stop)
    FLAT_RISK_PCT               = 0.02

    # Direction testing
    TEST_LONG                   = True
    TEST_SHORT                  = True
    TEST_COMBINED               = True          # long + short simultaneously

    # Commission and slippage model
    COMMISSION_PER_SHARE        = 0.005         # USD per share
    SLIPPAGE_BPS                = 5             # basis points per side

    # Coarse-to-fine grid search — Phase 1 (coarse)
    COARSE_ENTRY_ZSCORE         = [1.5, 2.0, 2.5, 3.0]
    COARSE_EXIT_ZSCORE          = [0.0, 0.25, 0.5, 0.75]
    COARSE_STOP_ZSCORE          = [3.0, 3.5, 4.0, 4.5]
    COARSE_TRAIL_PCT            = [0.01, 0.02, 0.05]

    # Phase 2 (fine) — populated programmatically around best coarse region
    FINE_GRID_STEPS             = 5             # steps per dimension in fine search
    FINE_GRID_RADIUS            = 0.25          # ± radius around coarse optimum

    # Primary optimization target for combinatoric search
    OPTIMIZE_TARGET             = "profit_factor"

    # Secondary metrics to record (not optimized, but reported)
    SECONDARY_METRICS           = [
        "sharpe", "sortino", "calmar", "max_drawdown",
        "win_rate", "total_pnl", "cagr", "omega"
    ]

    # Walk-forward analysis
    WFA_N_WINDOWS               = 10
    WFA_TRAIN_PCT               = 0.70
    WFA_TEST_PCT                = 0.30

    # Circuit breakers (applied during backtest simulation)
    DAILY_LOSS_LIMIT_PCT        = 0.03          # halt day if drawdown > 3% of account
    CONSECUTIVE_LOSS_LIMIT      = 5             # halt if 5 consecutive losses


# =============================================================================
# OPTIONS
# =============================================================================

class OptionsConfig:
    # IV surface interpolation
    IV_INTERPOLATION_METHOD     = "cubic"       # scipy interpolation method
    IV_SURFACE_MONEYNESS_RANGE  = (0.80, 1.20)  # OTM/ITM range to include
    IV_SURFACE_EXPIRY_RANGE     = (7, 90)       # DTE range to include (days)

    # IV spread signal
    # For a confirmed cointegrated pair, flag if IV differential exceeds threshold
    IV_SPREAD_ZSCORE_THRESHOLD  = 1.5
    IV_LOOKBACK_DAYS            = 60            # rolling window for IV spread z-score


# =============================================================================
# STATISTICAL VALIDATION
# =============================================================================

class StatsConfig:
    # Monte Carlo
    MC_N_SIMULATIONS            = 10_000
    MC_BLOCK_SIZE               = 20            # bars per block for block bootstrap
    MC_STUDENT_T_DF             = 5             # degrees of freedom for Student-t

    # Drawdown at risk
    DAR_CONFIDENCE              = [0.95, 0.99]

    # PSR / Deflated Sharpe
    PSR_BENCHMARK_SHARPE        = 0.0           # null hypothesis Sharpe
    MIN_TRACK_RECORD_ALPHA      = 0.05          # significance level for MTL test

    # PBO
    PBO_N_PARTITIONS            = 16            # combinatorial cross-validation partitions

    # Multiple comparison correction
    FDR_ALPHA                   = 0.05          # Benjamini-Hochberg FDR threshold

    # KS test
    KS_ALPHA                    = 0.05

    # PCA
    PCA_VARIANCE_EXPLAINED      = 0.95          # keep components explaining 95% of variance


# =============================================================================
# REPORT
# =============================================================================

class ReportConfig:
    TITLE                       = "Cross-Asset Co-Movement Arbitrage Research Framework"
    SUBTITLE                    = "Multi-Asset Statistical Co-Movement Detection, "\
                                  "ML-Based Signal Discovery, and Institutional-Grade Validation"
    AUTHOR                      = "Ross W."
    INSTITUTION                 = "Washington State University"
    VERSION                     = "1.0.0"

    # Page layout
    PAGE_WIDTH_IN               = 8.5
    PAGE_HEIGHT_IN              = 11.0
    MARGIN_IN                   = 1.0
    DPI                         = 150

    # Color palette (institutional)
    COLOR_PRIMARY               = "#1B2A4A"     # deep navy
    COLOR_SECONDARY             = "#2E6DA4"     # medium blue
    COLOR_ACCENT                = "#C8A951"     # gold
    COLOR_POSITIVE              = "#2E7D32"     # green
    COLOR_NEGATIVE              = "#C62828"     # red
    COLOR_NEUTRAL               = "#546E7A"     # slate

    OUTPUT_FILENAME             = "CAMARF_Research_Report_v1.0.0.pdf"


# =============================================================================
# MASTER CONFIG — single import point for all modules
# =============================================================================

class Config:
    IBKR        = IBKRConfig
    DATA        = DataConfig
    UNIVERSE    = UniverseConfig
    ANALYSIS    = AnalysisConfig
    ML          = MLConfig
    BACKTEST    = BacktestConfig
    OPTIONS     = OptionsConfig
    STATS       = StatsConfig
    REPORT      = ReportConfig

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
