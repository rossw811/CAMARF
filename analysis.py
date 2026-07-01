# =============================================================================
# CAMARF — Cross-Asset Co-Movement Arbitrage Research Framework
# analysis.py — Co-movement scan, spread model, regime classification, decay
# github.com/rossw811/CAMARF
#
# Pipeline order per timeframe:
#   1.  Load aligned data from data.UniverseResult
#   2.  UniverseFilter        — vectorized N×N Pearson correlation pre-filter
#   3.  CointScanner          — parallel Engle-Granger + BH-FDR correction
#                               + rolling cointegration fraction (decay signal)
#   4.  HedgeRatioEstimator   — OLS (primary) + TLS + Kalman (comparisons)
#   5.  SpreadModel           — OU fit, z-score, half-life, mean reversion speed
#                               (rolling 252D primary + expanding window comp)
#   6.  VolumeStructure       — relative vol, VWAP dev, CVD proxy, Amihud,
#                               squeeze indicator, cross-leg RSI divergence,
#                               rolling correlation + velocity
#   7.  RegimeClassifier      — K-Means + GMM + HMM, auto-K (silhouette/BIC),
#                               vol-standardized features, expanding-window fit,
#                               three conditioning variants (A regime, B volume,
#                               C baseline)
#   8.  StrategyDecayDetector — rolling coint fraction, half-life trend,
#                               Zivot-Andrews + CUSUM structural break tests
#   9.  CrossAssetTagger      — flags pairs spanning asset classes
#  10.  TrioBuilder           — Johansen multivariate test on A-B / B-C trios
#  11.  ThresholdCalibrator   — Pearson / Johansen / parameter sensitivity
#                               (run once on 1D — methodology section input)
#  12.  Save to output/results/{tf_label}/*.parquet + bias_audit.json
#
# Design principles:
#   - One TF at a time (memory management)
#   - All bias remedies recorded to BiasAuditLog continuously
#   - Expanding-window constraint on all fits requiring temporal data
#   - Rolling and expanding both computed where the comparison is informative
#   - Failed-statistical-power tests skipped per-TF, logged in audit
# =============================================================================

from __future__ import annotations

import json
import logging
import os
import re
import time
import traceback
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Set, Any, Union

import numpy as np
import pandas as pd

# Statistical libraries
from scipy import stats as scipy_stats
from scipy.linalg import svd as scipy_svd

try:
    from statsmodels.tsa.stattools import coint, adfuller
    from statsmodels.tsa.vector_ar.vecm import coint_johansen
    from statsmodels.regression.linear_model import OLS
    from statsmodels.tools import add_constant

    _STATSMODELS_AVAILABLE = True
except ImportError:
    _STATSMODELS_AVAILABLE = False

try:
    from sklearn.cluster import KMeans
    from sklearn.mixture import GaussianMixture
    from sklearn.metrics import silhouette_score
    from sklearn.preprocessing import StandardScaler

    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False

try:
    from hmmlearn.hmm import GaussianHMM

    _HMMLEARN_AVAILABLE = True
except ImportError:
    _HMMLEARN_AVAILABLE = False

# Project imports
from config import Config
from data import (
    UniverseBuilder,
    UniverseResult,
    DataAligner,
    DataStore,
    QualityReport,
    GapFlag,
    gap_aware_returns,
    clean_close,
)

warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# =============================================================================
# Logging setup — mirrors data.py format
# =============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("CAMARF.analysis")


# =============================================================================
# DATACLASSES — full results schema
# =============================================================================


@dataclass
class BiasAuditEntry:
    """Single bias remedy record — written every time a class applies a fix."""

    timestamp: str
    bias_type: str  # "lookahead" | "multiple_testing" | "non_stationarity"
    # | "regime_lookahead" | "survivorship" | "snooping"
    classification: str  # "data" | "model" | "statistical" | "execution"
    mechanism: str  # how this bias would distort results if uncorrected
    remedy: str  # what was actually done in code
    scope: str  # what data this entry applies to (TF, pair, asset)
    residual_risk: str  # remaining uncorrected risk after remedy


@dataclass
class PairResult:
    """One confirmed cointegrated pair on one timeframe."""

    symbol_a: str
    symbol_b: str
    asset_class_a: str
    asset_class_b: str
    tf_label: str
    is_cross_asset: bool

    # Cointegration
    pearson_corr: float
    coint_pvalue_raw: float
    coint_pvalue_adjusted: float  # post-BH-FDR
    coint_fraction_rolling: float  # fraction of 252-bar windows where p<0.05

    # Hedge ratios (full sample, point estimate)
    hedge_ratio_ols: float
    hedge_ratio_tls: float
    hedge_ratio_kalman_mean: float  # mean of Kalman trajectory

    # OU parameters (full sample)
    half_life_rolling: float  # rolling 252D median
    half_life_expanding: float  # full sample
    mean_reversion_speed: float  # θ

    # Decay signals
    half_life_trend_slope: float  # >0 = decaying
    zivot_andrews_break: Optional[str]  # date of structural break or None
    cusum_first_excursion: Optional[str]  # date CUSUM exits bounds or None

    # Hurst exponent (spread mean-reversion quality)
    # hurst_rs < 0.48 required to enter ML pipeline as primary gate
    hurst_rs: Optional[float]  # R/S estimate (primary)
    hurst_dfa: Optional[float]  # DFA estimate (comparison, robust)
    hurst_divergence: Optional[float]  # |rs - dfa|; >0.10 = uncertain
    passes_ml_gate: bool  # True if hurst_rs < 0.48
    hurst_interpretation: str  # "strongly_mean_reverting" / "mean_reverting" / etc.

    # Eigenportfolio decomposition validation
    # After projecting out Marchenko-Pastur-justified systematic factors,
    # does the idiosyncratic spread still show cointegration?
    # Gold tier: passes both raw EG and eigenportfolio residual EG.
    # Silver tier: passes raw EG only (may be factor-driven).
    eigenport_pvalue: Optional[float]  # EG p-value on residual spread
    passes_eigenportfolio: Optional[bool]  # True if residual EG p < 0.05
    n_factors_removed: Optional[int]  # K factors projected out
    confidence_tier: str  # "gold" / "silver" / "bronze"

    # Sample sizes
    n_bars: int
    n_overlap: int

    # Source provenance
    source_a: str
    source_b: str

    # Episodic cointegration re-test on IBKR deep history (ibkr_supplement/),
    # added 2026-06-21 — see DEVELOPMENT.md. None/False when no supplement
    # file exists for either leg at this TF (e.g. always for 3m — not a
    # native IBKR bar size — and a near-no-op for 15m, whose supplement is
    # no deeper than the main cache; both documented, not bugs).
    coint_fraction_rolling_deep: Optional[float] = None
    deep_history_used: bool = False

    # Secondary-evidence override on the coint_frac filter (added 2026-06-22,
    # see DEVELOPMENT.md): True only for a pair that fell BELOW
    # Config.UNIVERSE.MIN_COINT_FRAC but was kept anyway because the
    # independent stability signals (half-life trend, structural-break
    # tests) came back clean. False/None for every other pair — passed the
    # primary threshold cleanly, or excluded outright. Makes the override
    # auditable in pairs.parquet rather than an invisible side effect.
    coint_frac_secondary_override: bool = False

    # BUG-D49 price-degeneracy flag (added 2026-06-27): True when one or
    # both legs appear in the research/price_density_screen output with
    # genuinely_liquid=True — adequate dollar volume but implausibly few
    # distinct close prices (median 2-7 distinct values across hundreds of
    # bars). ml.py skips these pairs; the pipeline still keeps them in
    # pairs.parquet so the backtest comparison arm can evaluate whether the
    # degeneracy actually matters for live strategy outcomes.
    thin_info_content: bool = False

    # EG circular-shift permutation robustness flag (added 2026-06-27):
    # True = pair survived research/eg_permutation_check.py's null (real
    # EG p-value is distinguishable from the null of its own autocorrelation
    # structure); False = flagged divergent; None = not yet checked.
    # Policy as of 2026-06-27: comparison arm only until backtest.py exists.
    permutation_robust: Optional[bool] = None

    # Kalman hedge-ratio drift velocity (added 2026-06-29):
    # Mean absolute first-difference of the Kalman beta series over the
    # trailing 20 bars. High drift → hedge ratio is moving, dynamic instability.
    # Near-zero → beta is stable, OU process well-calibrated.
    kalman_drift_velocity: Optional[float] = None


@dataclass
class TrioResult:
    """One confirmed cointegrated trio (A,B,C) on one timeframe."""

    symbol_a: str
    symbol_b: str
    symbol_c: str
    asset_class_a: str
    asset_class_b: str
    asset_class_c: str
    tf_label: str
    johansen_trace_stat: float
    johansen_pvalue_approx: float
    n_cointegrating_vectors: int
    n_bars: int
    is_cross_asset: bool


@dataclass
class RegimeResult:
    """Regime classification output for one asset on one timeframe."""

    symbol: str
    tf_label: str

    # K-means
    kmeans_k_selected: int
    kmeans_silhouette: float
    kmeans_window_used: int  # 10, 20, or 40 bars

    # GMM
    gmm_k_selected: int
    gmm_bic: float
    gmm_window_used: int

    # HMM
    hmm_k_selected: int
    hmm_bic: float
    hmm_window_used: int
    hmm_transition_matrix: List[List[float]]
    hmm_mean_dwell_times: List[float]  # expected bars per regime

    n_observations: int


@dataclass
class AnalysisResults:
    """Top-level results container, one per pipeline run."""

    timeframes_processed: List[str]
    pairs_by_tf: Dict[str, List[PairResult]]
    trios_by_tf: Dict[str, List[TrioResult]]
    regimes_by_tf: Dict[str, List[RegimeResult]]
    cross_asset_pairs: Dict[str, List[PairResult]]
    threshold_calibration: Dict[str, Any]
    bias_audit: List[BiasAuditEntry]
    runtime_seconds: float


# =============================================================================
# BIAS AUDIT LOG — written to continuously during pipeline execution
# =============================================================================


class BiasAuditLog:
    """
    Append-only log of every bias remedy applied during pipeline execution.

    Every class that applies a remedy (rolling vs expanding window, FDR
    correction, expanding-window regime fit, etc.) calls record() before
    proceeding. The accumulated log feeds the Bias Audit chapter of the
    final report.
    """

    _entries: List[BiasAuditEntry] = []

    @classmethod
    def reset(cls) -> None:
        cls._entries = []

    @classmethod
    def record(
        cls,
        bias_type: str,
        classification: str,
        mechanism: str,
        remedy: str,
        scope: str,
        residual_risk: str = "none",
    ) -> None:
        cls._entries.append(
            BiasAuditEntry(
                timestamp=datetime.now().isoformat(timespec="seconds"),
                bias_type=bias_type,
                classification=classification,
                mechanism=mechanism,
                remedy=remedy,
                scope=scope,
                residual_risk=residual_risk,
            )
        )

    @classmethod
    def all_entries(cls) -> List[BiasAuditEntry]:
        return list(cls._entries)

    @classmethod
    def save(cls, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump([asdict(e) for e in cls._entries], f, indent=2)
        log.info(f"Bias audit log saved: {len(cls._entries)} entries → {path}")


# =============================================================================
# UTILITIES
# =============================================================================



def _output_dir(tf_label: str) -> str:
    """Where results for this TF get written.

    Uses DataStore._TF_SAFE (already the cache-filename convention) rather
    than tf_label directly. Fixed 2026-06-21: Windows/NTFS is case-
    insensitive, so the raw labels "3m"/"3M" (3-minute vs. 3-month) and
    "1m"/"1M" (1-minute vs. 1-month) collided onto the same physical
    directory — whichever timeframe processed second would silently
    overwrite the other's results. _TF_SAFE already maps every active TF
    to a case-distinct name (1min/1mo, 3min/3mo, ...) for exactly this
    reason on the data cache side; reusing it here closes the same hole
    for analysis.py's results directories.
    """
    safe = DataStore._TF_SAFE.get(tf_label, tf_label)
    d = os.path.join(Config.DATA.OUTPUT_DIR, "results", safe)
    os.makedirs(d, exist_ok=True)
    return d


# =============================================================================
# SCRIPT-HASH INVALIDATION
# =============================================================================


def _compute_script_hash() -> str:
    """
    SHA-256 of analysis.py + config.py concatenated.

    Any change to either file — new method, parameter tweak, bug fix —
    produces a different hash, which triggers stale-result clearing.
    The hash is stored alongside results in output/results/analysis_hash.json.
    """
    import hashlib

    h = hashlib.sha256()
    for fname in ("analysis.py", "config.py"):
        # Find the file relative to this module's location
        script_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(script_dir, fname)
        if os.path.exists(path):
            with open(path, "rb") as f:
                h.update(f.read())
    return h.hexdigest()[:16]  # 16 hex chars — short but collision-resistant


_HASH_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "output",
    "results",
    "analysis_hash.json",
)

# Matches {name}_stale_{timestamp}, e.g. "15m_stale_20260621_115458" or
# "bias_audit.json_stale_20260621_115458". {name} itself may already end in
# this same suffix (a leftover that survived a previous cleanup attempt).
_STALE_SUFFIX_RE = re.compile(r".+_stale_\d{8}_\d{6}$")


def _load_stored_hash() -> Optional[str]:
    """Read the hash from the previous run, or None if no previous run."""
    if not os.path.exists(_HASH_FILE):
        return None
    try:
        with open(_HASH_FILE) as f:
            data = json.load(f)
        return data.get("hash")
    except Exception:
        return None


def _save_current_hash(h: str) -> None:
    """Write the current script hash so the next run can compare."""
    os.makedirs(os.path.dirname(_HASH_FILE), exist_ok=True)
    with open(_HASH_FILE, "w") as f:
        json.dump({"hash": h, "saved_at": datetime.now().isoformat()}, f, indent=2)


def clear_stale_results(force: bool = False) -> bool:
    """
    If analysis.py or config.py changed since the last run, delete all
    output/results/* so the pipeline starts clean.

    Args:
        force: if True, always clear regardless of hash comparison.

    Returns:
        True if results were cleared, False if they're still valid.

    Design principle: we ONLY clear results directories, never the data
    cache (output/cache/*). Clearing results is cheap — analysis reruns in
    ~90 min. Clearing the data cache would require re-fetching 6,000+
    symbol-TF combinations from yfinance and IBKR.
    """
    current_hash = _compute_script_hash()
    stored_hash = _load_stored_hash()

    if not force and current_hash == stored_hash:
        log.info(f"Script hash unchanged ({current_hash}) — reusing prior results")
        return False

    results_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "output", "results"
    )
    if not os.path.exists(results_dir):
        log.info(f"No prior results to clear (hash: {current_hash})")
        _save_current_hash(current_hash)
        return False

    reason = (
        "forced clear" if force else f"script changed ({stored_hash} → {current_hash})"
    )
    log.info(f"Clearing stale results: {reason}")

    # Clean up leftovers from the PREVIOUS run's rename first, before renaming
    # anything new. By now those entries have had a full run's duration
    # (~90 min) for OneDrive to release any sync locks, instead of being
    # rmtree'd a moment after they were touched — which failed almost every
    # time and silently chained another "_stale_{ts}" suffix onto the same
    # entries on every subsequent run (one bias_audit.json leftover reached
    # 213 characters across 9 runs before it broke `git add .` outright on
    # Windows' path-length limit).
    _cleanup_stale(results_dir)

    n_renamed = 0
    n_failed = 0
    n_left_for_next_pass = 0
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    for entry in os.scandir(results_dir):
        # Both are meant to persist/accumulate ACROSS hash changes, not get
        # cleared with the rest of results/ — analysis_hash.json by design;
        # confirmed_pairs_manifest.json was missing this same exclusion
        # (found 2026-06-21: every analysis.py source edit during active
        # development silently wiped it back to whatever the single most
        # recent run's TFs happened to confirm, losing prior runs'/TFs'
        # symbols — e.g. tonight's 3m-run pairs and Session 8's original 15
        # manifest symbols were both gone by the time the 1h-scoped run
        # finished, since the hash changed in between).
        if entry.name in ("analysis_hash.json", "confirmed_pairs_manifest.json"):
            continue
        if _STALE_SUFFIX_RE.match(entry.name):
            # Survived the cleanup pass above (lock still held). Leave its
            # name alone — renaming it again would chain another
            # "_stale_{ts}" suffix on forever. Retried by the next run's
            # _cleanup_stale() call instead.
            n_left_for_next_pass += 1
            continue
        # Rename strategy: move old results to {name}_stale_{ts}
        # Rename works on Windows even when OneDrive has files open,
        # because it moves the directory handle without touching file handles.
        # The pipeline writes fresh files into new directories this run.
        # Stale directories are cleaned up lazily by _cleanup_stale().
        stale_path = os.path.join(results_dir, f"{entry.name}_stale_{ts}")
        try:
            os.rename(entry.path, stale_path)
            n_renamed += 1
        except OSError:
            # Rename also failed (network drive, permission boundary, etc.)
            # Fall back: just let the pipeline overwrite existing files.
            # Old results will be overwritten by new writes — no action needed.
            n_failed += 1

    log_msg = f"  Stale results: renamed {n_renamed} old result directories"
    if n_failed:
        log_msg += f"; {n_failed} could not be renamed (pipeline will overwrite in place)"
    if n_left_for_next_pass:
        log_msg += f"; {n_left_for_next_pass} pre-existing stale leftovers held for next cleanup pass"
    log.info(log_msg)

    _save_current_hash(current_hash)
    return True


def _cleanup_stale(results_dir: str) -> None:
    """
    Remove stale result files/directories left by a previous
    clear_stale_results() call. Matches the pattern {name}_stale_{timestamp},
    regardless of whether {name} is a file (e.g. bias_audit.json) or a
    directory (e.g. a TF result dir) — a prior version only handled
    directories, so stale top-level files could never be cleaned up.
    """
    import shutil

    for entry in os.scandir(results_dir):
        if not _STALE_SUFFIX_RE.match(entry.name):
            continue
        try:
            if entry.is_dir():
                shutil.rmtree(entry.path, ignore_errors=True)
            else:
                os.remove(entry.path)
        except Exception:
            pass  # Best-effort; leftover stale entries don't affect correctness


def _benjamini_hochberg(
    pvalues: np.ndarray, alpha: float
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Benjamini-Hochberg FDR correction.

    Returns:
        rejected:    boolean array — True where null is rejected at FDR=alpha
        adjusted:    BH-adjusted p-values (monotone, in original order)

    Algorithm:
        Sort p-values ascending. For rank k (1-indexed), threshold is k*alpha/m.
        Find largest k where p(k) ≤ k*alpha/m. Reject all hypotheses 1..k.
        Adjusted p-values: p_adj(k) = min over j≥k of (m/j) * p(j), capped at 1.
    """
    p = np.asarray(pvalues, dtype=float)
    n = p.size
    if n == 0:
        return np.array([], dtype=bool), np.array([], dtype=float)

    # Sort ascending, remember original indices
    order = np.argsort(p)
    p_sorted = p[order]

    # BH threshold per rank
    ranks = np.arange(1, n + 1)
    threshold = ranks * alpha / n

    # Largest k with p(k) <= threshold(k)
    below = p_sorted <= threshold
    if np.any(below):
        k_max = np.max(np.where(below)[0])  # zero-indexed
    else:
        k_max = -1

    rejected_sorted = np.zeros(n, dtype=bool)
    if k_max >= 0:
        rejected_sorted[: k_max + 1] = True

    # Adjusted p-values: enforce monotonicity from right to left
    adj_sorted = p_sorted * n / ranks
    # cumulative minimum from the right
    adj_sorted = np.minimum.accumulate(adj_sorted[::-1])[::-1]
    adj_sorted = np.minimum(adj_sorted, 1.0)

    # Restore original order
    rejected = np.zeros(n, dtype=bool)
    adjusted = np.zeros(n, dtype=float)
    rejected[order] = rejected_sorted
    adjusted[order] = adj_sorted

    return rejected, adjusted


# =============================================================================
# CLASS 1 — UniverseFilter
# =============================================================================


class UniverseFilter:
    """
    Vectorized Pearson correlation pre-filter.

    Takes aligned price DataFrames (one per asset, all on shared NYSE index),
    computes log-return matrix, then the full N×N correlation matrix in a
    single numpy operation. Returns candidate pairs above MIN_PEARSON_CORR
    threshold (absolute value — negative correlations are valid pair signals).

    Performance: at N=526 assets × T≈5000 daily bars, the correlation matrix
    is computed in well under one second via BLAS-optimized np.corrcoef.

    Bias notes:
      - Pearson correlation on full sample IS lookahead-biased.
      - This is intentional and acceptable here: this is a PRE-FILTER to
        reduce the candidate space for downstream tests. Cointegration tests
        and OU fits use rolling/expanding windows.
      - Recorded in BiasAuditLog as a documented pre-filter limitation.
    """

    @staticmethod
    def build_returns_matrix(
        aligned_data: Dict[str, pd.DataFrame],
        min_overlap: int = 252,
    ) -> Tuple[np.ndarray, List[str], pd.DatetimeIndex]:
        """
        Stack aligned 'close' columns into an (N_assets × T_bars) matrix
        of log returns. Drop assets with fewer than min_overlap non-NaN bars.

        IMPORTANT: align_daily trims each asset to its own first_valid_index,
        so assets have DIFFERENT lengths (AAPL from 1980 = 11,500 bars;
        ABNB from 2020 = 1,500 bars). We must NOT require equal lengths.

        Strategy:
          1. Collect all close arrays regardless of length.
          2. Cap each at _MAX_COLS bars from the right (memory guard).
          3. Pad shorter series with NaN at the BEGINNING so all have the
             same width in the stacked matrix.
          4. The pairwise-complete correlation code already masks NaN, so only
             the overlapping period between two assets contributes to their
             correlation — no spurious signal from the padding.
        """
        symbols = []
        ret_list = []
        for sym, df in aligned_data.items():
            if df is None or df.empty or "close" not in df.columns:
                continue
            close = df["close"].values
            # Require at least some valid prices
            valid = np.sum(np.isfinite(close) & (close > 0))
            if valid < min_overlap:
                continue
            symbols.append(sym)
            # Gap-aware (fixed 2026-06-20): was computing log returns
            # directly off raw "close" here, with zero GapFlag masking —
            # contradicting CLAUDE.md's "never silently forward-fill a
            # DATA_GAP bar into a correlation calculation" rule. A bar that
            # forward-fills across a >5-bar gap produces one artificially
            # large return when the real price resumes; gap_aware_returns
            # masks exactly that return to NaN (DATA_GAP only — FILL and
            # NO_ACTIVITY bars are left as genuine zero-ish returns).
            ret_list.append(gap_aware_returns(df))

        if not ret_list:
            return np.empty((0, 0)), [], pd.DatetimeIndex([])

        # Cap each series at _MAX_COLS from the right to bound memory
        _MAX_COLS = 50_000
        ret_list = [r[-_MAX_COLS:] if len(r) > _MAX_COLS else r for r in ret_list]

        # Pad shorter series with NaN at the beginning so all are same width.
        # NaN prefix does not contribute to pairwise correlations.
        max_len = max(len(r) for r in ret_list)
        returns = np.array(
            [
                np.concatenate([np.full(max_len - len(r), np.nan), r.astype(float)])
                for r in ret_list
            ],
            dtype=float,
        )  # (N, max_len)
        # First bar of each padded prefix is NaN — correct
        # First actual bar of each series is NaN (no prior price) — correct

        # Filter assets with insufficient finite return bars
        valid_counts = np.sum(np.isfinite(returns), axis=1)
        keep_idx = np.where(valid_counts >= min_overlap)[0]
        if keep_idx.size == 0:
            return np.empty((0, 0)), [], pd.DatetimeIndex([])

        returns_kept = returns[keep_idx]
        symbols_kept = [symbols[i] for i in keep_idx]
        return returns_kept, symbols_kept, pd.DatetimeIndex([])

    @staticmethod
    def _vectorized_pairwise_stats(x: np.ndarray) -> Tuple[np.ndarray, ...]:
        """
        Shared masked-matmul core for pairwise-complete correlation stats.

        Returns (count, mean_x, mean_y, var_x, var_y, cov_xy, corr_raw) where
        each is an (n, n) matrix. mean_x/var_x are asset-i's mean/variance
        computed over the i/j overlap only (and mean_y/var_y the mirror for
        asset j) — see _pairwise_corr docstring for the derivation. corr_raw
        is cov_xy / sqrt(var_x * var_y) computed WITHOUT any zero-variance
        guard (caller applies thresholds/guards).
        """
        finite = np.isfinite(x)
        x0 = np.where(finite, x, 0.0)
        m = finite.astype(np.float64)

        count = m @ m.T
        sum_x = x0 @ m.T          # sum_x[i, j] = sum of row i over overlap(i, j)
        sum_x2 = (x0 * x0) @ m.T  # sum_x2[i, j] = sum of row i^2 over overlap(i, j)
        sum_xy = x0 @ x0.T        # sum_xy[i, j] = sum of row i * row j over overlap(i, j)

        with np.errstate(invalid="ignore", divide="ignore"):
            mean_x = sum_x / count
            mean_y = sum_x.T / count
            var_x = sum_x2 / count - mean_x * mean_x
            var_y = sum_x2.T / count - mean_y * mean_y
            cov_xy = sum_xy / count - mean_x * mean_y
            den = np.sqrt(var_x * var_y)
            corr_raw = cov_xy / den
        return count, mean_x, mean_y, var_x, var_y, cov_xy, corr_raw, den

    @staticmethod
    def _exact_pair_corr(a: np.ndarray, b: np.ndarray, valid: np.ndarray, min_overlap: int):
        """
        Reference per-pair pairwise-complete Pearson correlation, computed
        the original (numerically stable, two-pass-demean) way: restrict to
        the overlap mask, demean within just that overlap, then dot product.
        Returns (value_or_nan, is_valid). Used as an exact fallback for the
        rare cells where the vectorized one-pass variance formula
        (E[x^2] - E[x]^2) is at risk of catastrophic cancellation.
        """
        m = int(np.sum(valid))
        if m < min_overlap:
            return np.nan, False
        aa = a[valid]
        aa = aa - aa.mean()
        bb = b[valid]
        bb = bb - bb.mean()
        den = np.sqrt(np.dot(aa, aa) * np.dot(bb, bb))
        if den > 0:
            return float(np.dot(aa, bb) / den), True
        return np.nan, False

    @staticmethod
    def _fix_ambiguous_variance_cells(
        x: np.ndarray,
        count: np.ndarray,
        var_x: np.ndarray,
        var_y: np.ndarray,
        corr_raw: np.ndarray,
        min_overlap: int,
        safety_factor: float = 1e8,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Detect cells where the one-pass variance formula (var_x/var_y from
        _vectorized_pairwise_stats) is at risk of catastrophic-cancellation
        error large enough to flip the original `den > 0` zero-variance
        guard, and recompute those cells EXACTLY via the original two-pass
        per-pair method (_exact_pair_corr). This is the only way to
        guarantee bit-for-bit-equivalent NaN/non-NaN decisions: the one-pass
        formula computes E[x^2] - E[x]^2 by subtracting two near-equal large
        numbers when the true variance is at or near zero (e.g. an
        illiquid/halted asset with an exactly-flat price over a window),
        and the rounding error from that subtraction can land on either
        side of zero — differently than the original two-pass dot-product
        method would. Such cells are rare in practice (<1% of pairs even on
        the worst observed real dataset) so recomputing them with a Python
        loop is cheap; the bulk of the matrix stays fully vectorized.

        Returns (corr_raw_fixed, den_valid_fixed) — corrected correlation
        values and a boolean mask of which cells have valid (den > 0)
        correlations, both with ambiguous cells corrected in place.
        """
        n = x.shape[0]
        eps = np.finfo(np.float64).eps
        # Cancellation error in E[x^2]-E[x]^2 is bounded by ~eps * E[x^2];
        # use a large safety factor since we only need to flag candidates
        # for exact recomputation, not make the final call here.
        scale = np.maximum(np.abs(var_x), np.abs(var_y)) + eps
        noise_floor = scale * eps * safety_factor
        ambiguous = (count >= min_overlap) & (
            (np.abs(var_x) < noise_floor) | (np.abs(var_y) < noise_floor)
        )
        np.fill_diagonal(ambiguous, False)
        den_valid = (count >= min_overlap) & np.isfinite(corr_raw)

        upper_ambiguous = np.triu(ambiguous, k=1)
        pairs = list(zip(*np.where(upper_ambiguous)))
        if not pairs:
            return corr_raw, den_valid

        finite = np.isfinite(x)
        for i, j in pairs:
            valid = finite[i] & finite[j]
            val, ok = UniverseFilter._exact_pair_corr(x[i], x[j], valid, min_overlap)
            corr_raw[i, j] = val
            corr_raw[j, i] = val
            den_valid[i, j] = ok
            den_valid[j, i] = ok
        return corr_raw, den_valid

    @staticmethod
    def _pairwise_corr(returns: np.ndarray, min_overlap: int = 30) -> np.ndarray:
        """
        Internal: N×N pairwise-complete Pearson correlation from demeaned returns.
        Used by correlation_matrix, spearman_matrix (after ranking), and
        rolling_corr_avg_matrix (per window).

        Vectorized (2026-06-23) via masked matrix multiplication — replaces a
        prior O(n^2) Python-level double loop that dominated UniverseFilter's
        runtime (532-580s per timeframe at n~1500 in production logs). The
        original loop, for each pair (i, j), restricted to the overlap of
        finite values and re-demeaned over JUST that overlap before computing
        Pearson's r. That two-stage demean (subtract full-row mean, then
        subtract the overlap-subset mean of the already-shifted values) is
        algebraically identical to demeaning directly by the overlap-subset
        mean, since mean is linear: (x - c) - mean(x - c) == x - mean(x) for
        any constant c. So the result is exactly standard pairwise-complete
        Pearson correlation, which can be computed for ALL pairs at once via
        _vectorized_pairwise_stats (count/mean/var/cov per pair via masked
        matmuls), with rare near-zero-variance cells exactly recomputed by
        _fix_ambiguous_variance_cells to guarantee the same NaN/non-NaN
        decisions as the original per-pair two-pass method (see that
        function's docstring for why one-pass variance alone is not safe
        for bit-exact equivalence). Verified against the original loop on
        real cached data across multiple timeframes — max abs diff ~1e-15
        on non-ambiguous cells, exact NaN-pattern match throughout — while
        turning an O(n^2 * T) Python-loop computation into a handful of
        BLAS matmuls plus a tiny per-ambiguous-cell fallback.

        min_overlap semantics preserved exactly: pairs with overlap count
        below min_overlap, or zero variance in either series over the
        overlap, are left as NaN — matching the original `m < min_overlap`
        skip and `den > 0` guard.
        """
        n = returns.shape[0]
        count, mean_x, mean_y, var_x, var_y, cov_xy, corr_raw, den = (
            UniverseFilter._vectorized_pairwise_stats(returns)
        )
        corr_raw, den_valid = UniverseFilter._fix_ambiguous_variance_cells(
            returns, count, var_x, var_y, corr_raw, min_overlap
        )

        corr = np.where(den_valid, corr_raw, np.nan)
        corr[count < min_overlap] = np.nan
        np.fill_diagonal(corr, 1.0)
        return corr

    @staticmethod
    def correlation_matrix(returns: np.ndarray) -> np.ndarray:
        """N×N Pearson correlation (pairwise complete, NaN-safe)."""
        return UniverseFilter._pairwise_corr(returns)

    @staticmethod
    def spearman_matrix(returns: np.ndarray) -> np.ndarray:
        """
        N×N Spearman rank correlation.

        More robust than Pearson to outlier returns (earnings spikes,
        flash crashes). Computed by ranking each asset's return series
        over their pairwise overlap, then computing Pearson on the ranks.

        Why it matters: a single large-gap event (circuit breaker, halt)
        can shift Pearson dramatically while Spearman is insensitive to
        the magnitude of the outlier — only its rank.
        """
        n, T = returns.shape
        corr = np.full((n, n), np.nan, dtype=float)
        # Rank within each row's finite values (argsort of argsort = rank)
        ranks = np.full_like(returns, np.nan, dtype=float)
        for i in range(n):
            mask = np.isfinite(returns[i])
            if np.sum(mask) < 30:
                continue
            r = np.empty(T, dtype=float)
            r[:] = np.nan
            vals = returns[i][mask]
            r_vals = np.argsort(np.argsort(vals)).astype(float)
            r[mask] = r_vals
            ranks[i] = r
        return UniverseFilter._pairwise_corr(ranks)

    @staticmethod
    def rolling_corr_avg_matrix(
        returns: np.ndarray,
        window: int = 252,
        n_windows: int = 5,
    ) -> np.ndarray:
        """
        N×N mean-of-rolling-windows Pearson correlation.

        Instead of full-sample Pearson, computes the average of the last
        n_windows rolling {window}-bar Pearson correlations.

        Decay-aware: a pair correlated for 15 years but decorrelated in
        the last 2 years shows a lower rolling average — correctly penalizing
        the stale relationship. This is the right pre-filter when we want
        pairs that are CURRENTLY correlated, not historically.

        Vectorized (2026-06-23): each window's N×N pairwise-complete Pearson
        correlation is now computed via the same masked-matmul approach as
        _pairwise_corr (see its docstring for the equivalence proof and
        _fix_ambiguous_variance_cells for why near-zero-variance cells are
        exactly recomputed rather than trusted to the one-pass formula)
        instead of a per-window O(n^2) Python double loop. With n_windows=5
        windows, the original loop ran the O(n^2) pairwise computation 5x —
        this was the single most expensive of the three correlation matrices
        in production logs (233-239s per timeframe). Only the outer loop
        over the (small, fixed at 5) windows remains in Python; everything
        else is BLAS matmuls (plus a rare per-cell fallback for ambiguous
        near-zero-variance pairs — observed on real 30min cached data from
        illiquid/halted assets with flat sub-windows, where the one-pass
        formula's cancellation error can flip the `den > 0` decision; fixed
        cells matched the original to ~1e-15 after the exact recompute). A
        window contributes to a pair's average under EXACTLY the same
        condition as before: overlap count >= 30 AND nonzero variance in
        both series over that window's overlap (the original `m < 30` skip
        and `den > 0` guard).
        """
        n, T = returns.shape
        corr = np.full((n, n), np.nan, dtype=float)
        np.fill_diagonal(corr, 1.0)

        starts = list(range(0, T - window, window))[-n_windows:]
        if not starts:
            return corr

        # Accumulate pairwise correlations across windows
        sums = np.zeros((n, n), dtype=float)
        counts = np.zeros((n, n), dtype=int)

        means = np.nanmean(returns, axis=1, keepdims=True)
        dm = returns - means
        min_overlap = 30

        for s in starts:
            e = s + window
            w = dm[:, s:e]

            ov_count, _mx, _my, var_x, var_y, _cov, window_corr, _den = (
                UniverseFilter._vectorized_pairwise_stats(w)
            )
            window_corr, window_valid = UniverseFilter._fix_ambiguous_variance_cells(
                w, ov_count, var_x, var_y, window_corr, min_overlap
            )
            window_valid = window_valid & (ov_count >= min_overlap)
            # Only accumulate strict upper triangle to match original
            # i<j-only accumulation (sums/counts mirrored symmetrically below)
            np.fill_diagonal(window_valid, False)
            sums[window_valid] += window_corr[window_valid]
            counts[window_valid] += 1

        mask = counts > 0
        corr[mask] = sums[mask] / counts[mask]
        return corr

    @staticmethod
    def dcor_matrix(returns: np.ndarray, max_n: int = 1000) -> np.ndarray:
        """
        N×N distance correlation matrix.

        Distance correlation (Székely, Rizzo & Bakirov 2007) detects
        both linear AND nonlinear dependence. dCor(X,Y)=0 IFF X,Y independent
        (unlike Pearson which only detects linear dependence).

        Particularly valuable for cross-asset pairs where the co-movement
        relationship may be nonlinear (e.g. equity↔commodity during stress
        regimes follows a different functional form than during calm regimes).

        Algorithm (O(n²) per pair, but vectorized):
          1. Compute pairwise distance matrix for each asset's return series
          2. Double-center each distance matrix
          3. dCor = sqrt(dCov(X,Y) / sqrt(dCov(X,X) * dCov(Y,Y)))
          where dCov(X,Y) = mean of element-wise products of centered distance matrices.

        Computational limit: at N=522 assets, N×N pairs × O(n²) per pair
        is expensive. We cap each series at max_n observations and only
        compute for pairs already in the Pearson candidate set (called
        selectively by run(), not unconditionally).
        """
        n, T = returns.shape
        corr = np.full((n, n), np.nan, dtype=float)
        np.fill_diagonal(corr, 1.0)

        # Pre-compute per-asset centered distance matrices (capped at max_n)
        cdms = {}
        for i in range(n):
            ri = returns[i]
            mask = np.isfinite(ri)
            m = int(np.sum(mask))
            if m < 30:
                continue
            x = ri[mask]
            if x.size > max_n:
                x = x[-max_n:]  # use most recent data
            cdms[i] = UniverseFilter._centered_distance_matrix(x)

        for i in range(n):
            if i not in cdms:
                continue
            for j in range(i + 1, n):
                if j not in cdms:
                    continue
                A, B = cdms[i], cdms[j]
                # Trim to same size (may differ if different valid counts)
                sz = min(A.shape[0], B.shape[0])
                if sz < 30:
                    continue
                A = A[:sz, :sz]
                B = B[:sz, :sz]
                dcov_xy = float(np.mean(A * B))
                dcov_xx = float(np.mean(A * A))
                dcov_yy = float(np.mean(B * B))
                denom = np.sqrt(abs(dcov_xx) * abs(dcov_yy))
                if denom > 1e-12:
                    dc = float(np.sqrt(max(0.0, dcov_xy / denom)))
                    corr[i, j] = dc
                    corr[j, i] = dc
        return corr

    @staticmethod
    def _centered_distance_matrix(x: np.ndarray) -> np.ndarray:
        """
        Double-centered pairwise distance matrix for distance correlation.
        A_{ij} = |x_i - x_j| - row_mean_i - col_mean_j + grand_mean
        """
        n = x.size
        D = np.abs(x[:, None] - x[None, :])  # (n, n)
        row = D.mean(axis=1, keepdims=True)
        col = D.mean(axis=0, keepdims=True)
        gm = D.mean()
        return D - row - col + gm

    @staticmethod
    def candidate_pairs(
        corr: np.ndarray,
        symbols: List[str],
        threshold: float,
        asset_class_map: Dict[str, str],
        spearman: Optional[np.ndarray] = None,
        rolling_avg: Optional[np.ndarray] = None,
        dcor: Optional[np.ndarray] = None,
    ) -> List[Dict[str, Any]]:
        """
        Extract pairs where Pearson |ρ| ≥ threshold.

        Each pair is also tagged with its Spearman, rolling-average, and
        dCor values (if provided), and which methods confirmed it at threshold.

        Confidence tiers (for paper section on methodology robustness):
          Gold   — all three methods (Pearson + Spearman + rolling avg) confirm
          Silver — two methods confirm
          Bronze — only Pearson confirms (Spearman and/or rolling avg disagree)

        dCor is reported separately (not used for tier assignment) because
        dCor captures nonlinear dependence and is not directly comparable
        to linear correlation thresholds.
        """
        n = corr.shape[0]
        pairs = []
        for i in range(n):
            for j in range(i + 1, n):
                c = corr[i, j]
                if not np.isfinite(c) or abs(c) < threshold:
                    continue
                sym_a = symbols[i]
                sym_b = symbols[j]
                cls_a = asset_class_map.get(sym_a, "unknown")
                cls_b = asset_class_map.get(sym_b, "unknown")

                rho_sp = (
                    float(spearman[i, j])
                    if spearman is not None and np.isfinite(spearman[i, j])
                    else np.nan
                )
                rho_roll = (
                    float(rolling_avg[i, j])
                    if rolling_avg is not None and np.isfinite(rolling_avg[i, j])
                    else np.nan
                )
                rho_dc = (
                    float(dcor[i, j])
                    if dcor is not None and np.isfinite(dcor[i, j])
                    else np.nan
                )

                sp_ok = np.isfinite(rho_sp) and abs(rho_sp) >= threshold
                roll_ok = np.isfinite(rho_roll) and abs(rho_roll) >= threshold
                n_methods = 1 + int(sp_ok) + int(roll_ok)
                tier = {3: "gold", 2: "silver", 1: "bronze"}[n_methods]

                pairs.append(
                    {
                        "symbol_a": sym_a,
                        "symbol_b": sym_b,
                        "asset_class_a": cls_a,
                        "asset_class_b": cls_b,
                        "pearson_corr": float(c),
                        "spearman_corr": rho_sp,
                        "rolling_avg_corr": rho_roll,
                        "dcor": rho_dc,
                        "pearson_confirmed": True,
                        "spearman_confirmed": sp_ok,
                        "rolling_confirmed": roll_ok,
                        "confidence_tier": tier,
                        "is_cross_asset": cls_a != cls_b,
                    }
                )
        return pairs

    @staticmethod
    def run(
        aligned_data: Dict[str, pd.DataFrame],
        asset_class_map: Dict[str, str],
        threshold: float,
        tf_label: str,
        run_dcor: bool = False,
        return_matrices: bool = False,  # if True, returns (pairs, syms, returns, corr, sym_order)
    ) -> Tuple:
        """
        Top-level entry. Returns (candidate_pairs, retained_symbols) by default.
        With return_matrices=True: (candidate_pairs, symbols, returns, pearson_corr, symbol_order).
        The matrices are needed by EigenportfolioDecomposer — passing them avoids
        recomputing the expensive N×N correlation matrix.

        Computes Pearson (primary), Spearman (robustness), and rolling-avg
        (decay-aware) correlation matrices. dCor is optional (expensive).
        Each candidate pair is tagged with confidence tier based on how
        many methods confirm it.
        """
        BiasAuditLog.record(
            bias_type="lookahead",
            classification="statistical",
            mechanism="All three correlation pre-filters use full or near-full "
            "sample — inherently lookahead-biased",
            remedy="Used only as candidate pre-filter; EG cointegration + "
            "BH-FDR correction + rolling spread modeling are the "
            "primary statistical decisions",
            scope=f"tf={tf_label}",
            residual_risk="Pairs that are not currently correlated but are still "
            "cointegrated in subperiods may be excluded",
        )

        _min_overlap = getattr(Config.ANALYSIS, "MIN_OVERLAP_BY_TF", {}).get(tf_label, 252)
        returns, symbols, _idx = UniverseFilter.build_returns_matrix(
            aligned_data,
            min_overlap=_min_overlap,
        )
        if returns.size == 0:
            log.warning(
                f"  [{tf_label}] UniverseFilter: no valid assets after filtering"
            )
            return [], []

        n = len(symbols)
        log.info(
            f"  [{tf_label}] Computing {n}×{n} correlation matrices "
            f"(Pearson + Spearman + rolling avg)..."
        )
        t0 = time.time()
        pearson = UniverseFilter.correlation_matrix(returns)
        t1 = time.time()
        spearman = UniverseFilter.spearman_matrix(returns)
        t2 = time.time()
        rolling_avg = UniverseFilter.rolling_corr_avg_matrix(returns)
        t3 = time.time()
        dcor_mat = None
        if run_dcor:
            log.info(f"  [{tf_label}] Computing dCor matrix (may take minutes)...")
            dcor_mat = UniverseFilter.dcor_matrix(returns)
        log.info(
            f"  [{tf_label}] Pearson {t1-t0:.1f}s | "
            f"Spearman {t2-t1:.1f}s | "
            f"RollingAvg {t3-t2:.1f}s"
        )

        pairs = UniverseFilter.candidate_pairs(
            pearson,
            symbols,
            threshold,
            asset_class_map,
            spearman=spearman,
            rolling_avg=rolling_avg,
            dcor=dcor_mat,
        )
        cross = sum(1 for p in pairs if p["is_cross_asset"])
        n_gold = sum(1 for p in pairs if p.get("confidence_tier") == "gold")
        n_sil = sum(1 for p in pairs if p.get("confidence_tier") == "silver")
        log.info(
            f"  [{tf_label}] Candidate pairs: {len(pairs)} ({cross} cross-asset)  "
            f"threshold |ρ| ≥ {threshold:.2f}  "
            f"[gold={n_gold} silver={n_sil} bronze={len(pairs)-n_gold-n_sil}]"
        )
        if return_matrices:
            return pairs, symbols, returns, pearson, symbols
        return pairs, symbols, None, None, symbols


# =============================================================================
# CLASS 2a — Engle-Granger worker function (top-level for multiprocessing)
# =============================================================================


def _eg_worker(args: Tuple[str, str, np.ndarray, np.ndarray, int]) -> Dict[str, Any]:
    """
    Worker run inside ProcessPoolExecutor. Must be top-level (picklable).

    Returns a dict with cointegration p-value and OLS hedge ratio so the
    main process can build PairResult objects without re-fitting OLS.
    """
    sym_a, sym_b, log_p_a, log_p_b, max_lag = args
    try:
        # Drop any NaN overlap (alignment should have handled this but be defensive)
        mask = np.isfinite(log_p_a) & np.isfinite(log_p_b)
        a = log_p_a[mask]
        b = log_p_b[mask]
        n_overlap = a.size
        if n_overlap < 60:
            return {
                "symbol_a": sym_a,
                "symbol_b": sym_b,
                "pvalue": 1.0,
                "hedge_ratio": np.nan,
                "n_overlap": n_overlap,
                "ok": False,
                "error": "insufficient_overlap",
            }
        # statsmodels coint returns (t-stat, p-value, crit_values)
        # It runs ADF on the residual of OLS(a on b)
        t_stat, p_value, _crit = coint(a, b, trend="c", maxlag=max_lag, autolag="aic")
        # Also compute the OLS hedge ratio directly for storage
        # ratio = cov(a,b) / var(b) (since constant included)
        b_centered = b - b.mean()
        a_centered = a - a.mean()
        var_b = np.dot(b_centered, b_centered)
        hr = np.dot(a_centered, b_centered) / var_b if var_b > 0 else np.nan
        return {
            "symbol_a": sym_a,
            "symbol_b": sym_b,
            "pvalue": float(p_value),
            "hedge_ratio": float(hr),
            "t_stat": float(t_stat),
            "n_overlap": int(n_overlap),
            "ok": True,
            "error": "",
        }
    except Exception as e:
        return {
            "symbol_a": sym_a,
            "symbol_b": sym_b,
            "pvalue": 1.0,
            "hedge_ratio": np.nan,
            "n_overlap": 0,
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
        }


def _rolling_coint_worker(
    args: Tuple[str, str, np.ndarray, np.ndarray, int, int],
) -> Dict[str, Any]:
    """
    Compute rolling cointegration fraction for one pair.
    Returns fraction of rolling windows where EG p < 0.05.
    """
    sym_a, sym_b, log_p_a, log_p_b, window, step = args
    try:
        mask = np.isfinite(log_p_a) & np.isfinite(log_p_b)
        a = log_p_a[mask]
        b = log_p_b[mask]
        n = a.size
        if n < window + step:
            return {
                "symbol_a": sym_a,
                "symbol_b": sym_b,
                "fraction": np.nan,
                "n_windows": 0,
            }
        n_significant = 0
        n_windows = 0
        for start in range(0, n - window + 1, step):
            a_w = a[start : start + window]
            b_w = b[start : start + window]
            try:
                _t, p, _c = coint(a_w, b_w, trend="c", maxlag=1, autolag=None)
                if p < 0.05:
                    n_significant += 1
                n_windows += 1
            except Exception:
                continue
        frac = n_significant / n_windows if n_windows > 0 else np.nan
        return {
            "symbol_a": sym_a,
            "symbol_b": sym_b,
            "fraction": float(frac),
            "n_windows": int(n_windows),
        }
    except Exception:
        return {
            "symbol_a": sym_a,
            "symbol_b": sym_b,
            "fraction": np.nan,
            "n_windows": 0,
        }


# =============================================================================
# CLASS 2 — CointScanner
# =============================================================================


class CointScanner:
    """
    Engle-Granger cointegration test on candidate pairs, parallelized
    via ProcessPoolExecutor across 12 workers.

    Procedure:
      1. For each candidate pair, run OLS(log_price_A on log_price_B)
         and ADF on residuals. statsmodels.tsa.stattools.coint() does both.
      2. Collect all p-values.
      3. Apply Benjamini-Hochberg FDR correction at FDR_ALPHA=0.05.
      4. Confirmed pairs are those whose BH-adjusted p-value remains
         significant.
      5. For each confirmed pair, run rolling 252-bar cointegration test
         and record the fraction of windows with p<0.05. This is the
         strategy decay signal.

    Bias notes:
      - Multiple testing across thousands of pairs corrected via BH-FDR.
      - Rolling cointegration uses non-overlapping or step-skipping windows
        to maintain test independence.
      - Recorded in BiasAuditLog.
    """

    @staticmethod
    def _build_log_price_map(
        aligned_data: Dict[str, pd.DataFrame],
        symbols: List[str],
    ) -> Dict[str, np.ndarray]:
        """
        Build {symbol: log_close_array} once, reused for all pair EG tests.
        DATA_GAP bars are masked to NaN: a 6-day data void produces a large
        spurious return at the resumption bar that would artificially widen
        the ADF test statistic toward false rejection of unit root.
        """
        out = {}
        for sym in symbols:
            df = aligned_data.get(sym)
            if df is None or "close" not in df.columns:
                continue
            close = clean_close(df, exclude_flags=(GapFlag.DATA_GAP,))
            with np.errstate(invalid="ignore", divide="ignore"):
                lp = np.where(close > 0, np.log(close), np.nan)
            out[sym] = lp
        return out

    @staticmethod
    def scan(
        candidate_pairs: List[Dict[str, Any]],
        aligned_data: Dict[str, pd.DataFrame],
        symbols_in_corr: List[str],
        tf_label: str,
        fdr_alpha: float = None,
        max_lag: int = None,
        n_workers: int = 12,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Run Engle-Granger on all candidate pairs, apply BH-FDR, return
        confirmed pairs with adjusted p-values.

        Returns:
            confirmed:  list of dicts (subset of candidate_pairs with extra
                        keys: coint_pvalue_raw, coint_pvalue_adjusted,
                        hedge_ratio_ols_pointest, n_overlap)
            stats:      dict with summary (n_tested, n_rejected, etc.)
        """
        if not _STATSMODELS_AVAILABLE:
            log.error("  statsmodels not available — cannot run cointegration tests")
            return [], {}

        fdr_alpha = fdr_alpha if fdr_alpha is not None else Config.STATS.FDR_ALPHA
        max_lag = max_lag if max_lag is not None else Config.ANALYSIS.EG_MAX_LAG

        if not candidate_pairs:
            return [], {"n_tested": 0, "n_passed_raw": 0, "n_passed_fdr": 0}

        BiasAuditLog.record(
            bias_type="multiple_testing",
            classification="statistical",
            mechanism=f"Testing {len(candidate_pairs)} pairs at α=0.05 produces "
            f"~{int(len(candidate_pairs)*0.05)} expected false positives "
            f"under the null hypothesis",
            remedy=f"Benjamini-Hochberg FDR correction at α={fdr_alpha}; "
            "adjusted p-values used for significance decision",
            scope=f"tf={tf_label}",
            residual_risk=f"Expected proportion of false positives among rejected "
            f"pairs ≈ {fdr_alpha}",
        )

        log.info(
            f"  [{tf_label}] Running EG on {len(candidate_pairs)} pairs "
            f"(workers={n_workers}, max_lag={max_lag})..."
        )

        # Build log-price arrays once
        log_prices = CointScanner._build_log_price_map(aligned_data, symbols_in_corr)

        # Prepare worker tasks
        tasks = []
        for p in candidate_pairs:
            lp_a = log_prices.get(p["symbol_a"])
            lp_b = log_prices.get(p["symbol_b"])
            if lp_a is None or lp_b is None:
                continue
            tasks.append((p["symbol_a"], p["symbol_b"], lp_a, lp_b, max_lag))

        if not tasks:
            return [], {"n_tested": 0, "n_passed_raw": 0, "n_passed_fdr": 0}

        # Run in parallel
        t0 = time.time()
        results = []
        with ProcessPoolExecutor(max_workers=n_workers) as pool:
            for r in pool.map(_eg_worker, tasks, chunksize=50):
                results.append(r)
        log.info(f"  [{tf_label}] EG complete in {time.time()-t0:.1f}s")

        # Build index from results back to candidate metadata
        meta_by_key = {(p["symbol_a"], p["symbol_b"]): p for p in candidate_pairs}

        # Collect p-values for BH-FDR
        ok_results = [r for r in results if r.get("ok")]
        if not ok_results:
            return [], {"n_tested": len(results), "n_passed_raw": 0, "n_passed_fdr": 0}

        pvals = np.array([r["pvalue"] for r in ok_results])
        rejected, adjusted = _benjamini_hochberg(pvals, fdr_alpha)

        n_raw_pass = int(np.sum(pvals < Config.ANALYSIS.EG_SIGNIFICANCE))
        n_fdr_pass = int(np.sum(rejected))

        confirmed = []
        for i, r in enumerate(ok_results):
            if rejected[i]:
                key = (r["symbol_a"], r["symbol_b"])
                meta = meta_by_key.get(key, {})
                confirmed.append(
                    {
                        **meta,
                        "coint_pvalue_raw": float(r["pvalue"]),
                        "coint_pvalue_adjusted": float(adjusted[i]),
                        "hedge_ratio_ols_pointest": float(r["hedge_ratio"]),
                        "n_overlap": int(r["n_overlap"]),
                    }
                )

        stats = {
            "n_tested": len(results),
            "n_passed_raw": n_raw_pass,
            "n_passed_fdr": n_fdr_pass,
            "fdr_alpha": fdr_alpha,
        }
        log.info(
            f"  [{tf_label}] EG: tested={len(results)}, "
            f"raw<{Config.ANALYSIS.EG_SIGNIFICANCE}={n_raw_pass}, "
            f"FDR-adjusted<{fdr_alpha}={n_fdr_pass}"
        )
        return confirmed, stats

    @staticmethod
    def rolling_fraction(
        confirmed_pairs: List[Dict[str, Any]],
        aligned_data: Dict[str, pd.DataFrame],
        tf_label: str,
        window: int = 252,
        step: int = 21,
        n_workers: int = 12,
    ) -> List[Dict[str, Any]]:
        """
        For each confirmed pair, compute fraction of rolling windows where
        EG p<0.05. Step controls overlap — step=window means no overlap
        (independent tests), step<window means overlapping.

        We use step=21 (one month for daily) to balance independence and
        coverage. Documented in BiasAuditLog.
        """
        if not _STATSMODELS_AVAILABLE or not confirmed_pairs:
            return confirmed_pairs

        # Adjust window for shallow TFs — if we don't have at least 2*window
        # bars on any pair, downscale or skip
        sample_pair = confirmed_pairs[0]
        sample_a = aligned_data.get(sample_pair["symbol_a"])
        n_bars = len(sample_a) if sample_a is not None else 0
        if n_bars < window + step:
            new_window = max(60, n_bars // 3)
            new_step = max(5, new_window // 10)
            log.info(
                f"  [{tf_label}] Rolling coint window {window}→{new_window} "
                f"(only {n_bars} bars available)"
            )
            BiasAuditLog.record(
                bias_type="statistical_power",
                classification="statistical",
                mechanism=f"Default 252-bar rolling window exceeds available "
                f"depth ({n_bars} bars) — test has insufficient power",
                remedy=f"Window scaled to {new_window} bars with step "
                f"{new_step}; rolling fraction interpretation "
                "should account for reduced statistical power",
                scope=f"tf={tf_label}",
                residual_risk="Shorter windows produce noisier fraction estimates",
            )
            window = new_window
            step = new_step

        # Pre-build log-price map
        symbols = list(
            {p["symbol_a"] for p in confirmed_pairs}
            | {p["symbol_b"] for p in confirmed_pairs}
        )
        log_prices = CointScanner._build_log_price_map(aligned_data, symbols)

        tasks = []
        for p in confirmed_pairs:
            lp_a = log_prices.get(p["symbol_a"])
            lp_b = log_prices.get(p["symbol_b"])
            if lp_a is None or lp_b is None:
                continue
            tasks.append((p["symbol_a"], p["symbol_b"], lp_a, lp_b, window, step))

        log.info(
            f"  [{tf_label}] Rolling coint on {len(tasks)} pairs "
            f"(window={window}, step={step})..."
        )
        t0 = time.time()
        fracs = {}
        with ProcessPoolExecutor(max_workers=n_workers) as pool:
            for r in pool.map(_rolling_coint_worker, tasks, chunksize=20):
                fracs[(r["symbol_a"], r["symbol_b"])] = r["fraction"]
        log.info(f"  [{tf_label}] Rolling coint complete in {time.time()-t0:.1f}s")

        # Attach fractions back to confirmed pairs
        for p in confirmed_pairs:
            key = (p["symbol_a"], p["symbol_b"])
            p["coint_fraction_rolling"] = float(fracs.get(key, np.nan))

        return confirmed_pairs


# =============================================================================
# CLASS 3 — HedgeRatioEstimator
# =============================================================================


# =============================================================================
# CLASS: EigenportfolioDecomposer
# =============================================================================


class EigenportfolioDecomposer:
    """
    Projects out systematic common factors from asset returns using
    eigenportfolio decomposition, then re-tests cointegration on the
    idiosyncratic residuals.

    WHY THIS MATTERS:
    If FITB and TFC are cointegrated, it could be because:
    (a) They share genuine business-level cointegration (same loan books,
        same deposit markets, same regulatory environment), OR
    (b) They both respond strongly to the "bank sector factor" and the
        "market factor" — any two bank stocks would look cointegrated.

    EG on raw prices cannot distinguish (a) from (b). Running EG on the
    residuals after projecting out the top-K systematic factors can:
    - If residual EG confirms cointegration → genuinely idiosyncratic,
      not just shared factor exposure. This is Gold tier.
    - If residual EG fails → the pair's cointegration was factor-driven.
      Still reportable (Silver tier) but weaker evidence.

    MARCHENKO-PASTUR THRESHOLD:
    For a random N×T matrix of IID Gaussian entries, the eigenvalues of
    the sample correlation matrix follow the MP distribution with bulk
    supported between λ± = (1 ± √(N/T))². Eigenvalues ABOVE λ+ represent
    genuine signal (common factors). For N=1536, T=16220:
      λ+ = (1 + √(1536/16220))² ≈ 1.61
    K = number of eigenvalues above λ+ gives the number of genuine factors.

    PROCEDURE:
    1. Compute N×N correlation matrix of asset returns (already computed
       by UniverseFilter — reuse it).
    2. Eigendecompose: C = V Λ V^T
    3. Find K = count of eigenvalues above λ+
    4. Factor returns: F (K×T) = V_K^T × R_demeaned (K top eigenvectors × returns)
    5. For each asset i: loadings b_i = F @ r_i / (F @ F^T) (OLS projection)
    6. Residual returns: r_i_resid = r_i - b_i^T @ F
    7. For each confirmed pair (A, B): run EG on the cumulative residual
       return (idiosyncratic spread) and store p-value.

    CONFIDENCE TIER ASSIGNMENT:
    - Gold:   passes raw EG+FDR AND residual EG (p < 0.05)
    - Silver: passes raw EG+FDR only (residual EG fails or uncertain)
    - Bronze: passes Pearson threshold only (not used by default)
    """

    @staticmethod
    def marchenko_pastur_threshold(
        n_assets: int, n_periods: int, sigma2: float = 1.0
    ) -> Tuple[float, int]:
        """
        Compute the Marchenko-Pastur upper edge λ+ and estimate K.

        Returns (lambda_plus, K) where K is the number of eigenvalues
        above λ+ in a unit-variance normalized correlation matrix.

        For a properly normalized correlation matrix (diagonal = 1.0),
        σ² = 1.0 is the correct default.
        """
        c = n_assets / n_periods  # ratio
        lambda_plus = sigma2 * (1 + np.sqrt(c)) ** 2
        return float(lambda_plus), None  # K determined from actual eigenvalues

    @staticmethod
    def _eigendecompose(
        corr: np.ndarray, n_periods: int
    ) -> Tuple[np.ndarray, np.ndarray, float, int]:
        """
        Shared eigendecomposition + Marchenko-Pastur factor count, extracted
        out of compute_factor_residuals() (2026-06-30) so a caller that only
        needs the eigenvalue spectrum itself — e.g. absorption_ratio.py's
        Kritzman-Li-Page-Rigobon (2011) systemic-risk measure, which needs
        the fraction of total variance explained by the top eigenvalues, not
        the residual-return OLS projection — doesn't have to duplicate (and
        risk silently diverging from) this NaN-handling/threshold logic.

        Returns (eigenvalues_desc, eigenvectors_desc, lambda_plus, K).
        K here is the MP-threshold factor count used for eigenportfolio
        residual construction — NOT the same K convention the Absorption
        Ratio uses (a fixed fraction of N per Kritzman et al., computed by
        the caller from the returned eigenvalues directly).
        """
        n = corr.shape[0]
        lambda_plus, _ = EigenportfolioDecomposer.marchenko_pastur_threshold(
            n, n_periods
        )

        # Found overnight (2026-06-23): a prior comment here claimed "use
        # only finite rows/cols" but no such filtering ever happened —
        # np.linalg.eigh on a NaN-containing matrix doesn't reliably raise,
        # it can silently return garbage eigenvalues/eigenvectors
        # (numpy/numpy#20280). NaN entries here are EXPECTED, not a bug in
        # the correlation computation itself: UniverseFilter._pairwise_corr
        # leaves corr[i,j]=NaN whenever pairwise overlap < min_overlap,
        # which happens routinely across a universe spanning 1980-era IPOs
        # to 2020+ ones plus crypto/forex/futures with very different
        # history lengths — unrelated to whether the specific confirmed
        # pair being analyzed has good data. Fix: treat insufficient-
        # overlap pairs as uncorrelated (0, a conservative "no evidence of
        # correlation" assumption) rather than silently feeding NaN/garbage
        # into the eigendecomposition that determines every pair's Gold/
        # Silver tier this run.
        n_nan = int(np.sum(~np.isfinite(corr)))
        corr_clean = np.nan_to_num(corr, nan=0.0)
        np.fill_diagonal(corr_clean, 1.0)
        if n_nan > 0:
            log.warning(
                f"  Eigenportfolio: {n_nan} NaN entries in the {n}x{n} "
                f"correlation matrix (insufficient pairwise overlap) — "
                f"treated as uncorrelated (0) before eigendecomposition"
            )
        with np.errstate(invalid="ignore"):
            eigenvalues, eigenvectors = np.linalg.eigh(corr_clean)  # ascending order

        # Flip to descending order
        eigenvalues = eigenvalues[::-1]
        eigenvectors = eigenvectors[:, ::-1]

        K = int(np.sum(eigenvalues > lambda_plus))
        return eigenvalues, eigenvectors, lambda_plus, K

    @staticmethod
    def compute_factor_residuals(
        returns: np.ndarray,  # (N, T) — pairwise-complete, NaN for missing
        corr: np.ndarray,  # (N, N) — already computed Pearson matrix
        n_periods: int,  # T (for MP threshold)
    ) -> Tuple[np.ndarray, int]:
        """
        Project out systematic factors and return residual returns.

        Returns:
            residuals: (N, T) array of idiosyncratic returns
            K:         number of factors removed
        """
        n = returns.shape[0]
        eigenvalues, eigenvectors, lambda_plus, K = EigenportfolioDecomposer._eigendecompose(
            corr, n_periods
        )
        if K == 0:
            # No factors above noise floor — returns are independent
            # Return raw returns unchanged with K=0
            return returns.copy(), 0

        log.debug(
            f"  Eigenportfolio: K={K} factors above λ+={lambda_plus:.3f} "
            f"(top eigenvalue={eigenvalues[0]:.2f})"
        )

        # Top-K eigenvectors (N, K)
        V_K = eigenvectors[:, :K]

        # Factor returns: F (K, T)
        # For each time step t, project all asset returns onto the K eigenvectors
        # Handle NaN by using valid observations per time step
        T = returns.shape[1]
        F = np.full((K, T), np.nan)
        for t in range(T):
            r_t = returns[:, t]
            mask = np.isfinite(r_t)
            if np.sum(mask) < K + 1:
                continue
            # F[:,t] = V_K[mask]^T @ r_t[mask]
            F[:, t] = V_K[mask].T @ r_t[mask]

        # OLS projection: for each asset, regress returns on factor returns
        residuals = returns.copy()
        for i in range(n):
            r_i = returns[i]
            valid = np.isfinite(r_i)
            # Find time steps where both r_i and ALL K factors are valid
            f_valid = np.all(np.isfinite(F), axis=0)
            both = valid & f_valid
            if np.sum(both) < K + 5:
                continue  # insufficient overlap — leave residual as raw returns
            f_sub = F[:, both]  # (K, T_valid)
            r_sub = r_i[both]  # (T_valid,)
            # OLS: b = (F F^T)^{-1} F r
            try:
                FtF = f_sub @ f_sub.T  # (K, K)
                Ftr = f_sub @ r_sub  # (K,)
                b = np.linalg.solve(FtF + 1e-8 * np.eye(K), Ftr)
                # Residual only at valid time steps
                residuals[i, both] = r_sub - b @ f_sub
            except np.linalg.LinAlgError:
                pass  # singular — leave as raw

        return residuals, K

    @staticmethod
    def validate_pair(
        sym_a: str,
        sym_b: str,
        idx_a: int,  # row index in returns/residuals matrix
        idx_b: int,
        residuals: np.ndarray,  # (N, T) residual returns
        K: int,
        tf_label: str,
        alpha: float = 0.05,
    ) -> Dict[str, Any]:
        """
        Run EG cointegration on the idiosyncratic residual log-price series.

        Reconstructs residual log-prices by cumulative sum of residual returns,
        then runs the same EG test as CointScanner on raw prices.
        """
        r_a = residuals[idx_a]
        r_b = residuals[idx_b]
        mask = np.isfinite(r_a) & np.isfinite(r_b)
        n = int(np.sum(mask))

        if n < 60:
            return {
                "eigenport_pvalue": None,
                "passes_eigenportfolio": None,
                "n_factors_removed": K,
                "confidence_tier": "silver",
                "note": "insufficient_overlap_for_residual_EG",
            }

        # Reconstruct cumulative residual log-prices
        cum_a = np.cumsum(r_a[mask])
        cum_b = np.cumsum(r_b[mask])

        try:
            from statsmodels.tsa.stattools import coint as eg_coint

            pval = float(eg_coint(cum_a, cum_b, maxlag=Config.ANALYSIS.EG_MAX_LAG)[1])
            passes = bool(pval < alpha)
            tier = "gold" if passes else "silver"
        except Exception:
            pval = None
            passes = None
            tier = "silver"

        return {
            "eigenport_pvalue": pval,
            "passes_eigenportfolio": passes,
            "n_factors_removed": K,
            "confidence_tier": tier,
        }

    @staticmethod
    def run_for_tf(
        confirmed_pairs: List[PairResult],
        returns: np.ndarray,  # full (N, T) returns matrix from UniverseFilter
        symbols: List[str],  # symbol order matching rows of returns
        corr: np.ndarray,  # (N, N) Pearson correlation matrix
        n_periods: int,  # T for MP threshold
        tf_label: str,
        alpha: float = 0.05,
    ) -> List[PairResult]:
        """
        Run eigenportfolio validation for all confirmed pairs at this TF.

        Returns updated PairResult list with eigenport_pvalue,
        passes_eigenportfolio, n_factors_removed, and confidence_tier filled in.
        """
        if not confirmed_pairs or returns.size == 0:
            return confirmed_pairs

        BiasAuditLog.record(
            bias_type="factor_contamination",
            classification="statistical",
            mechanism="Raw EG cointegration may detect shared factor exposure "
            "(market, sector, style) rather than genuine idiosyncratic "
            "co-movement. Factor-contaminated pairs produce false signals.",
            remedy="Eigenportfolio decomposition projects out Marchenko-Pastur "
            f"justified systematic factors (K determined by λ+ threshold). "
            f"EG re-run on residuals. Gold tier = confirmed by both.",
            scope=f"tf={tf_label}",
            residual_risk="OLS projection itself may have finite-sample bias; "
            "small K mis-estimates the factor space",
        )

        log.info(
            f"  [{tf_label}] Eigenportfolio validation on "
            f"{len(confirmed_pairs)} pairs..."
        )
        t0 = time.time()

        # Compute factor residuals once for this TF
        residuals, K = EigenportfolioDecomposer.compute_factor_residuals(
            returns, corr, n_periods
        )
        log.info(
            f"  [{tf_label}]   K={K} systematic factors removed "
            f"(MP λ+={EigenportfolioDecomposer.marchenko_pastur_threshold(returns.shape[0], n_periods)[0]:.3f})"
        )

        # Build symbol → index map
        sym_to_idx = {s: i for i, s in enumerate(symbols)}

        updated = []
        n_gold = 0
        for pr in confirmed_pairs:
            idx_a = sym_to_idx.get(pr.symbol_a)
            idx_b = sym_to_idx.get(pr.symbol_b)
            if idx_a is None or idx_b is None:
                # Symbol not in returns matrix — mark as silver (can't validate)
                import dataclasses

                pr = dataclasses.replace(
                    pr,
                    eigenport_pvalue=None,
                    passes_eigenportfolio=None,
                    n_factors_removed=K,
                    confidence_tier="silver",
                )
            else:
                result = EigenportfolioDecomposer.validate_pair(
                    pr.symbol_a,
                    pr.symbol_b,
                    idx_a,
                    idx_b,
                    residuals,
                    K,
                    tf_label,
                    alpha,
                )
                import dataclasses

                pr = dataclasses.replace(pr, **result)
                if result.get("passes_eigenportfolio"):
                    n_gold += 1

            updated.append(pr)

        log.info(
            f"  [{tf_label}]   Eigenportfolio: {n_gold}/{len(updated)} Gold tier "
            f"(idiosyncratic) | {len(updated)-n_gold} Silver tier (factor-driven) "
            f"in {time.time()-t0:.1f}s"
        )
        return updated


class HedgeRatioEstimator:
    """
    Three hedge ratio estimation methods, all computed for every confirmed pair.

    OLS (primary):     β = cov(A,B) / var(B). Directional — assumes B drives A.
                       Rolling 252-day window for the time series, plus a
                       full-sample point estimate.

    TLS (comparison):  Total Least Squares via SVD. Stack centered log-prices
                       into a 2×N matrix, compute SVD, hedge ratio = V[0,0]/V[1,0]
                       (first right singular vector). Symmetric — both variables
                       have measurement error. Useful for cross-asset pairs where
                       neither leg obviously "leads" the other.

    Kalman (comparison): Dynamic hedge ratio as a Kalman filter state.
                       State equation:  β_t = β_{t-1} + w  (w ~ N(0, Q))
                       Observation:     log_A_t = β_t * log_B_t + v  (v ~ N(0, R))
                       Q and R are calibrated on the first 252 bars and held
                       fixed thereafter to avoid lookahead.

    Bias notes:
      - Rolling OLS uses only data up to current bar — no lookahead.
      - Kalman Q/R calibrated on initial window only.
      - TLS as a point estimate uses full sample (documented).
    """

    @staticmethod
    def ols_rolling(
        log_a: np.ndarray,
        log_b: np.ndarray,
        window: int = 252,
    ) -> Tuple[np.ndarray, float]:
        """
        Rolling OLS hedge ratio.
        Returns (rolling_series, full_sample_point_estimate).

        For each bar t ≥ window, β_t = cov(A[t-window:t], B[t-window:t]) /
                                       var(B[t-window:t])
        Bars before the window are NaN.
        """
        n = log_a.size
        out = np.full(n, np.nan, dtype=float)
        if n < window:
            # Full sample as fallback
            mask = np.isfinite(log_a) & np.isfinite(log_b)
            if np.sum(mask) < 10:
                return out, np.nan
            a = log_a[mask] - np.nanmean(log_a[mask])
            b = log_b[mask] - np.nanmean(log_b[mask])
            var_b = np.dot(b, b)
            beta_full = float(np.dot(a, b) / var_b) if var_b > 0 else np.nan
            return out, beta_full

        for t in range(window - 1, n):
            a_w = log_a[t - window + 1 : t + 1]
            b_w = log_b[t - window + 1 : t + 1]
            mask = np.isfinite(a_w) & np.isfinite(b_w)
            if np.sum(mask) < window // 2:
                continue
            a = a_w[mask] - a_w[mask].mean()
            b = b_w[mask] - b_w[mask].mean()
            var_b = np.dot(b, b)
            if var_b > 0:
                out[t] = np.dot(a, b) / var_b

        # Full sample point estimate
        mask = np.isfinite(log_a) & np.isfinite(log_b)
        a = log_a[mask] - log_a[mask].mean()
        b = log_b[mask] - log_b[mask].mean()
        var_b = np.dot(b, b)
        beta_full = float(np.dot(a, b) / var_b) if var_b > 0 else np.nan

        return out, beta_full

    @staticmethod
    def tls(log_a: np.ndarray, log_b: np.ndarray) -> float:
        """
        Total Least Squares hedge ratio via SVD.

        For two series A, B with measurement error in both, the TLS solution
        minimizes orthogonal distances rather than vertical (OLS) distances.

        Method:
            Center each series. Stack as X = [a; b] (2 × N).
            Compute SVD: X = U Σ V^T
            The minor singular vector (last column of U) defines the orthogonal
            regression direction. Hedge ratio = -U[0,1] / U[1,1] gives slope
            of B on A in TLS sense.
        """
        mask = np.isfinite(log_a) & np.isfinite(log_b)
        a = log_a[mask]
        b = log_b[mask]
        if a.size < 30:
            return np.nan
        a = a - a.mean()
        b = b - b.mean()
        X = np.vstack([a, b])  # shape (2, N)
        try:
            U, _S, _Vt = scipy_svd(X, full_matrices=False)
            # Last column of U is the minor direction
            # The TLS hedge ratio for predicting a from b:
            #   slope = -U[0,-1] / U[1,-1]
            if abs(U[1, -1]) < 1e-12:
                return np.nan
            return float(-U[0, -1] / U[1, -1])
        except Exception:
            return np.nan

    @staticmethod
    def kalman(
        log_a: np.ndarray,
        log_b: np.ndarray,
        calib_bars: int = 252,
    ) -> Tuple[np.ndarray, float]:
        """
        Dynamic hedge ratio via Kalman filter.

        State:        β_t = β_{t-1} + w_t,  w_t ~ N(0, Q)
        Observation:  a_t = β_t * b_t + v_t,  v_t ~ N(0, R)

        Q (process noise) and R (observation noise) are estimated on the
        first calib_bars observations using maximum likelihood (simple
        method-of-moments equivalent: Q = small fraction of var(β_ols),
        R = var of OLS residuals). Then held fixed for the remainder of
        the series — this is the no-lookahead constraint.

        Returns (kalman_beta_series, mean_kalman_beta).
        """
        n = log_a.size
        beta = np.full(n, np.nan, dtype=float)

        # Use OLS rolling on calibration window to estimate Q, R
        if n < calib_bars + 10:
            # Fall back to single point estimate via OLS
            beta_ols, beta_full = HedgeRatioEstimator.ols_rolling(
                log_a, log_b, window=min(60, n // 2)
            )
            return beta_ols, beta_full

        # Calibration phase: fit OLS, get residual variance
        log_a_calib = log_a[:calib_bars]
        log_b_calib = log_b[:calib_bars]
        mask = np.isfinite(log_a_calib) & np.isfinite(log_b_calib)
        if np.sum(mask) < 30:
            beta_ols, beta_full = HedgeRatioEstimator.ols_rolling(log_a, log_b)
            return beta_ols, beta_full

        a0 = log_a_calib[mask]
        b0 = log_b_calib[mask]
        a0c = a0 - a0.mean()
        b0c = b0 - b0.mean()
        var_b = np.dot(b0c, b0c)
        beta0 = float(np.dot(a0c, b0c) / var_b) if var_b > 0 else 1.0
        residuals = a0 - beta0 * b0
        R = float(np.var(residuals))
        # Q chosen as small fraction so β evolves slowly — 1% of residual var per bar
        Q = max(R * 1e-5, 1e-10)

        # Run filter
        beta_prev = beta0
        P_prev = 1.0  # initial uncertainty
        for t in range(n):
            if not (np.isfinite(log_a[t]) and np.isfinite(log_b[t])):
                beta[t] = beta_prev
                continue
            # Predict
            beta_pred = beta_prev
            P_pred = P_prev + Q
            # Update
            obs = log_a[t]
            b_t = log_b[t]
            S = b_t * P_pred * b_t + R
            if S <= 0 or not np.isfinite(S):
                beta[t] = beta_pred
                P_prev = P_pred
                beta_prev = beta_pred
                continue
            K = P_pred * b_t / S
            beta_t = beta_pred + K * (obs - beta_pred * b_t)
            P_t = (1 - K * b_t) * P_pred
            beta[t] = beta_t
            beta_prev = beta_t
            P_prev = P_t

        # Mean Kalman beta (excluding calibration warmup)
        warmup = min(calib_bars // 2, n // 4)
        mean_beta = (
            float(np.nanmean(beta[warmup:])) if n > warmup else float(np.nanmean(beta))
        )
        return beta, mean_beta

    @staticmethod
    def estimate_all_for_pair(
        log_a: np.ndarray,
        log_b: np.ndarray,
        window: int = 252,
    ) -> Dict[str, Any]:
        """
        Compute all three hedge ratios for one pair. Returns dict with
        time series and point estimates.
        """
        ols_series, ols_point = HedgeRatioEstimator.ols_rolling(log_a, log_b, window)
        tls_point = HedgeRatioEstimator.tls(log_a, log_b)
        kalman_series, kalman_mean = HedgeRatioEstimator.kalman(log_a, log_b)
        return {
            "ols_series": ols_series,
            "ols_point": ols_point,
            "tls_point": tls_point,
            "kalman_series": kalman_series,
            "kalman_mean": kalman_mean,
        }


# =============================================================================
# CLASS 4 — SpreadModel
# =============================================================================


class SpreadModel:
    """
    Ornstein-Uhlenbeck spread model.

    The spread series for pair (A,B) with hedge ratio β is:
        spread_t = log(A_t) - β * log(B_t)

    Under the OU model, the spread evolves as:
        d(spread) = -θ * (spread - μ) dt + σ dW
    Discrete-time AR(1) approximation:
        spread_t = α + φ * spread_{t-1} + ε_t
    where φ = exp(-θ Δt), so θ = -ln(φ) / Δt.

    Half-life of mean reversion: ln(2) / θ bars.
    A pair with φ=0.97 has half-life ≈ 23 bars.

    The model produces:
      - spread time series (with rolling hedge ratio applied bar-by-bar)
      - rolling z-score using 252-bar mean and std
      - expanding z-score using all data up to current bar
      - half-life (rolling estimates + median + full sample)
      - mean reversion speed θ
      - half-life trend slope (strategy decay signal)

    Bias notes:
      - Hedge ratio applied bar-by-bar is the rolling OLS estimate at that
        bar — no future data used.
      - Rolling and expanding both computed; rolling is primary.
    """

    @staticmethod
    def compute_spread(
        log_a: np.ndarray,
        log_b: np.ndarray,
        hedge_series: np.ndarray,
        hedge_static: float,
    ) -> np.ndarray:
        """
        spread_t = log_a_t - hedge_t * log_b_t

        For bars where hedge_series is NaN (early bars before rolling window
        fills), fall back to the static full-sample hedge ratio.
        """
        h = np.where(
            np.isfinite(hedge_series),
            hedge_series,
            hedge_static if np.isfinite(hedge_static) else 1.0,
        )
        with np.errstate(invalid="ignore"):
            spread = log_a - h * log_b
        return spread

    @staticmethod
    def rolling_zscore(spread: np.ndarray, window: int) -> np.ndarray:
        """
        Rolling z-score: (x - rolling_mean) / rolling_std, same window for
        both — that shared-window property is what makes "z > 2" mean
        "2 std devs from this series' own typical range". A decoupled,
        shorter window for std (tried and measured, see fit_pair's
        docstring / DEVELOPMENT.md BUG-D45) breaks that guarantee whenever
        the spread drifts at all, producing a systematically biased z-score
        rather than a more vol-responsive one.
        """
        n = spread.size
        z = np.full(n, np.nan, dtype=float)
        if n < Config.ANALYSIS.OU_WINDOW_MIN_BARS:
            return z
        s = pd.Series(spread)
        mu = s.rolling(window, min_periods=max(2, window // 2)).mean()
        sd = s.rolling(window, min_periods=max(2, window // 2)).std(ddof=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            z_ser = (s - mu) / sd
        z[:] = z_ser.values
        return z

    @staticmethod
    def _adaptive_window(half_life: float, mult: float, min_bars: int, max_bars: int) -> int:
        """window ~= mult x half_life, clipped to [min_bars, max_bars]. Falls
        back to max_bars when half-life is NaN/degenerate."""
        if not np.isfinite(half_life) or half_life <= 0:
            return max_bars
        return int(np.clip(round(mult * half_life), min_bars, max_bars))

    @staticmethod
    def expanding_zscore(spread: np.ndarray, min_periods: int = 60) -> np.ndarray:
        """Expanding z-score: uses all data from start to current bar."""
        s = pd.Series(spread)
        mu = s.expanding(min_periods=min_periods).mean()
        sd = s.expanding(min_periods=min_periods).std(ddof=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            z = (s - mu) / sd
        return z.values

    @staticmethod
    def half_life_ar1(spread: np.ndarray) -> float:
        """
        Half-life from AR(1) fit:
            spread_t = α + φ * spread_{t-1} + ε
            half_life = -ln(2) / ln(φ),  valid when 0 < φ < 1
        """
        s = spread[np.isfinite(spread)]
        if s.size < 30:
            return np.nan
        s_lag = s[:-1]
        s_now = s[1:]
        if s_lag.size < 30:
            return np.nan
        # OLS: s_now = α + φ * s_lag
        s_lag_c = s_lag - s_lag.mean()
        s_now_c = s_now - s_now.mean()
        var_lag = np.dot(s_lag_c, s_lag_c)
        if var_lag <= 0:
            return np.nan
        phi = float(np.dot(s_lag_c, s_now_c) / var_lag)
        if phi <= 0 or phi >= 1:
            return np.nan
        return float(-np.log(2) / np.log(phi))

    @staticmethod
    def rolling_half_life(
        spread: np.ndarray,
        window: int = 252,
        step: int = 21,
    ) -> np.ndarray:
        """
        Rolling half-life estimates. Returns array of length len(spread)
        with NaN before the first full window, then half-life at each
        step-spaced point.
        """
        n = spread.size
        hl = np.full(n, np.nan, dtype=float)
        if n < window:
            return hl
        for t in range(window - 1, n, step):
            seg = spread[t - window + 1 : t + 1]
            h = SpreadModel.half_life_ar1(seg)
            # forward-fill so the value persists until next refresh
            hl[t] = h
        # Forward-fill the step gaps
        hl = pd.Series(hl).ffill().values
        return hl

    @staticmethod
    def half_life_trend_slope(hl_series: np.ndarray) -> float:
        """
        Linear regression of half-life on time index.
        Positive slope = half-life increasing = mean reversion slowing
        = pair relationship decaying.
        """
        mask = np.isfinite(hl_series)
        if np.sum(mask) < 10:
            return np.nan
        t = np.arange(hl_series.size)[mask].astype(float)
        y = hl_series[mask]
        # Standard OLS slope
        t_c = t - t.mean()
        y_c = y - y.mean()
        var_t = np.dot(t_c, t_c)
        if var_t <= 0:
            return np.nan
        return float(np.dot(t_c, y_c) / var_t)

    @staticmethod
    def mean_reversion_speed(half_life: float) -> float:
        """θ = ln(2) / half_life."""
        if not np.isfinite(half_life) or half_life <= 0:
            return np.nan
        return float(np.log(2) / half_life)

    @staticmethod
    def fit_pair(
        log_a: np.ndarray,
        log_b: np.ndarray,
        hedge_series: np.ndarray,
        hedge_static: float,
        clean_mask: Optional[np.ndarray] = None,
    ) -> Dict[str, Any]:
        """
        Compute full spread model for one pair. Returns dict with all
        time series and scalar summaries.

        Rolling mean/std/half-life are computed on TRADING BARS ONLY
        (clean_mask True), not the full 24/7-reindexed calendar that
        DataAligner.align_intraday() forward-fills for intraday TFs.
        Without this, the first real bar after any gap longer than the
        rolling window sits in a window of (window-1) identical
        forward-filled values plus 1 real value — a degenerate case whose
        z-score is EXACTLY (window-1)/sqrt(window) regardless of the
        actual price move (BUG-D45, DEVELOPMENT.md), not a real
        divergence signal. clean_mask=None (e.g. the IBKR deep-history
        enrichment path, which carries no gap_flag) treats every bar as
        real — documented limitation there, not a bug here.

        The window itself is adaptive per pair rather than one fixed bar
        count applied uniformly across every TF: window ~=
        OU_WINDOW_HALFLIFE_MULT_MEAN x half-life, spanning several
        reversion cycles for a stable mean/std estimate.

        Mean and std deliberately use the SAME window here (verified
        empirically, not just by theory — see DEVELOPMENT.md BUG-D45): an
        earlier version used a shorter, separately-scaled window for std
        only (current-volatility-responsive), but on real data this
        decouples the z-score from its own textbook mean=0/std=1-over-its-
        window property — if the spread drifts at all over the longer mean
        window, a fast-shrinking std denominator amplifies that lag into a
        systematic bias (tested on CRWD/DDOG: mean -1.5, std 7.1, 12% of
        bars |z|>10, vs. mean -0.05..0.11, std 1.4-1.7, ~0.1% |z|>10 once
        mean and std share one window). Volatility-regime information is
        better surfaced as a separate diagnostic feature than baked into
        the entry signal's own denominator — not yet built, see
        DEVELOPMENT.md.
        """
        spread = SpreadModel.compute_spread(log_a, log_b, hedge_series, hedge_static)
        n = spread.size
        if clean_mask is None:
            clean_mask = np.ones(n, dtype=bool)
        real_pos = np.flatnonzero(clean_mask & np.isfinite(spread))
        spread_real = spread[real_pos]

        cfg = Config.ANALYSIS
        hl_full = SpreadModel.half_life_ar1(spread_real)
        mean_window = SpreadModel._adaptive_window(
            hl_full, cfg.OU_WINDOW_HALFLIFE_MULT_MEAN, cfg.OU_WINDOW_MIN_BARS, cfg.OU_LOOKBACK_DAYS
        )

        z_real = SpreadModel.rolling_zscore(spread_real, mean_window)
        z_exp_real = SpreadModel.expanding_zscore(spread_real)
        hl_roll_real = SpreadModel.rolling_half_life(spread_real, window=mean_window)

        z_rolling = np.full(n, np.nan, dtype=float)
        z_expanding = np.full(n, np.nan, dtype=float)
        hl_rolling = np.full(n, np.nan, dtype=float)
        z_rolling[real_pos] = z_real
        z_expanding[real_pos] = z_exp_real
        hl_rolling[real_pos] = hl_roll_real

        hl_rolling_median = (
            float(np.nanmedian(hl_roll_real))
            if np.any(np.isfinite(hl_roll_real))
            else np.nan
        )
        trend_slope = SpreadModel.half_life_trend_slope(hl_roll_real)
        theta = SpreadModel.mean_reversion_speed(hl_full)

        return {
            "spread": spread,
            "z_rolling": z_rolling,
            "z_expanding": z_expanding,
            "half_life_full": hl_full,
            "half_life_rolling_series": hl_rolling,
            "half_life_rolling_median": hl_rolling_median,
            "half_life_trend_slope": trend_slope,
            "mean_reversion_speed": theta,
            "window": mean_window,
        }


# =============================================================================
# CLASS 5 — VolumeStructure
# =============================================================================


# =============================================================================
# CLASS: HurstEstimator
# =============================================================================


class HurstEstimator:
    """
    Estimates the Hurst exponent of a spread series using two methods.

    WHY HURST FOR SPREADS:
    EG cointegration is a binary pass/fail. Hurst provides a continuous
    quality score: H measures whether the spread is genuinely anti-persistent
    (mean-reverting) beyond just being stationary. Pairs with H further below
    0.5 revert faster and more reliably — directly predicting strategy quality.

    CRITICAL IMPLEMENTATION NOTE — operate on INCREMENTS for R/S:
    For an OU/AR(1) spread s[t] with AR coefficient φ:
      - Levels: ρ_levels(lag-1) = φ > 0 → R/S on levels gives H > 0.5 even
        for strongly mean-reverting spreads. NOT diagnostic.
      - Increments Δs[t] = s[t]-s[t-1]: ρ_1(Δs) = (φ-1)/(2-φ) < 0 for φ<1.
        R/S on increments gives H < 0.5 for OU → correct for mean-reversion.

    1. R/S (Rescaled Range) — Hurst 1951, applied to spread INCREMENTS.
       Fast O(N log N). Slight finite-sample upward bias; use 20+ scales.

    2. DFA (Detrended Fluctuation Analysis) — Peng et al. 1994, applied to
       spread LEVELS via integration profile. More robust to non-stationarity.
       Slower O(N × n_scales). Comparison/robustness check against R/S.

    Interpretation:
       H < 0.45 — strongly mean-reverting
       H < 0.50 — mean-reverting (passes ML gate)
       H ≈ 0.50 — near random walk (borderline)
       H > 0.50 — persistent/trending (fails ML gate)

    ML gate: hurst_rs < 0.50 required. Where |H_rs - H_dfa| > 0.10,
    estimation is flagged as uncertain (structural breaks likely).
    """

    MIN_BARS = 100
    ML_GATE = 0.50

    @staticmethod
    def _ols_slope(x: np.ndarray, y: np.ndarray) -> float:
        if len(x) < 3:
            return np.nan
        x_c = x - x.mean()
        denom = np.dot(x_c, x_c)
        return float(np.dot(x_c, y - y.mean()) / denom) if denom > 1e-12 else np.nan

    @staticmethod
    def _log_scales(
        n_obs: int, min_win: int = 8, max_ratio: float = 0.25, n_pts: int = 20
    ) -> np.ndarray:
        max_win = max(min_win + 1, int(n_obs * max_ratio))
        return np.unique(
            np.round(np.logspace(np.log10(min_win), np.log10(max_win), n_pts)).astype(
                int
            )
        )

    @staticmethod
    def hurst_rs(spread: np.ndarray) -> float:
        """
        R/S Hurst on spread INCREMENTS.

        Increments of an OU process have negative lag-1 autocorrelation
        (phi-1)/(2-phi) < 0, yielding H < 0.5. Operating on levels would
        give H > 0.5 for high-phi OU due to positive level autocorrelation.
        """
        s = spread[np.isfinite(spread)]
        inc = np.diff(s)  # <- INCREMENTS, not levels
        n = inc.size
        if n < HurstEstimator.MIN_BARS:
            return np.nan
        scales = HurstEstimator._log_scales(n)
        log_n, log_rs = [], []
        for win in scales:
            n_win = n // win
            if n_win < 2:
                continue
            rs_vals = []
            for i in range(n_win):
                w = inc[i * win : (i + 1) * win]
                mu = w.mean()
                cd = np.cumsum(w - mu)
                R = cd.max() - cd.min()
                S = w.std(ddof=1)
                if S > 1e-12 and R > 0:
                    rs_vals.append(R / S)
            if len(rs_vals) >= 2:
                log_n.append(np.log(float(win)))
                log_rs.append(np.log(float(np.mean(rs_vals))))
        H = HurstEstimator._ols_slope(np.array(log_n), np.array(log_rs))
        return float(np.clip(H, 0.0, 1.0)) if np.isfinite(H) else np.nan

    @staticmethod
    def hurst_dfa(spread: np.ndarray) -> float:
        """
        DFA Hurst on spread INCREMENTS via integration profile.

        Like R/S, DFA is applied to the increments of the spread (first
        differences). The DFA profile Y(k) = cumsum(Δs - mean(Δs)).
        For iid increments (random walk spread): Y is Brownian → H_dfa ≈ 0.5.
        For negatively autocorrelated increments (OU spread): Y is anti-persistent
        → H_dfa < 0.5.

        DFA is more robust than R/S when increments have non-stationarity or
        slow structural shifts — detrending within each window absorbs these.
        """
        s = spread[np.isfinite(spread)]
        inc = np.diff(s)  # operate on INCREMENTS (same as R/S)
        n = inc.size
        if n < HurstEstimator.MIN_BARS:
            return np.nan
        Y = np.cumsum(inc - inc.mean())  # DFA integration profile of increments
        scales = HurstEstimator._log_scales(n)
        log_n, log_fn = [], []
        for win in scales:
            n_win = n // win
            if n_win < 2:
                continue
            t = np.arange(float(win))
            t_c = t - t.mean()
            tv = np.dot(t_c, t_c)
            if tv < 1e-12:
                continue
            fn_sq = []
            for i in range(n_win):
                seg = Y[i * win : (i + 1) * win]
                slope = np.dot(t_c, seg - seg.mean()) / tv
                resid = seg - (seg.mean() + slope * t_c)
                fn_sq.append(float(np.mean(resid**2)))
            if fn_sq:
                F = np.sqrt(np.mean(fn_sq))
                if F > 1e-12:
                    log_n.append(np.log(float(win)))
                    log_fn.append(np.log(F))
        H = HurstEstimator._ols_slope(np.array(log_n), np.array(log_fn))
        return float(np.clip(H, 0.0, 1.0)) if np.isfinite(H) else np.nan

    @staticmethod
    def estimate(spread: np.ndarray) -> Dict[str, Any]:
        """Compute both H estimates and return full diagnostic dict."""
        h_rs = HurstEstimator.hurst_rs(spread)
        h_dfa = HurstEstimator.hurst_dfa(spread)
        div = (
            abs(h_rs - h_dfa) if (np.isfinite(h_rs) and np.isfinite(h_dfa)) else np.nan
        )
        if np.isfinite(h_rs):
            if h_rs < 0.40:
                interp = "strongly_mean_reverting"
            elif h_rs < 0.50:
                interp = "mean_reverting"
            elif h_rs < 0.55:
                interp = "near_random_walk"
            else:
                interp = "trending"
        else:
            interp = "insufficient_data"
        return {
            "hurst_rs": float(h_rs) if np.isfinite(h_rs) else None,
            "hurst_dfa": float(h_dfa) if np.isfinite(h_dfa) else None,
            "hurst_divergence": float(div) if np.isfinite(div) else None,
            "passes_ml_gate": bool(np.isfinite(h_rs) and h_rs < HurstEstimator.ML_GATE),
            "interpretation": interp,
        }


class VolumeStructure:
    """
    Volume- and microstructure-based features computed per asset bar.

    Inputs: an aligned DataFrame with columns [open, high, low, close, volume, vwap].
    Outputs: a feature DataFrame indexed by the same DatetimeIndex.

    Features computed:
      - relative_volume    : current bar volume / rolling N-day same-time-of-day average
      - dollar_volume      : close × volume
      - vwap_deviation     : (close - vwap) / vwap  — order flow pressure within bar
      - amihud_illiquidity : |return| / dollar_volume — high = thin market
      - cvd_proxy          : cumulative signed volume via tick rule
                             (close>open: +vol, close<open: -vol, eq: 0)
      - large_move_low_vol : flag |return| > 2σ AND volume < 0.5× rolling avg
      - high_vol_small_move: flag volume > 2× avg AND |return| < 0.5σ
      - vol_divergence     : price making N-bar high while volume declining
      - squeeze_indicator  : BBand width / Keltner width  — <1 = squeeze
      - rsi_14             : standard 14-period RSI
      - relative_vol_ratio : short-vol / long-vol (20 / 252)
      - returns            : log returns for downstream use

    Pair-level features (computed by AnalysisPipeline when iterating pairs):
      - cross_leg_rsi_divergence  : (RSI_A - RSI_B) standardized
      - rolling_correlation_60d   : 60-bar rolling correlation of returns
      - rolling_correlation_252d  : 252-bar rolling correlation of returns
      - correlation_velocity      : first difference of rolling_correlation_60d, smoothed

    All features computed bar-by-bar using only past data (rolling windows
    are right-aligned). No lookahead bias by construction.
    """

    @staticmethod
    def compute_features(
        df: pd.DataFrame,
        relative_vol_window: int = 20,
        rsi_period: int = 14,
        bb_period: int = 20,
        bb_std: float = 2.0,
        atr_period: int = 14,
        squeeze_period: int = 20,
        vol_short: int = 20,
        vol_long: int = 252,
    ) -> pd.DataFrame:
        """
        Compute the full feature set for one asset's price DataFrame.

        Returns a new DataFrame with the same index and all feature columns.
        Missing 'vwap' column (e.g. yfinance data) is handled by using
        the typical price (H+L+C)/3 as a proxy.
        """
        # Mask DATA_GAP bars to NaN before any feature computation. Found
        # overnight (2026-06-23): this previously used raw OHLC values with
        # no gap_flag masking at all — the BUG-D45 contamination mechanism,
        # particularly severe here since RSI's Wilder smoothing is a
        # sequential recursive filter, so a contaminated run early in the
        # series propagates forward indefinitely, not just at the gap
        # boundary. Partial fix: masks inputs at the source (fixes RSI and
        # every .rolling()-based feature below, which already skip NaN
        # correctly); NOT a verified line-by-line audit of every downstream
        # sub-calculation's NaN-propagation behavior (e.g. cumsum-based
        # cvd_proxy) — flagged for a dedicated follow-up pass, not yet a
        # consumer of ml.py (Stage 2, unimplemented) so lower urgency than
        # the Hurst/decay-test/Johansen fixes applied the same night.
        out = pd.DataFrame(index=df.index)
        _clean = clean_close(df, exclude_flags=(GapFlag.DATA_GAP,))
        _gap_mask = ~np.isfinite(_clean)
        open_ = df["open"].values.astype(float).copy() if "open" in df.columns else df["close"].values.astype(float).copy()
        high = df["high"].values.astype(float).copy() if "high" in df.columns else df["close"].values.astype(float).copy()
        low = df["low"].values.astype(float).copy() if "low" in df.columns else df["close"].values.astype(float).copy()
        close = df["close"].values.astype(float).copy()
        open_[_gap_mask] = np.nan
        high[_gap_mask] = np.nan
        low[_gap_mask] = np.nan
        close[_gap_mask] = np.nan
        volume = df["volume"].values if "volume" in df.columns else np.ones_like(close)
        if "vwap" in df.columns and df["vwap"].notna().any():
            vwap = df["vwap"].values
        else:
            # Typical price proxy when VWAP unavailable (yfinance data)
            vwap = (high + low + close) / 3.0

        # Log returns
        with np.errstate(invalid="ignore", divide="ignore"):
            ret = np.zeros_like(close, dtype=float)
            ret[1:] = np.log(close[1:] / close[:-1])
            # NaN, not zero, at any gap-touching or numerically-degenerate
            # return — see masking note above; zeroing would re-introduce
            # the same contamination this fix removes.
            ret[~np.isfinite(ret)] = np.nan
        out["returns"] = ret

        # Dollar volume
        out["dollar_volume"] = close * volume

        # Relative volume (rolling N-day average)
        # Note: for proper time-of-day normalization we'd group by bar time;
        # for now use rolling mean which is correct for daily and a reasonable
        # approximation for intraday. Full time-of-day grouping in future revision.
        vol_s = pd.Series(volume, index=df.index)
        vol_rolling_mean = vol_s.rolling(relative_vol_window, min_periods=5).mean()
        with np.errstate(invalid="ignore", divide="ignore"):
            rel_vol = np.where(
                vol_rolling_mean.values > 0,
                volume / vol_rolling_mean.values,
                np.nan,
            )
        out["relative_volume"] = rel_vol

        # VWAP deviation
        with np.errstate(invalid="ignore", divide="ignore"):
            vwap_dev = np.where(vwap > 0, (close - vwap) / vwap, np.nan)
        out["vwap_deviation"] = vwap_dev

        # Amihud illiquidity: |return| / dollar_volume (scaled for readability)
        with np.errstate(invalid="ignore", divide="ignore"):
            dv = out["dollar_volume"].values
            amihud = np.where(dv > 0, np.abs(ret) / dv, np.nan)
        # Scale by 1e6 so typical values are O(1) instead of O(1e-9)
        out["amihud_illiquidity"] = amihud * 1e6

        # CVD proxy via tick rule
        sign = np.where(close > open_, 1.0, np.where(close < open_, -1.0, 0.0))
        signed_vol = sign * volume
        out["cvd_proxy"] = np.cumsum(signed_vol)

        # Large move / low volume flag
        # 2σ return = mean ± 2 * rolling std of returns
        ret_s = pd.Series(ret, index=df.index)
        ret_std = ret_s.rolling(relative_vol_window, min_periods=5).std(ddof=1)
        with np.errstate(invalid="ignore"):
            move_2sd = np.abs(ret) > (2.0 * ret_std.values)
            vol_low = (vol_rolling_mean.values > 0) & (
                volume < 0.5 * vol_rolling_mean.values
            )
            vol_high = (vol_rolling_mean.values > 0) & (
                volume > 2.0 * vol_rolling_mean.values
            )
            move_small = np.abs(ret) < (0.5 * ret_std.values)
        out["large_move_low_vol"] = (move_2sd & vol_low).astype(int)
        out["high_vol_small_move"] = (vol_high & move_small).astype(int)

        # Volume divergence: price 20-bar high while volume declining
        close_s = pd.Series(close, index=df.index)
        close_max20 = close_s.rolling(20, min_periods=10).max()
        # Check if current bar is at the 20-bar high
        at_high = close == close_max20.values
        vol_slope20 = (
            pd.Series(volume, index=df.index)
            .rolling(20, min_periods=10)
            .apply(
                lambda x: (
                    float(np.polyfit(np.arange(x.size), x, 1)[0])
                    if x.size >= 5
                    else np.nan
                ),
                raw=True,
            )
        )
        out["vol_divergence"] = ((at_high) & (vol_slope20.values < 0)).astype(int)

        # Squeeze indicator: BB width / Keltner width
        close_mean20 = close_s.rolling(bb_period, min_periods=5).mean()
        close_std20 = close_s.rolling(bb_period, min_periods=5).std(ddof=1)
        bb_width = 4.0 * close_std20.values  # 2σ above and below

        # ATR
        high_s = pd.Series(high, index=df.index)
        low_s = pd.Series(low, index=df.index)
        prev_close = close_s.shift(1)
        tr = np.maximum.reduce(
            [
                (high_s - low_s).values,
                (high_s - prev_close).abs().values,
                (low_s - prev_close).abs().values,
            ]
        )
        atr = pd.Series(tr, index=df.index).rolling(atr_period, min_periods=5).mean()
        kc_width = 4.0 * atr.values

        with np.errstate(invalid="ignore", divide="ignore"):
            squeeze = np.where(kc_width > 0, bb_width / kc_width, np.nan)
        out["squeeze_indicator"] = squeeze

        # RSI (Wilder smoothing)
        out["rsi_14"] = VolumeStructure._rsi(close, rsi_period)

        # Relative vol ratio (short / long)
        ret_short = ret_s.rolling(vol_short, min_periods=5).std(ddof=1)
        ret_long = ret_s.rolling(vol_long, min_periods=20).std(ddof=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            relvol_ratio = np.where(
                ret_long.values > 0, ret_short.values / ret_long.values, np.nan
            )
        out["relative_vol_ratio"] = relvol_ratio

        return out

    @staticmethod
    def _rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
        """Standard Wilder RSI."""
        n = close.size
        rsi = np.full(n, np.nan, dtype=float)
        if n <= period:
            return rsi
        diff = np.diff(close, prepend=close[0])
        gains = np.where(diff > 0, diff, 0.0)
        losses = np.where(diff < 0, -diff, 0.0)
        # First average using simple mean
        avg_gain = np.mean(gains[1 : period + 1])
        avg_loss = np.mean(losses[1 : period + 1])
        for t in range(period + 1, n):
            avg_gain = (avg_gain * (period - 1) + gains[t]) / period
            avg_loss = (avg_loss * (period - 1) + losses[t]) / period
            if avg_loss == 0:
                rsi[t] = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi[t] = 100.0 - (100.0 / (1.0 + rs))
        return rsi

    @staticmethod
    def pair_features(
        features_a: pd.DataFrame,
        features_b: pd.DataFrame,
        returns_a: np.ndarray,
        returns_b: np.ndarray,
    ) -> pd.DataFrame:
        """
        Compute cross-leg features for a pair: cross-leg RSI divergence,
        rolling correlations (60d, 252d), correlation velocity.

        Both inputs share the same DatetimeIndex post-alignment.
        """
        idx = features_a.index
        out = pd.DataFrame(index=idx)

        # Cross-leg RSI divergence — standardized
        rsi_diff = features_a["rsi_14"].values - features_b["rsi_14"].values
        rsi_diff_s = pd.Series(rsi_diff, index=idx)
        rsi_std = rsi_diff_s.rolling(60, min_periods=20).std(ddof=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            out["cross_leg_rsi_divergence"] = np.where(
                rsi_std.values > 0,
                rsi_diff / rsi_std.values,
                np.nan,
            )

        # Rolling correlations
        ra = pd.Series(returns_a, index=idx)
        rb = pd.Series(returns_b, index=idx)
        out["rolling_corr_60d"] = ra.rolling(60, min_periods=20).corr(rb).values
        out["rolling_corr_252d"] = ra.rolling(252, min_periods=60).corr(rb).values

        # Correlation velocity = smoothed first difference of 60d rolling correlation
        corr60_diff = pd.Series(out["rolling_corr_60d"], index=idx).diff()
        out["correlation_velocity"] = (
            corr60_diff.rolling(10, min_periods=3).mean().values
        )

        return out


# =============================================================================
# CLASS 6 — RegimeClassifier
# =============================================================================


class RegimeClassifier:
    """
    Three regime classification methods, all run and compared:

      K-means : hard cluster assignment, no temporal structure.
                Auto-K via silhouette score (max over K=2..6).

      GMM     : soft probabilistic assignment via Gaussian mixture.
                Auto-K via BIC (min over K=2..6).
                Output includes regime probabilities for ML layer.

      HMM     : Gaussian HMM with state transitions — adds temporal
                persistence not present in K-means or GMM.
                Auto-K via BIC (min over K=2..6).
                Output includes transition matrix and dwell times.

    Feature construction:
      Raw per-bar features:
        - realized_vol         : rolling 20-bar std of returns
        - trend_strength       : |rolling 20-bar return| / rolling vol
        - mean_reversion_speed : AR(1) phi on rolling window
        - relative_vol_ratio   : already in VolumeStructure output

      These are then aggregated over rolling windows of 10, 20, 40 bars
      (test all three, select the one producing highest silhouette / lowest BIC).

      Before clustering, every feature is divided by its own rolling std
      so the classifier responds to RELATIVE structure rather than absolute level.

    Bias notes:
      - Expanding-window constraint: classifier at time T fitted only on data
        up to T. Practically implemented by re-fitting every 63 bars (quarterly
        for daily data) on all data up to refit date.
      - For the full-run analysis output we report the FINAL-fit classifier
        on the full sample (used by ml.py for feature extraction). For
        WFA in backtest.py, the rolling-refit machinery is invoked there.
      - Logged in BiasAuditLog.
    """

    @staticmethod
    def build_raw_features(df: pd.DataFrame, vol_window: int = 20) -> pd.DataFrame:
        """
        Compute per-bar regime features for one asset.
        Returns DataFrame with columns:
            realized_vol, trend_strength, mean_reversion_speed, relative_vol_ratio
        """
        # clean_close masks DATA_GAP bars to NaN before logging. Found
        # overnight (2026-06-23): this previously used raw df["close"].values
        # with no gap_flag masking, the BUG-D45 contamination mechanism —
        # every overnight/weekend run is forward-filled, producing a long
        # run of literal zero returns (real[t]==real[t-1] after fill) that
        # got explicitly zero-filled (not NaN-filled) below, treating
        # excluded padding as real zero-return observations feeding
        # realized_vol/trend_strength/mean_reversion_speed for every
        # intraday-TF regime fit and the persisted per-bar regime labels.
        close = clean_close(df, exclude_flags=(GapFlag.DATA_GAP,))
        with np.errstate(invalid="ignore", divide="ignore"):
            ret = np.zeros_like(close, dtype=float)
            ret[1:] = np.log(close[1:] / close[:-1])
            # NaN, not zero — pandas .rolling() already skips NaN correctly;
            # zeroing would silently re-introduce the same contamination.
            ret[~np.isfinite(ret)] = np.nan

        ret_s = pd.Series(ret, index=df.index)
        realized_vol = ret_s.rolling(vol_window, min_periods=5).std(ddof=1)

        # Trend strength: |sum of recent returns| / rolling vol (normalized momentum)
        ret_sum = ret_s.rolling(vol_window, min_periods=5).sum().abs()
        trend_strength = (ret_sum / realized_vol).replace([np.inf, -np.inf], np.nan)

        # Mean reversion speed: rolling AR(1) phi estimate
        mr_phi = RegimeClassifier._rolling_ar1_phi(ret, window=vol_window)

        # Relative volatility ratio (short / long)
        ret_long = ret_s.rolling(252, min_periods=20).std(ddof=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            relvol = (realized_vol / ret_long).replace([np.inf, -np.inf], np.nan)

        return pd.DataFrame(
            {
                "realized_vol": realized_vol.values,
                "trend_strength": trend_strength.values,
                "mean_reversion_speed": mr_phi,
                "relative_vol_ratio": relvol.values,
            },
            index=df.index,
        )

    @staticmethod
    def _rolling_ar1_phi(ret: np.ndarray, window: int = 20) -> np.ndarray:
        """Rolling AR(1) phi coefficient on returns (a noisy mean reversion proxy)."""
        n = ret.size
        phi = np.full(n, np.nan, dtype=float)
        if n < window + 2:
            return phi
        for t in range(window, n):
            seg = ret[t - window : t]
            seg_lag = seg[:-1]
            seg_now = seg[1:]
            mask = np.isfinite(seg_lag) & np.isfinite(seg_now)
            if np.sum(mask) < 5:
                continue
            sl = seg_lag[mask] - seg_lag[mask].mean()
            sn = seg_now[mask] - seg_now[mask].mean()
            var = np.dot(sl, sl)
            if var > 0:
                phi[t] = np.dot(sl, sn) / var
        return phi

    @staticmethod
    def aggregate_features(
        features: pd.DataFrame,
        window: int,
    ) -> pd.DataFrame:
        """
        Rolling mean of features over `window` bars. The aggregation
        smooths bar-level noise and makes regime classification respond
        to persistent structural changes rather than single-bar volatility.
        """
        return features.rolling(window, min_periods=max(3, window // 3)).mean()

    @staticmethod
    def standardize(features: pd.DataFrame, vol_window: int = 252) -> pd.DataFrame:
        """
        Volatility-standardize: each feature divided by its own rolling std.
        Makes features dimensionless and scale-invariant so no single feature
        dominates clustering by scale.
        """
        out = pd.DataFrame(index=features.index)
        for col in features.columns:
            s = features[col]
            std = s.rolling(vol_window, min_periods=20).std(ddof=1)
            with np.errstate(invalid="ignore", divide="ignore"):
                out[col] = (s / std).replace([np.inf, -np.inf], np.nan)
        return out

    @staticmethod
    def fit_kmeans_auto_k(
        X: np.ndarray,
        k_min: int = 2,
        k_max: int = 6,
        seed: int = 42,
    ) -> Tuple[Any, int, float]:
        """
        Fit K-means for K = k_min..k_max, return best by silhouette.
        Returns (model, k, silhouette_score).
        """
        if not _SKLEARN_AVAILABLE or X.shape[0] < k_max * 5:
            return None, 0, np.nan
        best_model = None
        best_k = 0
        best_score = -np.inf
        for k in range(k_min, k_max + 1):
            try:
                km = KMeans(n_clusters=k, random_state=seed, n_init=10)
                labels = km.fit_predict(X)
                if len(set(labels)) < 2:
                    continue
                score = silhouette_score(
                    X, labels, sample_size=min(X.shape[0], 1000), random_state=seed
                )
                if score > best_score:
                    best_score = score
                    best_k = k
                    best_model = km
            except Exception:
                continue
        return (
            best_model,
            best_k,
            float(best_score) if np.isfinite(best_score) else np.nan,
        )

    @staticmethod
    def fit_gmm_auto_k(
        X: np.ndarray,
        k_min: int = 2,
        k_max: int = 6,
        seed: int = 42,
    ) -> Tuple[Any, int, float]:
        """
        Fit Gaussian Mixture Models for K = k_min..k_max, return best by BIC.
        """
        if not _SKLEARN_AVAILABLE or X.shape[0] < k_max * 5:
            return None, 0, np.nan
        best_model = None
        best_k = 0
        best_bic = np.inf
        for k in range(k_min, k_max + 1):
            try:
                gmm = GaussianMixture(
                    n_components=k, random_state=seed, covariance_type="full", n_init=3
                )
                gmm.fit(X)
                bic = gmm.bic(X)
                if bic < best_bic:
                    best_bic = bic
                    best_k = k
                    best_model = gmm
            except Exception:
                continue
        return best_model, best_k, float(best_bic) if np.isfinite(best_bic) else np.nan

    @staticmethod
    def fit_hmm_auto_k(
        X: np.ndarray,
        k_min: int = 2,
        k_max: int = 6,
        seed: int = 42,
    ) -> Tuple[Any, int, float]:
        """
        Fit Gaussian HMM for K = k_min..k_max, return best by BIC.
        BIC = -2 * log_likelihood + n_params * ln(N)
        For GaussianHMM with full covariance, n_params per state =
            k*(k-1)/2 transitions + d means + d*(d+1)/2 cov terms (per state)
        """
        if not _HMMLEARN_AVAILABLE or X.shape[0] < k_max * 10:
            return None, 0, np.nan
        best_model = None
        best_k = 0
        best_bic = np.inf
        n, d = X.shape
        for k in range(k_min, k_max + 1):
            try:
                hmm = GaussianHMM(
                    n_components=k,
                    covariance_type="full",
                    n_iter=200,
                    tol=1e-2,
                    random_state=seed,
                )
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", message="Model is not converging")
                    warnings.filterwarnings("ignore", message=".*transmat_.*zero sum.*")
                    hmm.fit(X)
                log_lik = hmm.score(X)
                # Parameter count
                n_params = (k - 1) + k * (k - 1) + k * d + k * d * (d + 1) / 2
                bic = -2 * log_lik + n_params * np.log(n)
                if bic < best_bic:
                    best_bic = bic
                    best_k = k
                    best_model = hmm
            except Exception:
                continue
        return best_model, best_k, float(best_bic) if np.isfinite(best_bic) else np.nan

    @staticmethod
    def fit_asset(
        df: pd.DataFrame,
        tf_label: str,
        windows: List[int] = (10, 20, 40),
    ) -> Optional[RegimeResult]:
        """
        Full regime classification for one asset.

        Steps:
          1. Build raw per-bar features (realized vol, trend, mr speed, relvol)
          2. For each aggregation window in windows:
                a. Aggregate (rolling mean over window)
                b. Volatility-standardize
                c. Drop NaN rows
                d. Fit K-means + GMM + HMM, score
          3. For each method, pick the window with best score
          4. Return RegimeResult with selected K and metadata

        Bias note: this is a FULL-SAMPLE fit producing the regime labels
        used by ml.py for feature extraction. For WFA OOS validation, the
        backtest layer re-fits in expanding windows. Documented in
        BiasAuditLog when called by AnalysisPipeline.
        """
        if not _SKLEARN_AVAILABLE:
            return None

        raw_feat = RegimeClassifier.build_raw_features(df)
        if raw_feat.dropna().shape[0] < 200:
            return None

        best_kmeans = (None, 0, -np.inf, 0)  # (model, k, score, window)
        best_gmm = (None, 0, np.inf, 0)
        best_hmm = (None, 0, np.inf, 0)

        for win in windows:
            agg = RegimeClassifier.aggregate_features(raw_feat, win)
            stdz = RegimeClassifier.standardize(agg, vol_window=max(252, win * 5))
            X_df = stdz.dropna()
            if X_df.shape[0] < 100:
                continue
            X = X_df.values

            km_model, km_k, km_score = RegimeClassifier.fit_kmeans_auto_k(X)
            if km_score > best_kmeans[2]:
                best_kmeans = (km_model, km_k, km_score, win)

            gmm_model, gmm_k, gmm_bic = RegimeClassifier.fit_gmm_auto_k(X)
            if gmm_bic < best_gmm[2]:
                best_gmm = (gmm_model, gmm_k, gmm_bic, win)

            if _HMMLEARN_AVAILABLE:
                hmm_model, hmm_k, hmm_bic = RegimeClassifier.fit_hmm_auto_k(X)
                if hmm_bic < best_hmm[2]:
                    best_hmm = (hmm_model, hmm_k, hmm_bic, win)

        # HMM transition matrix + mean dwell times
        trans = []
        dwell = []
        if best_hmm[0] is not None:
            trans = best_hmm[0].transmat_.tolist()
            # Mean dwell time per state = 1 / (1 - p_self)
            for i, row in enumerate(trans):
                p_self = row[i] if i < len(row) else 0
                dwell.append(1.0 / max(1.0 - p_self, 1e-6))

        n_obs = raw_feat.dropna().shape[0]
        return RegimeResult(
            symbol=df.index.name or "",
            tf_label=tf_label,
            kmeans_k_selected=best_kmeans[1],
            kmeans_silhouette=(
                float(best_kmeans[2]) if np.isfinite(best_kmeans[2]) else np.nan
            ),
            kmeans_window_used=best_kmeans[3],
            gmm_k_selected=best_gmm[1],
            gmm_bic=float(best_gmm[2]) if np.isfinite(best_gmm[2]) else np.nan,
            gmm_window_used=best_gmm[3],
            hmm_k_selected=best_hmm[1],
            hmm_bic=float(best_hmm[2]) if np.isfinite(best_hmm[2]) else np.nan,
            hmm_window_used=best_hmm[3],
            hmm_transition_matrix=trans,
            hmm_mean_dwell_times=dwell,
            n_observations=n_obs,
        )

    @staticmethod
    def predict_labels(
        df: pd.DataFrame,
        regime_result: RegimeResult,
        method: str = "hmm",
    ) -> Optional[pd.DataFrame]:
        """
        Re-fit the chosen model on the asset's data and produce label time series.

        Returns DataFrame with columns:
          regime_kmeans, regime_gmm, regime_hmm,
          regime_hmm_prob_0..K (HMM state probabilities, optional)

        Used by AnalysisPipeline to attach regime labels to PairResult
        downstream features.
        """
        if not _SKLEARN_AVAILABLE or regime_result is None:
            return None
        raw = RegimeClassifier.build_raw_features(df)
        out_df = pd.DataFrame(index=df.index)

        for method_name, k, win in [
            (
                "kmeans",
                regime_result.kmeans_k_selected,
                regime_result.kmeans_window_used,
            ),
            ("gmm", regime_result.gmm_k_selected, regime_result.gmm_window_used),
            ("hmm", regime_result.hmm_k_selected, regime_result.hmm_window_used),
        ]:
            col = f"regime_{method_name}"
            if k < 2 or win <= 0:
                out_df[col] = np.nan
                continue
            agg = RegimeClassifier.aggregate_features(raw, win)
            stdz = RegimeClassifier.standardize(agg, vol_window=max(252, win * 5))
            X_df = stdz.dropna()
            if X_df.shape[0] < 100:
                out_df[col] = np.nan
                continue
            X = X_df.values
            labels_full = np.full(df.shape[0], np.nan, dtype=float)
            try:
                if method_name == "kmeans":
                    model = KMeans(n_clusters=k, random_state=42, n_init=10)
                    labels = model.fit_predict(X)
                elif method_name == "gmm":
                    model = GaussianMixture(
                        n_components=k, random_state=42, covariance_type="full"
                    )
                    model.fit(X)
                    labels = model.predict(X)
                elif method_name == "hmm" and _HMMLEARN_AVAILABLE:
                    model = GaussianHMM(
                        n_components=k,
                        covariance_type="full",
                        n_iter=200,
                        tol=1e-2,
                        random_state=42,
                    )
                    with warnings.catch_warnings():
                        warnings.filterwarnings(
                            "ignore", message="Model is not converging"
                        )
                        warnings.filterwarnings(
                            "ignore", message=".*transmat_.*zero sum.*"
                        )
                        model.fit(X)
                    labels = model.predict(X)
                else:
                    labels = None

                if labels is not None:
                    # Map labels back into the full index (X_df has subset of rows)
                    pos = df.index.get_indexer(X_df.index)
                    valid = pos >= 0
                    labels_full[pos[valid]] = labels[valid]
            except Exception:
                pass
            out_df[col] = labels_full

        return out_df


# =============================================================================
# CLASS 7 — StrategyDecayDetector
# =============================================================================


class StrategyDecayDetector:
    """
    Detects relationship decay in confirmed cointegrated pairs.

    Four signals, all computed and reported:
      1. Rolling cointegration fraction — already in PairResult from CointScanner
      2. Half-life trend slope — from SpreadModel, positive = decaying
      3. Zivot-Andrews structural break test — detects single endogenous break
      4. CUSUM test — detects parameter instability from recursive residuals

    Bias notes:
      - All decay signals computed on the spread series, which itself is
        constructed with rolling hedge ratio (no lookahead).
      - Documented in BiasAuditLog as a methodology component.
    """

    @staticmethod
    def zivot_andrews(spread: np.ndarray) -> Optional[str]:
        """
        Zivot-Andrews test for unit root with single endogenous structural break.

        We don't implement the full Z-A test here (it's involved); we use a
        simplified Quandt-Andrews break-point approximation: scan candidate
        break dates, fit OLS pre/post on the AR(1) coefficient, identify the
        date with the largest Chow F statistic. If F exceeds critical value,
        report that date.

        Returns: ISO date string of break, or None if no significant break.
        """
        s = spread[np.isfinite(spread)]
        n = s.size
        if n < 200:
            return None

        # Trim the candidate window: skip first 15% and last 15%
        trim = int(n * 0.15)
        s_lag = s[:-1]
        s_now = s[1:]
        n_diff = s_lag.size

        # OLS over full series
        s_lag_c = s_lag - s_lag.mean()
        s_now_c = s_now - s_now.mean()
        denom_full = np.dot(s_lag_c, s_lag_c)
        if denom_full <= 0:
            return None
        phi_full = np.dot(s_lag_c, s_now_c) / denom_full
        resid_full = s_now - (s_now.mean() - phi_full * s_lag.mean()) - phi_full * s_lag
        ssr_full = np.dot(resid_full, resid_full)

        best_f = 0.0
        best_t_break = -1
        for t_break in range(trim, n_diff - trim, max(1, n_diff // 200)):
            # Pre-break OLS
            sl_pre = s_lag[:t_break] - s_lag[:t_break].mean()
            sn_pre = s_now[:t_break] - s_now[:t_break].mean()
            dn_pre = np.dot(sl_pre, sl_pre)
            if dn_pre <= 0:
                continue
            phi_pre = np.dot(sl_pre, sn_pre) / dn_pre
            res_pre = (
                s_now[:t_break]
                - (s_now[:t_break].mean() - phi_pre * s_lag[:t_break].mean())
                - phi_pre * s_lag[:t_break]
            )
            ssr_pre = np.dot(res_pre, res_pre)

            # Post-break OLS
            sl_post = s_lag[t_break:] - s_lag[t_break:].mean()
            sn_post = s_now[t_break:] - s_now[t_break:].mean()
            dn_post = np.dot(sl_post, sl_post)
            if dn_post <= 0:
                continue
            phi_post = np.dot(sl_post, sn_post) / dn_post
            res_post = (
                s_now[t_break:]
                - (s_now[t_break:].mean() - phi_post * s_lag[t_break:].mean())
                - phi_post * s_lag[t_break:]
            )
            ssr_post = np.dot(res_post, res_post)

            ssr_break = ssr_pre + ssr_post
            # Chow F-statistic
            k_params = 2  # intercept + phi
            denom_chow = ssr_break / (n_diff - 2 * k_params)
            if denom_chow <= 0:
                continue
            f_stat = ((ssr_full - ssr_break) / k_params) / denom_chow
            if f_stat > best_f:
                best_f = f_stat
                best_t_break = t_break

        # Approximate critical value for Quandt sup-F at α=0.05 ≈ 8.85 for k=2
        if best_f < 8.85 or best_t_break < 0:
            return None
        return str(best_t_break)  # caller maps index to actual date

    @staticmethod
    def cusum(spread: np.ndarray) -> Optional[str]:
        """
        CUSUM test for parameter instability on AR(1) spread model.

        Approach: fit AR(1) on full sample, compute recursive standardized
        residuals, cumulative sum. If CUSUM path exits ±2σ * sqrt(n) bounds,
        record the first exit point.

        Returns: index of first excursion as string, or None.
        """
        s = spread[np.isfinite(spread)]
        n = s.size
        if n < 100:
            return None

        s_lag = s[:-1]
        s_now = s[1:]
        sl_c = s_lag - s_lag.mean()
        sn_c = s_now - s_now.mean()
        dn = np.dot(sl_c, sl_c)
        if dn <= 0:
            return None
        phi = np.dot(sl_c, sn_c) / dn
        resid = s_now - (s_now.mean() - phi * s_lag.mean()) - phi * s_lag
        sigma = float(np.std(resid, ddof=1))
        if sigma <= 0:
            return None

        cumsum = np.cumsum(resid) / sigma
        n_resid = resid.size
        # CUSUM bound: ±2 * sqrt(n)  (approximation of Brown-Durbin-Evans bands)
        for t in range(20, n_resid):
            bound = 2.0 * np.sqrt(t)
            if abs(cumsum[t]) > bound:
                return str(t)
        return None

    @staticmethod
    def analyze_pair(
        spread: np.ndarray,
        spread_index: Optional[pd.DatetimeIndex] = None,
    ) -> Dict[str, Any]:
        """
        Run both structural break tests. Returns dict with break dates as
        ISO strings (or None) and CUSUM excursion point.

        If spread_index is provided, the integer indices returned by the
        tests are mapped to actual dates.
        """
        za = StrategyDecayDetector.zivot_andrews(spread)
        cs = StrategyDecayDetector.cusum(spread)

        za_date = None
        cs_date = None
        if spread_index is not None and len(spread_index) == spread.size:
            if za is not None:
                idx = int(za)
                if 0 <= idx < len(spread_index):
                    za_date = str(spread_index[idx].date())
            if cs is not None:
                idx = int(cs)
                if 0 <= idx < len(spread_index):
                    cs_date = str(spread_index[idx].date())
        else:
            za_date = za
            cs_date = cs

        return {
            "zivot_andrews_break": za_date,
            "cusum_first_excursion": cs_date,
        }


# =============================================================================
# CLASS 8 — CrossAssetTagger
# =============================================================================


class CrossAssetTagger:
    """
    Tags pairs that span asset classes (equity↔forex, equity↔commodity,
    futures↔crypto, etc.). Produces a separate results dictionary so the
    cross-asset section of the report can be built independently.

    Tagging happens in UniverseFilter via the is_cross_asset flag — this
    class just routes confirmed pairs into the cross-asset results bucket.
    """

    # Currency codes used to detect forex triangular arbitrage
    _CURRENCY_CODES = {
        "EUR",
        "GBP",
        "USD",
        "JPY",
        "CHF",
        "CAD",
        "AUD",
        "NZD",
        "HKD",
        "SGD",
        "SEK",
        "NOK",
        "DKK",
        "MXN",
    }

    # Known share-class pairs — same company, different share classes.
    # Cointegration is structural (mathematical identity), not discovered.
    _SHARE_CLASS_PAIRS: Set[FrozenSet[str]] = {
        frozenset({"GOOGL", "GOOG"}),  # Alphabet A / C
        frozenset({"BRK.A", "BRK.B"}),  # Berkshire Hathaway
        frozenset({"BF.A", "BF.B"}),  # Brown-Forman
        frozenset({"MOG.A", "MOG.B"}),  # Moog Inc.
        frozenset({"FOXA", "FOX"}),  # Fox Corp A / B
        frozenset({"NWS", "NWSA"}),  # News Corp A / B
        frozenset({"LGF.A", "LGF.B"}),  # Lions Gate
        frozenset({"HEI.A", "HEI"}),  # Heico Corp
    }

    @staticmethod
    def _shared_currency(sym_a: str, sym_b: str) -> bool:
        """
        True if two forex pair symbols share a common currency leg.
        Only applies when both are forex (contain a '.' separator and
        the components are currency codes).
        """
        if "." not in sym_a or "." not in sym_b:
            return False
        codes_a = set(sym_a.split("."))
        codes_b = set(sym_b.split("."))
        return bool(codes_a & codes_b & CrossAssetTagger._CURRENCY_CODES)

    @staticmethod
    def _is_share_class_pair(sym_a: str, sym_b: str) -> bool:
        """True if the two symbols are different share classes of the same company."""
        return frozenset({sym_a, sym_b}) in CrossAssetTagger._SHARE_CLASS_PAIRS

    @staticmethod
    def split(
        confirmed_pairs: List[PairResult],
    ) -> Tuple[List[PairResult], List[PairResult]]:
        """
        Returns (same_asset_pairs, cross_asset_pairs).

        Forex pairs sharing a common currency leg are tagged is_structural=True
        and separated. Structural pairs are stored in the audit log and report
        but NOT included in the primary discovered-cointegration findings —
        triangular arbitrage is mathematical identity, not empirical discovery.
        """
        structural_forex = []
        same = []
        cross = []
        for p in confirmed_pairs:
            is_forex_triangle = CrossAssetTagger._shared_currency(
                p.symbol_a, p.symbol_b
            )
            is_share_class = CrossAssetTagger._is_share_class_pair(
                p.symbol_a, p.symbol_b
            )
            if is_forex_triangle or is_share_class:
                structural_forex.append(p)
                reason = (
                    "triangular arbitrage"
                    if is_forex_triangle
                    else "same-company share classes"
                )
                BiasAuditLog.record(
                    bias_type="snooping",
                    classification="data",
                    mechanism=f"Pair {p.symbol_a}↔{p.symbol_b} is structural "
                    f"({reason}) — cointegration is guaranteed, not discovered",
                    remedy="Excluded from primary findings; reported separately",
                    scope=f"pair={p.symbol_a}-{p.symbol_b}",
                    residual_risk="None — documented as structural",
                )
            elif p.is_cross_asset:
                cross.append(p)
            else:
                same.append(p)
        if structural_forex:
            log.info(
                f"  CrossAssetTagger: {len(structural_forex)} structural forex pairs "
                f"(triangular arbitrage) excluded from primary findings"
            )
        return same, cross

    @staticmethod
    def summarize_cross_asset(cross: List[PairResult]) -> Dict[str, Any]:
        """
        Summary stats on cross-asset findings for the report section.
        Returns counts by asset-class pairing, mean half-life, mean
        coint fraction, etc.
        """
        if not cross:
            return {"count": 0}

        from collections import Counter

        pair_types = Counter(
            tuple(sorted([p.asset_class_a, p.asset_class_b])) for p in cross
        )

        half_lives = [
            p.half_life_rolling for p in cross if np.isfinite(p.half_life_rolling)
        ]
        frac_rolling = [
            p.coint_fraction_rolling
            for p in cross
            if np.isfinite(p.coint_fraction_rolling)
        ]
        return {
            "count": len(cross),
            "by_asset_class_pair": {f"{a}-{b}": v for (a, b), v in pair_types.items()},
            "mean_half_life": float(np.mean(half_lives)) if half_lives else np.nan,
            "median_half_life": float(np.median(half_lives)) if half_lives else np.nan,
            "mean_coint_fraction": (
                float(np.mean(frac_rolling)) if frac_rolling else np.nan
            ),
            "median_coint_fraction": (
                float(np.median(frac_rolling)) if frac_rolling else np.nan
            ),
        }


# =============================================================================
# CLASS 9 — TrioBuilder
# =============================================================================


def _johansen_worker(args) -> Dict[str, Any]:
    """
    Worker for Johansen cointegration on a trio. Top-level for picklability.
    """
    sym_a, sym_b, sym_c, log_a, log_b, log_c, det_order, k_ar_diff = args
    try:
        mask = np.isfinite(log_a) & np.isfinite(log_b) & np.isfinite(log_c)
        a = log_a[mask]
        b = log_b[mask]
        c = log_c[mask]
        n = a.size
        if n < 60:
            return {
                "symbol_a": sym_a,
                "symbol_b": sym_b,
                "symbol_c": sym_c,
                "ok": False,
                "error": "insufficient_overlap",
                "n_bars": n,
            }
        X = np.column_stack([a, b, c])
        result = coint_johansen(X, det_order=det_order, k_ar_diff=k_ar_diff)
        # trace stat for r=0 (at least one cointegrating vector)
        trace_stat = float(result.lr1[0])
        # critical value at 5% significance is column index 1
        crit_5pct = float(result.cvt[0, 1])
        # Number of cointegrating vectors: count r where lr1[r] > cvt[r, 1]
        n_coint = int(np.sum(result.lr1 > result.cvt[:, 1]))
        # Approximate p-value: use trace_stat / crit_5pct ratio as a proxy
        # (Johansen doesn't have closed-form p; report stat + crit instead)
        passes = trace_stat > crit_5pct
        # Crude p-value approximation for ranking: 0.05 if at threshold, lower if above
        if passes:
            # Pseudo-p: lower bound 0.001, scales with how far above crit
            ratio = trace_stat / max(crit_5pct, 1e-6)
            approx_p = max(0.001, 0.05 / ratio)
        else:
            approx_p = min(0.5, 0.05 * (crit_5pct / max(trace_stat, 1e-6)))

        return {
            "symbol_a": sym_a,
            "symbol_b": sym_b,
            "symbol_c": sym_c,
            "trace_stat": trace_stat,
            "crit_5pct": crit_5pct,
            "approx_p": approx_p,
            "n_coint_vec": n_coint,
            "n_bars": int(n),
            "ok": passes,
            "error": "",
        }
    except Exception as e:
        return {
            "symbol_a": sym_a,
            "symbol_b": sym_b,
            "symbol_c": sym_c,
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "n_bars": 0,
        }


class TrioBuilder:
    """
    Derivative trio construction from confirmed pairs.

    Procedure:
      1. Build graph: nodes = assets, edges = confirmed cointegrated pairs.
      2. For each node B with degree ≥ 2, collect pairs (A,B) and (B,C)
         and propose trio (A,B,C).
      3. Cap candidates at TRIO_MAX_CANDIDATES — rank by sum of pair p-values
         (most significant trios first).
      4. Run Johansen multivariate cointegration test on each candidate.
      5. Confirmed trios are those passing Johansen at 5%.

    Tagging: a trio is is_cross_asset if any two of its three legs come from
    different asset classes.
    """

    @staticmethod
    def candidate_trios(
        confirmed_pairs: List[Dict[str, Any]],
        max_candidates: int = None,
    ) -> List[Tuple[str, str, str]]:
        """
        Build candidate trios from the pair graph. Returns list of
        (symbol_a, symbol_b, symbol_c) tuples where B is the shared leg.
        Deduplicated so each unordered triplet appears once.
        """
        max_candidates = max_candidates or Config.ANALYSIS.TRIO_MAX_CANDIDATES

        # Build adjacency map: node -> list of (other_node, pvalue)
        adj: Dict[str, List[Tuple[str, float]]] = {}
        for p in confirmed_pairs:
            a, b = p["symbol_a"], p["symbol_b"]
            pv = p.get("coint_pvalue_adjusted", p.get("coint_pvalue_raw", 1.0))
            adj.setdefault(a, []).append((b, pv))
            adj.setdefault(b, []).append((a, pv))

        # For each node B, enumerate all unordered pairs of its neighbors
        seen: Set[Tuple[str, str, str]] = set()
        candidates: List[Tuple[str, str, str, float]] = []
        for b_node, neighbors in adj.items():
            if len(neighbors) < 2:
                continue
            for i in range(len(neighbors)):
                for j in range(i + 1, len(neighbors)):
                    a_node, p_ab = neighbors[i]
                    c_node, p_bc = neighbors[j]
                    if a_node == c_node:
                        continue
                    triple = tuple(sorted([a_node, b_node, c_node]))
                    if triple in seen:
                        continue
                    seen.add(triple)
                    candidates.append((a_node, b_node, c_node, p_ab + p_bc))

        # Sort by combined p-value ascending (most significant first), cap
        candidates.sort(key=lambda x: x[3])
        capped = candidates[:max_candidates]
        return [(a, b, c) for (a, b, c, _) in capped]

    @staticmethod
    def test_trios(
        candidate_trios: List[Tuple[str, str, str]],
        aligned_data: Dict[str, pd.DataFrame],
        asset_class_map: Dict[str, str],
        tf_label: str,
        det_order: int = None,
        k_ar_diff: int = None,
        sig_level: float = None,
        n_workers: int = 12,
    ) -> List[TrioResult]:
        """
        Run Johansen test on candidate trios in parallel.
        Returns list of confirmed TrioResult.
        """
        if not _STATSMODELS_AVAILABLE or not candidate_trios:
            return []

        det_order = (
            det_order if det_order is not None else Config.ANALYSIS.JOHANSEN_DET_ORDER
        )
        k_ar_diff = (
            k_ar_diff if k_ar_diff is not None else Config.ANALYSIS.JOHANSEN_K_AR_DIFF
        )
        sig_level = (
            sig_level
            if sig_level is not None
            else Config.ANALYSIS.JOHANSEN_SIGNIFICANCE
        )

        BiasAuditLog.record(
            bias_type="multiple_testing",
            classification="statistical",
            mechanism=f"Testing {len(candidate_trios)} trios after pair confirmation "
            f"compounds multiple-testing burden",
            remedy=f"Trios capped at {Config.ANALYSIS.TRIO_MAX_CANDIDATES}; "
            f"only trios where ALL pairs already passed BH-FDR enter; "
            f"Johansen significance at {sig_level}",
            scope=f"tf={tf_label}",
            residual_risk="Trios inherit any false discoveries from pair-level FDR",
        )

        # Build log-price arrays
        symbols_needed = set()
        for a, b, c in candidate_trios:
            symbols_needed |= {a, b, c}
        log_prices = {}
        for sym in symbols_needed:
            df = aligned_data.get(sym)
            if df is None or "close" not in df.columns:
                continue
            # clean_close masks DATA_GAP bars to NaN before logging — same
            # gap-aware convention as CointScanner._build_log_price_map.
            # Found overnight (2026-06-23): this Johansen path used raw
            # df["close"].values with no gap_flag masking at all, the exact
            # BUG-D45 contamination mechanism (forward-filled padding
            # treated as real prices), inconsistent with the pairwise EG
            # test that feeds trio candidacy in the first place.
            close = clean_close(df, exclude_flags=(GapFlag.DATA_GAP,))
            with np.errstate(invalid="ignore", divide="ignore"):
                lp = np.log(close)
            lp[~np.isfinite(lp)] = np.nan
            log_prices[sym] = lp

        tasks = []
        for a, b, c in candidate_trios:
            if a not in log_prices or b not in log_prices or c not in log_prices:
                continue
            tasks.append(
                (
                    a,
                    b,
                    c,
                    log_prices[a],
                    log_prices[b],
                    log_prices[c],
                    det_order,
                    k_ar_diff,
                )
            )

        if not tasks:
            return []

        log.info(f"  [{tf_label}] Testing {len(tasks)} trios with Johansen...")
        t0 = time.time()
        results = []
        with ProcessPoolExecutor(max_workers=n_workers) as pool:
            for r in pool.map(_johansen_worker, tasks, chunksize=10):
                results.append(r)
        log.info(f"  [{tf_label}] Trio testing complete in {time.time()-t0:.1f}s")

        # Collect confirmed
        confirmed = []
        for r in results:
            if not r.get("ok"):
                continue
            a, b, c = r["symbol_a"], r["symbol_b"], r["symbol_c"]
            cls_a = asset_class_map.get(a, "unknown")
            cls_b = asset_class_map.get(b, "unknown")
            cls_c = asset_class_map.get(c, "unknown")
            is_cross = len(set([cls_a, cls_b, cls_c])) > 1
            confirmed.append(
                TrioResult(
                    symbol_a=a,
                    symbol_b=b,
                    symbol_c=c,
                    asset_class_a=cls_a,
                    asset_class_b=cls_b,
                    asset_class_c=cls_c,
                    tf_label=tf_label,
                    johansen_trace_stat=float(r["trace_stat"]),
                    johansen_pvalue_approx=float(r["approx_p"]),
                    n_cointegrating_vectors=int(r["n_coint_vec"]),
                    n_bars=int(r["n_bars"]),
                    is_cross_asset=is_cross,
                )
            )

        log.info(f"  [{tf_label}] Confirmed trios: {len(confirmed)}/{len(tasks)}")
        return confirmed


# =============================================================================
# CLASS 10 — ThresholdCalibrator
# =============================================================================


class ThresholdCalibrator:
    """
    Empirical justification for parameter choices.

    Two studies:
      1. Pearson pre-filter sensitivity — for thresholds 0.45..0.75 in
         0.05 steps, record number of candidate pairs and EG confirmation
         rate. Inflection point is the data-driven floor.

      2. Johansen significance sensitivity — for levels 0.01, 0.05, 0.10,
         record number of confirmed trios. Used to justify the chosen
         level in the methodology section.

    The full parameter sensitivity study (OU lookback, half-life ceiling,
    z-score thresholds, BH-FDR alpha) is run after the primary analysis
    completes — sensitivity is a robustness check, not a parameter selection
    tool. Implemented in `parameter_sensitivity` separately because it
    requires re-running pieces of the pipeline.

    Bias notes:
      - This entire class is calibration, not optimization. Recorded in
        BiasAuditLog as such — choosing parameters by the calibration result
        WOULD be optimization, but we use it to JUSTIFY a pre-selected value.
    """

    @staticmethod
    def pearson_sensitivity(
        aligned_data: Dict[str, pd.DataFrame],
        asset_class_map: Dict[str, str],
        tf_label: str,
        thresholds: List[float] = (0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75),
        n_workers: int = 12,
    ) -> Dict[str, Any]:
        """
        For each threshold, run UniverseFilter + a SUBSET of EG (capped at
        2000 pairs for compute) and record confirmation rate.

        Returns:
            { threshold: {n_candidates, n_eg_confirmed, confirmation_rate}, ... }
        """
        if not _STATSMODELS_AVAILABLE:
            return {}

        # Build returns matrix once
        returns, symbols, _ = UniverseFilter.build_returns_matrix(aligned_data)
        if returns.size == 0:
            return {}
        corr = UniverseFilter.correlation_matrix(returns)

        # Pre-build log-price map for EG worker
        log_prices = CointScanner._build_log_price_map(aligned_data, symbols)

        results = {}
        log.info(f"  [{tf_label}] Pearson calibration: {len(thresholds)} thresholds")
        for thr in thresholds:
            pairs = UniverseFilter.candidate_pairs(corr, symbols, thr, asset_class_map)
            n_cand = len(pairs)

            # For compute reasons, sample up to 2000 pairs per threshold for EG
            cap = min(n_cand, 2000)
            if cap == 0:
                results[thr] = {
                    "n_candidates": 0,
                    "n_eg_confirmed": 0,
                    "confirmation_rate": np.nan,
                }
                continue
            # Stratified sample by correlation magnitude bin to be representative
            np.random.seed(42)
            if n_cand > cap:
                indices = np.random.choice(n_cand, cap, replace=False)
                sample = [pairs[i] for i in indices]
            else:
                sample = pairs

            tasks = []
            for p in sample:
                lp_a = log_prices.get(p["symbol_a"])
                lp_b = log_prices.get(p["symbol_b"])
                if lp_a is None or lp_b is None:
                    continue
                tasks.append(
                    (
                        p["symbol_a"],
                        p["symbol_b"],
                        lp_a,
                        lp_b,
                        Config.ANALYSIS.EG_MAX_LAG,
                    )
                )

            n_eg = 0
            n_tested = 0
            with ProcessPoolExecutor(max_workers=n_workers) as pool:
                for r in pool.map(_eg_worker, tasks, chunksize=50):
                    n_tested += 1
                    if r.get("ok") and r["pvalue"] < Config.ANALYSIS.EG_SIGNIFICANCE:
                        n_eg += 1
            rate = n_eg / n_tested if n_tested > 0 else np.nan
            results[thr] = {
                "n_candidates": n_cand,
                "n_sampled": len(tasks),
                "n_eg_confirmed": n_eg,
                "confirmation_rate": float(rate),
            }
            log.info(
                f"  [{tf_label}]   ρ≥{thr:.2f}: candidates={n_cand}, "
                f"sample_confirmed={n_eg}/{n_tested}, rate={rate:.3f}"
            )

        BiasAuditLog.record(
            bias_type="snooping",
            classification="statistical",
            mechanism="Choosing pre-filter threshold based on confirmation curve "
            "could constitute data snooping",
            remedy="Threshold chosen a priori (0.60); this sensitivity study "
            "is calibration/justification, not optimization. The baseline "
            "threshold is held fixed for primary results.",
            scope=f"tf={tf_label}",
            residual_risk="Reviewer may still consider the curve presentation as "
            "implicit threshold selection",
        )
        return results

    @staticmethod
    def johansen_sensitivity(
        candidate_trios: List[Tuple[str, str, str]],
        aligned_data: Dict[str, pd.DataFrame],
        asset_class_map: Dict[str, str],
        tf_label: str,
        sig_levels: List[float] = (0.01, 0.05, 0.10),
        n_workers: int = 12,
    ) -> Dict[float, int]:
        """
        Run Johansen at multiple significance levels and report confirmed
        trio count at each. Note that Johansen reports trace stat vs
        critical values — we compare against the same crit values but
        interpret as different significance levels.
        """
        results = {}
        if not candidate_trios or not _STATSMODELS_AVAILABLE:
            return results

        # The Johansen test produces trace_stat and crit values; running the
        # test once per trio at default settings is enough — we just check
        # against different crit thresholds. The coint_johansen output has
        # 3 columns of crit values: 10%, 5%, 1%. Lower index = lower significance.
        symbols_needed = {s for tr in candidate_trios for s in tr}
        log_prices = {}
        for sym in symbols_needed:
            df = aligned_data.get(sym)
            if df is None or "close" not in df.columns:
                continue
            with np.errstate(invalid="ignore", divide="ignore"):
                lp = np.log(df["close"].values)
            lp[~np.isfinite(lp)] = np.nan
            log_prices[sym] = lp

        # Map sig level to crit column index in coint_johansen output
        sig_to_col = {0.10: 0, 0.05: 1, 0.01: 2}

        tasks = []
        for a, b, c in candidate_trios:
            if a in log_prices and b in log_prices and c in log_prices:
                tasks.append(
                    (
                        a,
                        b,
                        c,
                        log_prices[a],
                        log_prices[b],
                        log_prices[c],
                        Config.ANALYSIS.JOHANSEN_DET_ORDER,
                        Config.ANALYSIS.JOHANSEN_K_AR_DIFF,
                    )
                )
        if not tasks:
            return {lvl: 0 for lvl in sig_levels}

        # Direct trace stats + crit
        all_traces = []
        all_crits = []
        for task in tasks:
            sym_a, sym_b, sym_c, la, lb, lc, det, kar = task
            try:
                mask = np.isfinite(la) & np.isfinite(lb) & np.isfinite(lc)
                X = np.column_stack([la[mask], lb[mask], lc[mask]])
                if X.shape[0] < 60:
                    continue
                r = coint_johansen(X, det_order=det, k_ar_diff=kar)
                all_traces.append(r.lr1[0])  # r=0 trace
                all_crits.append(r.cvt[0])  # 3-element array
            except Exception:
                continue

        for lvl in sig_levels:
            col = sig_to_col.get(lvl)
            if col is None:
                results[lvl] = 0
                continue
            n_passed = sum(1 for ts, cv in zip(all_traces, all_crits) if ts > cv[col])
            results[lvl] = n_passed
            log.info(
                f"  [{tf_label}]   Johansen α={lvl}: {n_passed}/{len(all_traces)} passed"
            )

        return results

    @staticmethod
    def parameter_sensitivity_summary(
        baseline_pairs: List[Dict[str, Any]],
        param_variations: Dict[str, List[float]] = None,
    ) -> Dict[str, Any]:
        """
        Lightweight parameter sensitivity report. Full WFA-based sensitivity
        is run by backtest.py; here we report sensitivity of confirmed pair
        counts and median rolling coint fraction to BH-FDR alpha and EG max_lag.

        Returns dict keyed by parameter with table of (value, pair_count, median_frac).
        """
        if param_variations is None:
            param_variations = {
                "fdr_alpha": [0.01, 0.05, 0.10, 0.15],
                # max_lag and other params would require re-running EG; skipped here
            }

        out = {}
        if not baseline_pairs:
            return out

        # BH-FDR re-application at different alphas using stored RAW p-values
        raw_pvals = np.array([p.get("coint_pvalue_raw", 1.0) for p in baseline_pairs])
        for alpha in param_variations.get("fdr_alpha", []):
            rejected, _adj = _benjamini_hochberg(raw_pvals, alpha)
            n_pass = int(np.sum(rejected))
            out.setdefault("fdr_alpha", []).append(
                {
                    "value": alpha,
                    "pair_count": n_pass,
                }
            )
        return out


# =============================================================================
# MODULE-LEVEL WORKER — must be at module level for ProcessPoolExecutor pickling
# =============================================================================


def _regime_worker(args) -> Optional[Tuple["RegimeResult", Optional[pd.DataFrame]]]:
    """
    Top-level (not nested) function for ProcessPoolExecutor.

    Nested/local functions are not picklable and cannot be sent to worker
    processes. This must live at module scope.

    Receives serialized DataFrame bytes to avoid shared-memory issues;
    deserializes, fits all regime models (K-means, GMM, HMM), returns
    (summary RegimeResult, per-bar label DataFrame). The per-bar labels
    come from RegimeClassifier.predict_labels(), which existed and was
    fully implemented but never called until 2026-06-22 — added so
    per-bar regime context (Level 1 of the "Rich Regime Classification"
    enhancement, DEVELOPMENT.md) is available for ml.py's later stages,
    at the documented ~15-20% extra runtime cost (re-fitting all 3 models
    a second time to produce labels, not just summary stats).
    """
    sym, df_bytes, tf_label = args
    try:
        import pickle

        df = pickle.loads(df_bytes)
        df.index.name = sym
        rr = RegimeClassifier.fit_asset(df, tf_label)
        if rr is None:
            return None
        rr.symbol = sym
        labels = RegimeClassifier.predict_labels(df, rr)
        return rr, labels
    except Exception:
        return None


# =============================================================================
# CLASS 11 — AnalysisPipeline (orchestrator)
# =============================================================================


@dataclass
class FilterFunnelStage:
    """One gate's before/after count for one timeframe's filter funnel."""

    stage: str
    n_before: int
    n_after: int

    @property
    def n_removed(self) -> int:
        return self.n_before - self.n_after


class FilterFunnel:
    """
    Tracks symbol/pair counts through each sequential gate in one timeframe's
    analysis pipeline (ADV liquidity, Pearson pre-filter, EG+BH-FDR,
    price-degeneracy, structural exclusion, coint_frac threshold+override),
    so a filter-ablation study can measure each stage's real marginal effect
    instead of only ever seeing the final confirmed-pair count.

    Units differ by stage (ADV/price-degeneracy record symbol-level or
    pair-level counts depending on what the gate actually operates on) — the
    stage name itself documents the unit; this class does not normalize
    across stages, it just records what each gate saw before/after.
    """

    def __init__(self, tf_label: str):
        self.tf_label = tf_label
        self.stages: List[FilterFunnelStage] = []

    def record(self, stage: str, n_before: int, n_after: int) -> None:
        self.stages.append(FilterFunnelStage(stage, n_before, n_after))

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "tf_label": self.tf_label,
                    "stage": s.stage,
                    "n_before": s.n_before,
                    "n_after": s.n_after,
                    "n_removed": s.n_removed,
                }
                for s in self.stages
            ]
        )

    def save(self) -> None:
        df = self.to_dataframe()
        if df.empty:
            return
        out_path = os.path.join(_output_dir(self.tf_label), "filter_funnel.parquet")
        df.to_parquet(out_path, index=False)
        log.info(f"  [{self.tf_label}] filter funnel:\n{df.to_string(index=False)}")


class AnalysisPipeline:
    """
    Top-level orchestrator. Consumes a UniverseResult from data.py and
    produces an AnalysisResults dataclass.

    Memory management: processes one timeframe at a time. After each TF
    completes, results are saved to disk and the TF data is released.

    Per-TF processing order:
      1. Filter aligned_data to assets that have this TF
      2. Align via DataAligner.align_universe
      3. UniverseFilter (Pearson candidate pairs)
      4. CointScanner.scan (EG + BH-FDR)
      5. CointScanner.rolling_fraction (decay signal #1)
      6. For each confirmed pair:
            - HedgeRatioEstimator.estimate_all_for_pair
            - SpreadModel.fit_pair (rolling + expanding)
            - StrategyDecayDetector.analyze_pair (decay signals #2-4)
            - Build PairResult dataclass
      7. Build VolumeStructure feature DataFrames for all retained symbols
            - Save to output/results/{tf_label}/features_{symbol}.parquet
      8. RegimeClassifier on each retained symbol (skip if insufficient bars)
      9. CrossAssetTagger.split (separate cross-asset bucket)
      10. TrioBuilder: candidate enumeration + Johansen tests
      11. (1D only) ThresholdCalibrator: Pearson + Johansen sensitivity
      12. Save all dataclasses to output/results/{tf_label}/*.parquet
      13. BiasAuditLog.save once at end

    Failure handling: any single pair/asset failure is caught and logged.
    The TF as a whole completes even if some pairs/assets fail.
    """

    @staticmethod
    def run(
        universe: UniverseResult,
        timeframes: Optional[List[str]] = None,
        run_calibration: bool = True,
        run_synthetic: bool = False,
        n_workers: int = 12,
    ) -> AnalysisResults:
        """
        Run the full analysis pipeline.

        Args:
            universe:        Output of UniverseBuilder.build()
            timeframes:      If None, processes all TFs from Config. Otherwise
                             processes only the listed TFs (useful for debugging).
            run_calibration: If True, runs ThresholdCalibrator on 1D timeframe.
            run_synthetic:   If True, also runs synthetic dollar-bar variant on
                             high-liquidity subset (placeholder — to be implemented).
            n_workers:       Parallelism for EG, Johansen, rolling coint.

        Returns:
            AnalysisResults with all confirmed pairs, trios, regimes, and audit log.
        """
        t_start = time.time()
        BiasAuditLog.reset()

        log.info("=" * 70)
        log.info("CAMARF — analysis.py — Pipeline start")
        log.info("=" * 70)
        log.info(
            f"  Universe: {len(universe.assets)} assets, "
            f"{len(universe.data)} symbol-TF combinations"
        )

        # Hash-based result invalidation — clear stale results if scripts changed
        clear_stale_results(force=False)

        # Build asset_class_map once
        asset_class_map = {sym: cls for sym, cls in universe.assets}

        # Determine TFs to process
        all_tfs = timeframes or Config.DATA.TIMEFRAME_LABELS
        log.info(f"  Timeframes: {all_tfs}")

        # Initial bias audit entries (universe-level)
        BiasAuditLog.record(
            bias_type="survivorship",
            classification="data",
            mechanism="Universe uses current S&P 500 constituents — historically "
            "removed names (bankruptcies, acquisitions, delistings) absent",
            remedy="Documented limitation. True correction requires historical "
            "constituent data (e.g. CRSP/Compustat) — not available here.",
            scope="universe",
            residual_risk="Historical cointegration findings biased toward survivors; "
            "may overstate strategy profitability vs reality",
        )
        BiasAuditLog.record(
            bias_type="non_stationarity",
            classification="statistical",
            mechanism="Cointegration relationships break down over time; full-sample "
            "tests may average over distinct structural regimes",
            remedy="Rolling 252-bar cointegration fraction computed for every "
            "confirmed pair; structural break tests (Zivot-Andrews, CUSUM) "
            "run on every spread series",
            scope="universe",
            residual_risk="Rolling tests have lower power than full-sample; some genuine "
            "decay signals may not reach significance",
        )

        # Result containers
        pairs_by_tf: Dict[str, List[PairResult]] = {}
        trios_by_tf: Dict[str, List[TrioResult]] = {}
        regimes_by_tf: Dict[str, List[RegimeResult]] = {}
        cross_asset_pairs: Dict[str, List[PairResult]] = {}
        threshold_calibration: Dict[str, Any] = {}

        # Process each TF
        for tf_label in all_tfs:
            log.info("-" * 70)
            log.info(f"  Timeframe: {tf_label}")
            log.info("-" * 70)
            try:
                pairs, trios, regimes, cross, calib = AnalysisPipeline._run_one_tf(
                    universe=universe,
                    tf_label=tf_label,
                    asset_class_map=asset_class_map,
                    run_calibration=(run_calibration and tf_label == "1D"),
                    n_workers=n_workers,
                )
                pairs_by_tf[tf_label] = pairs
                trios_by_tf[tf_label] = trios
                regimes_by_tf[tf_label] = regimes
                cross_asset_pairs[tf_label] = cross
                if calib:
                    threshold_calibration[tf_label] = calib
            except Exception as e:
                log.error(f"  [{tf_label}] FAILED: {type(e).__name__}: {e}")
                log.error(traceback.format_exc())
                pairs_by_tf[tf_label] = []
                trios_by_tf[tf_label] = []
                regimes_by_tf[tf_label] = []
                cross_asset_pairs[tf_label] = []

        # Save bias audit and update script hash (run completed successfully)
        audit_path = os.path.join(Config.DATA.OUTPUT_DIR, "results", "bias_audit.json")
        BiasAuditLog.save(audit_path)
        _save_current_hash(_compute_script_hash())
        log.info(f"Script hash saved: {_compute_script_hash()}")

        runtime = time.time() - t_start
        log.info("=" * 70)
        log.info(f"Pipeline complete in {runtime/60:.1f} min")
        for tf in all_tfs:
            n_p = len(pairs_by_tf.get(tf, []))
            n_t = len(trios_by_tf.get(tf, []))
            n_r = len(regimes_by_tf.get(tf, []))
            n_c = len(cross_asset_pairs.get(tf, []))
            log.info(f"  {tf}: pairs={n_p} (cross={n_c}), trios={n_t}, regimes={n_r}")

        return AnalysisResults(
            timeframes_processed=all_tfs,
            pairs_by_tf=pairs_by_tf,
            trios_by_tf=trios_by_tf,
            regimes_by_tf=regimes_by_tf,
            cross_asset_pairs=cross_asset_pairs,
            threshold_calibration=threshold_calibration,
            bias_audit=BiasAuditLog.all_entries(),
            runtime_seconds=runtime,
        )

    @staticmethod
    def _run_one_tf(
        universe: UniverseResult,
        tf_label: str,
        asset_class_map: Dict[str, str],
        run_calibration: bool,
        n_workers: int,
    ) -> Tuple[
        List[PairResult],
        List[TrioResult],
        List[RegimeResult],
        List[PairResult],
        Dict[str, Any],
    ]:
        """Process one timeframe end-to-end."""

        # Step 1: extract TF data
        # Cap shallow TFs to last N bars per asset to prevent OOM.
        # Also explicitly skip any symbol in universe.exclusion_set —
        # belt-and-suspenders guard so excluded assets (VLTO, BNY, etc.)
        # cannot enter analysis results even if they have cached data.
        _SHALLOW_CAP = {"1m": 5_000, "2m": 5_000, "3m": 5_000}
        _exclusions = getattr(universe, "exclusion_set", set()) or set()
        tf_data_raw = {}
        _freq_mismatches = []
        for sym, _cls in universe.assets:
            if sym in _exclusions:
                continue
            key = f"{sym}_{tf_label}"
            if key not in universe.data or universe.data[key] is None:
                continue
            df = universe.data[key]
            # Validate that the cache data is actually at the expected frequency.
            # Catches cases like NTRS_1m.parquet containing daily bars — which
            # would produce 1m cointegration results identical to 1D analysis.
            if not DataStore.validate_frequency(sym, tf_label, df):
                _freq_mismatches.append(sym)
                continue  # skip this asset for this TF; urge data.py rerun
            cap = _SHALLOW_CAP.get(tf_label)
            if cap and len(df) > cap:
                df = df.iloc[-cap:]
            tf_data_raw[sym] = df
        if _freq_mismatches:
            log.warning(
                f"  [{tf_label}] {len(_freq_mismatches)} assets skipped (frequency mismatch "
                f"in cache): {_freq_mismatches[:10]}{'...' if len(_freq_mismatches)>10 else ''}. "
                f"Rerun data.py to refresh these cache files."
            )
        log.info(f"  [{tf_label}] {len(tf_data_raw)} assets have data for this TF")

        funnel = FilterFunnel(tf_label)

        # ADV liquidity filter — requires both symbols in any pair to exceed threshold.
        # Computed from 1hr cache (close × volume, aggregated to daily sums) so it is
        # independent of the current TF being analyzed.
        _adv_threshold = getattr(Config.ANALYSIS, "ADV_FILTER_USD", 0.0)
        if _adv_threshold > 0:
            _cache_dir = Config.DATA.CACHE_DIR
            _adv_map: dict = {}
            for sym in list(tf_data_raw.keys()):
                _hr_path = os.path.join(_cache_dir, f"{sym}_1hr.parquet")
                if not os.path.exists(_hr_path):
                    _adv_map[sym] = float("nan")
                    continue
                try:
                    _hr = pd.read_parquet(_hr_path)
                    if "close" in _hr.columns and "volume" in _hr.columns:
                        _hr.index = pd.to_datetime(_hr.index)
                        _dv = _hr["close"] * _hr["volume"]
                        _daily_dv = _dv.groupby(_hr.index.date).sum()
                        _adv_map[sym] = float(_daily_dv.mean()) if len(_daily_dv) > 0 else float("nan")
                    else:
                        _adv_map[sym] = float("nan")
                except Exception:
                    _adv_map[sym] = float("nan")
            _adv_filtered = {s: v for s, v in _adv_map.items() if v >= _adv_threshold}
            _adv_excluded = {s for s in tf_data_raw if s not in _adv_filtered}
            funnel.record("adv_liquidity_symbols", len(tf_data_raw), len(_adv_filtered))
            if _adv_excluded:
                log.info(
                    f"  [{tf_label}] ADV filter (>=${_adv_threshold/1e6:.0f}M): "
                    f"removed {len(_adv_excluded)} symbols "
                    f"(kept {len(_adv_filtered)}/{len(tf_data_raw)})"
                )
                tf_data_raw = {s: df for s, df in tf_data_raw.items() if s in _adv_filtered}

        if len(tf_data_raw) < 10:
            log.warning(f"  [{tf_label}] insufficient assets — skipping TF")
            return [], [], [], [], {}

        # Step 2: align to NYSE master calendar (or intraday equivalent)
        aligned = DataAligner.align_universe(
            {f"{sym}_{tf_label}": df for sym, df in tf_data_raw.items()},
            tf_label,
        )
        if not aligned:
            log.warning(f"  [{tf_label}] alignment failed — skipping TF")
            return [], [], [], [], {}
        log.info(f"  [{tf_label}] aligned: {len(aligned)} assets")

        BiasAuditLog.record(
            bias_type="lookahead",
            classification="data",
            mechanism="Cross-asset analysis requires shared time index; "
            "naive joining could leak information",
            remedy="DataAligner uses NYSE master calendar with strict forward-fill; "
            "is_gap column flags every imputed bar; no future data used",
            scope=f"tf={tf_label}",
        )

        # Step 3: Pearson filter
        # Returns the returns matrix and Pearson correlation matrix alongside
        # candidates so EigenportfolioDecomposer can reuse them without
        # recomputing the (expensive) N×N matrix from scratch.
        _uf_raw = UniverseFilter.run(
            aligned,
            asset_class_map,
            threshold=Config.UNIVERSE.MIN_PEARSON_CORR,
            tf_label=tf_label,
            return_matrices=True,
        )
        # Guard: returns 2-tuple ([], []) when no assets pass filtering
        # (e.g. 6M with only 4 qualifying assets)
        _n_possible_pairs = len(aligned) * (len(aligned) - 1) // 2
        if not isinstance(_uf_raw, tuple) or len(_uf_raw) < 5:
            funnel.record("pearson_prefilter_pairs", _n_possible_pairs, 0)
            funnel.save()
            log.info(f"  [{tf_label}] no candidate pairs above threshold")
            return [], [], [], [], {}
        candidates, retained_symbols, _returns_mat, _corr_mat, _sym_order = _uf_raw
        if not candidates:
            funnel.record("pearson_prefilter_pairs", _n_possible_pairs, 0)
            funnel.save()
            log.info(f"  [{tf_label}] no candidate pairs above threshold")
            return [], [], [], [], {}
        funnel.record("pearson_prefilter_pairs", _n_possible_pairs, len(candidates))

        # Step 4: Engle-Granger + BH-FDR
        confirmed_dicts, eg_stats = CointScanner.scan(
            candidate_pairs=candidates,
            aligned_data=aligned,
            symbols_in_corr=retained_symbols,
            tf_label=tf_label,
            n_workers=n_workers,
        )
        if not confirmed_dicts:
            funnel.record("eg_bh_fdr_pairs", len(candidates), 0)
            funnel.save()
            log.info(f"  [{tf_label}] no pairs survived BH-FDR")
            return [], [], [], [], {}
        funnel.record("eg_bh_fdr_pairs", len(candidates), len(confirmed_dicts))

        # Step 5: rolling coint fraction (decay signal #1)
        confirmed_dicts = CointScanner.rolling_fraction(
            confirmed_dicts,
            aligned,
            tf_label,
            n_workers=n_workers,
        )

        # Steps 6: per-pair full modeling — hedge ratios, spread, decay
        log.info(f"  [{tf_label}] Per-pair modeling: hedge ratios + spread + decay...")
        pair_results: List[PairResult] = []
        per_bar_by_pair: Dict[Tuple[str, str], Dict[str, Any]] = {}
        t0 = time.time()
        for i, pd_meta in enumerate(confirmed_dicts):
            try:
                built = AnalysisPipeline._build_pair_result(pd_meta, aligned, tf_label)
                if built is not None:
                    pr, per_bar = built
                    pair_results.append(pr)
                    per_bar_by_pair[(pr.symbol_a, pr.symbol_b)] = per_bar
            except Exception as e:
                log.warning(
                    f"    pair {pd_meta.get('symbol_a')}-{pd_meta.get('symbol_b')} "
                    f"failed in _build_pair_result: {type(e).__name__}: {e}"
                )
            if (i + 1) % 500 == 0:
                log.info(f"    progress: {i+1}/{len(confirmed_dicts)} pairs modeled")
        log.info(
            f"  [{tf_label}] Per-pair modeling done in {time.time()-t0:.1f}s — "
            f"{len(pair_results)} PairResult objects built"
        )

        # Step 6b: Eigenportfolio validation — project out systematic factors
        # and re-test cointegration on idiosyncratic residuals.
        # Gold tier = confirmed by raw EG AND residual EG (genuinely idiosyncratic).
        # Silver tier = raw EG only (may be factor-driven correlation).
        if pair_results and _returns_mat is not None and _returns_mat.size > 0:
            pair_results = EigenportfolioDecomposer.run_for_tf(
                confirmed_pairs=pair_results,
                returns=_returns_mat,
                symbols=_sym_order,
                corr=_corr_mat,
                n_periods=_returns_mat.shape[1],
                tf_label=tf_label,
            )
        else:
            # No returns matrix available — set default Silver tier for all
            import dataclasses as _dc

            pair_results = [
                _dc.replace(
                    p,
                    eigenport_pvalue=None,
                    passes_eigenportfolio=None,
                    n_factors_removed=None,
                    confidence_tier="silver",
                )
                for p in pair_results
            ]

        BiasAuditLog.record(
            bias_type="lookahead",
            classification="model",
            mechanism="Hedge ratio estimated on full sample is lookahead-biased",
            remedy="Three hedge ratios estimated: OLS rolling 252-bar (primary, "
            "no lookahead), Kalman calibrated on first 252 bars then frozen "
            "(no lookahead), TLS full-sample (lookahead — used for comparison "
            "in methodology only)",
            scope=f"tf={tf_label}",
            residual_risk="TLS point estimate has lookahead; documented in pair results "
            "but not used as primary signal",
        )

        # Step 6c: annotate research-screen flags (thin_info_content,
        # permutation_robust) from pre-computed output/research/ parquets.
        # Read-only, no-ops cleanly when screens haven't been run.
        pair_results = AnalysisPipeline._apply_research_screen_flags(pair_results, tf_label)

        # Step 6d: BUG-D49 price-degeneracy filter — drop pairs where either
        # leg has implausibly few distinct close prices (e.g. 2–7 distinct
        # values across hundreds of bars). These produce near-zero-variance
        # spreads and generate 0 backtest trades. Only active when
        # audit_price_degeneracy.py has been run (thin_info_content populated).
        n_before_deg = len(pair_results)
        pair_results = [pr for pr in pair_results if not pr.thin_info_content]
        n_dropped_deg = n_before_deg - len(pair_results)
        funnel.record("price_degeneracy_pairs", n_before_deg, len(pair_results))
        if n_dropped_deg:
            log.info(
                f"  [{tf_label}] Price-degeneracy filter: dropped {n_dropped_deg} pairs "
                f"({n_before_deg} → {len(pair_results)})"
            )

        # Step 7: VolumeStructure feature engineering
        log.info(f"  [{tf_label}] Computing VolumeStructure features...")
        feat_dir = _output_dir(tf_label)
        t0 = time.time()
        n_features_saved = 0
        retained_for_features = set()
        for pr in pair_results:
            retained_for_features.add(pr.symbol_a)
            retained_for_features.add(pr.symbol_b)
        for sym in retained_for_features:
            df = aligned.get(sym)
            if df is None or df.empty:
                continue
            try:
                feat = VolumeStructure.compute_features(df)
                feat_path = os.path.join(
                    feat_dir, f"features_{sym.replace(' ','_')}.parquet"
                )
                feat.to_parquet(feat_path)
                n_features_saved += 1
            except Exception as e:
                log.debug(f"    features {sym} failed: {e}")
        log.info(
            f"  [{tf_label}] Features saved: {n_features_saved} assets "
            f"in {time.time()-t0:.1f}s"
        )

        # Step 8: RegimeClassifier on retained assets — parallelized
        # Sequential fitting at ~187s/asset becomes prohibitive at scale.
        # ProcessPoolExecutor distributes across n_workers.
        log.info(
            f"  [{tf_label}] Regime classification ({len(retained_for_features)} assets)..."
        )
        regime_results: List[RegimeResult] = []
        t0 = time.time()

        # Build task list — serialize DataFrames for inter-process transfer
        import pickle as _pickle

        regime_tasks = []
        for sym in retained_for_features:
            df = aligned.get(sym)
            if df is None or df.empty:
                continue
            try:
                regime_tasks.append((sym, _pickle.dumps(df), tf_label))
            except Exception:
                pass

        n_labels_persisted = 0
        if regime_tasks:
            _regime_out_dir = _output_dir(tf_label)
            with ProcessPoolExecutor(max_workers=n_workers) as pool:
                for result in pool.map(_regime_worker, regime_tasks, chunksize=1):
                    if result is None:
                        continue
                    rr, labels = result
                    regime_results.append(rr)
                    if labels is not None and not labels.empty:
                        try:
                            labels.to_parquet(
                                os.path.join(
                                    _regime_out_dir,
                                    f"regime_labels_{rr.symbol}.parquet",
                                )
                            )
                            n_labels_persisted += 1
                        except Exception as _e:
                            log.debug(
                                f"  regime_labels persist failed for {rr.symbol}: {_e}"
                            )

        log.info(
            f"  [{tf_label}] Regimes fitted: {len(regime_results)} assets "
            f"({n_labels_persisted} per-bar label files saved) "
            f"in {time.time()-t0:.1f}s"
        )

        if regime_results:
            BiasAuditLog.record(
                bias_type="regime_lookahead",
                classification="model",
                mechanism="Fitting regime model on full sample uses future data "
                "to define regime labels, contaminating downstream backtests",
                remedy="Primary result reports full-sample regimes for descriptive "
                "analysis. For OOS validation in backtest.py, regimes are "
                "refitted in expanding windows — that machinery lives there",
                scope=f"tf={tf_label}",
                residual_risk="ML features extracted from full-sample regimes inherit "
                "lookahead; mitigated by backtest layer's WFA refit",
            )

        # Step 9: split cross-asset
        same_pairs, cross_pairs = CrossAssetTagger.split(pair_results)
        log.info(
            f"  [{tf_label}] Cross-asset split: same={len(same_pairs)}, "
            f"cross={len(cross_pairs)}"
        )

        # Step 10: TrioBuilder
        log.info(f"  [{tf_label}] Trio enumeration + Johansen...")
        trio_candidates = TrioBuilder.candidate_trios(confirmed_dicts)
        trio_results = TrioBuilder.test_trios(
            candidate_trios=trio_candidates,
            aligned_data=aligned,
            asset_class_map=asset_class_map,
            tf_label=tf_label,
            n_workers=n_workers,
        )

        # Step 11: Threshold calibration (1D only)
        calib_dict: Dict[str, Any] = {}
        if run_calibration:
            log.info(f"  [{tf_label}] Threshold calibration...")
            calib_dict["pearson"] = ThresholdCalibrator.pearson_sensitivity(
                aligned,
                asset_class_map,
                tf_label,
                n_workers=n_workers,
            )
            calib_dict["johansen"] = ThresholdCalibrator.johansen_sensitivity(
                trio_candidates,
                aligned,
                asset_class_map,
                tf_label,
                n_workers=n_workers,
            )
            calib_dict["parameter_sensitivity"] = (
                ThresholdCalibrator.parameter_sensitivity_summary(confirmed_dicts)
            )

        # Step 12: save all results to disk, then checkpoint the hash.
        # If the 8-hour run crashes mid-pipeline, completed TFs are preserved.
        # The script hash checkpoint ensures the next run doesn't clear them.
        # pair_results is reassigned to the actually-persisted set (post
        # structural-pair and coint_frac filtering) so pairs_by_tf/the run
        # summary log can't show a pair as "confirmed" that was never saved.
        pair_results = AnalysisPipeline._save_tf_results(
            tf_label,
            pair_results,
            trio_results,
            regime_results,
            cross_pairs,
            calib_dict,
            per_bar_by_pair,
            funnel,
        )
        # Checkpoint: mark this TF as complete in the hash store.
        # The full hash is only confirmed at pipeline end, but partial
        # progress is preserved so crashes don't waste completed TF work.
        _save_current_hash(_compute_script_hash())

        return pair_results, trio_results, regime_results, cross_pairs, calib_dict

    @staticmethod
    def _build_pair_result(
        pd_meta: Dict[str, Any],
        aligned_data: Dict[str, pd.DataFrame],
        tf_label: str,
    ) -> Optional[Tuple[PairResult, Dict[str, Any]]]:
        """
        Build PairResult from confirmed-pair metadata. Computes hedge ratios,
        spread, half-life trend, structural break tests.

        Also returns the per-bar spread/z-score/half-life arrays SpreadModel
        already computes internally (previously discarded after this function
        returned) — carried forward so _save_tf_results() can persist them for
        whichever pairs survive final filtering, without recomputing anything.
        A future ml.py needs real historical entry/exit events, not just the
        summary scalars in PairResult; see DEVELOPMENT.md ml.py section.
        """
        sym_a = pd_meta["symbol_a"]
        sym_b = pd_meta["symbol_b"]
        df_a = aligned_data.get(sym_a)
        df_b = aligned_data.get(sym_b)
        if df_a is None or df_b is None:
            return None

        # Build log-price arrays from the SHARED index (already aligned)
        close_a = df_a["close"].values
        close_b = df_b["close"].values
        with np.errstate(invalid="ignore", divide="ignore"):
            log_a = np.log(close_a)
            log_b = np.log(close_b)
        log_a[~np.isfinite(log_a)] = np.nan
        log_b[~np.isfinite(log_b)] = np.nan

        gap_flag_a = df_a["gap_flag"].values if "gap_flag" in df_a else None
        gap_flag_b = df_b["gap_flag"].values if "gap_flag" in df_b else None
        clean_mask = (
            (gap_flag_a == GapFlag.NONE) & (gap_flag_b == GapFlag.NONE)
            if gap_flag_a is not None and gap_flag_b is not None
            else None
        )

        # Hedge ratios
        hr_window = min(252, max(60, log_a.size // 4))
        hr = HedgeRatioEstimator.estimate_all_for_pair(log_a, log_b, hr_window)

        # Spread model with rolling OLS hedge series as primary
        sm = SpreadModel.fit_pair(
            log_a, log_b, hr["ols_series"], hr["ols_point"], clean_mask=clean_mask
        )

        # Half-life — full sample as "expanding", rolling median for primary
        hl_exp = sm["half_life_full"]
        hl_roll = sm["half_life_rolling_median"]
        trend_slope = sm["half_life_trend_slope"]
        theta = sm["mean_reversion_speed"]

        # Decay tests + Hurst exponent — masked to the SAME real-bars-only
        # positions SpreadModel.fit_pair used internally for its own rolling
        # stats (BUG-D45). Found overnight (2026-06-23): both of these were
        # still operating on sm["spread"] unmasked, the exact BUG-D45
        # contamination mechanism left live in two more consumers — a long
        # run of identical forward-filled padding values, punctuated by a
        # jump at every session boundary, biases Hurst R/S/DFA and can
        # produce false/missed Zivot-Andrews/CUSUM structural breaks.
        _spread_full = sm["spread"]
        if clean_mask is not None:
            _real_pos = np.flatnonzero(clean_mask & np.isfinite(_spread_full))
        else:
            _real_pos = np.flatnonzero(np.isfinite(_spread_full))
        _spread_real = _spread_full[_real_pos]
        _index_real = df_a.index[_real_pos]

        decay = StrategyDecayDetector.analyze_pair(_spread_real, _index_real)

        # Hurst exponent on spread series (both R/S and DFA)
        hurst_result = HurstEstimator.estimate(_spread_real)

        # Log non-ML-gate pairs for diagnostic awareness
        if not hurst_result["passes_ml_gate"]:
            _dfa_str = (
                f"{hurst_result['hurst_dfa']:.3f}"
                if hurst_result["hurst_dfa"] is not None
                else "n/a"
            )
            _rs_str = (
                f"{hurst_result['hurst_rs']:.3f}"
                if hurst_result["hurst_rs"] is not None
                else "n/a"
            )
            log.debug(
                f"    {sym_a}↔{sym_b} [{tf_label}]: "
                f"H_rs={_rs_str} H_dfa={_dfa_str} "
                f"— {hurst_result['interpretation']} (will not enter ML pipeline)"
            )

        # Asset sources from QualityReport (best-effort)
        src_a = "unknown"
        src_b = "unknown"

        n_bars = log_a.size
        n_overlap = int(np.sum(np.isfinite(log_a) & np.isfinite(log_b)))

        # Per-bar series for persistence (see docstring) — carried forward
        # exactly as SpreadModel computed them, not recomputed later.
        # hedge_ratio_ols_t / hedge_ratio_kalman_t: point-in-time causal hedge
        # series persisted so backtest.py can use them at entry time without
        # lookahead (backtest previously used scalar mean values from
        # pairs.parquet which embed full-sample information).
        per_bar = {
            "index": df_a.index,
            "spread": sm["spread"],
            "z_rolling": sm["z_rolling"],
            "z_expanding": sm["z_expanding"],
            "half_life_rolling_series": sm["half_life_rolling_series"],
            "gap_flag_a": gap_flag_a,
            "gap_flag_b": gap_flag_b,
            "hedge_ratio_ols_t": hr["ols_series"],
            "hedge_ratio_kalman_t": hr["kalman_series"],
        }

        # Kalman drift velocity: mean absolute 1-bar change in the Kalman beta
        # over the trailing 20 bars. Captures hedge-ratio instability.
        _kal_series = hr.get("kalman_series")
        _kalman_drift_velocity: Optional[float] = None
        if _kal_series is not None and len(_kal_series) > 21:
            _kal_vals = np.asarray(_kal_series, dtype=float)
            _d_beta = np.abs(np.diff(_kal_vals))
            _tail = _d_beta[-20:]
            _tail = _tail[np.isfinite(_tail)]
            if len(_tail) > 0:
                _kalman_drift_velocity = float(np.mean(_tail))

        pair_result = PairResult(
            symbol_a=sym_a,
            symbol_b=sym_b,
            asset_class_a=pd_meta.get("asset_class_a", "unknown"),
            asset_class_b=pd_meta.get("asset_class_b", "unknown"),
            tf_label=tf_label,
            is_cross_asset=bool(pd_meta.get("is_cross_asset", False)),
            pearson_corr=float(pd_meta.get("pearson_corr", np.nan)),
            coint_pvalue_raw=float(pd_meta.get("coint_pvalue_raw", np.nan)),
            coint_pvalue_adjusted=float(pd_meta.get("coint_pvalue_adjusted", np.nan)),
            coint_fraction_rolling=float(pd_meta.get("coint_fraction_rolling", np.nan)),
            hedge_ratio_ols=(
                float(hr["ols_point"]) if np.isfinite(hr["ols_point"]) else np.nan
            ),
            hedge_ratio_tls=(
                float(hr["tls_point"]) if np.isfinite(hr["tls_point"]) else np.nan
            ),
            hedge_ratio_kalman_mean=(
                float(hr["kalman_mean"]) if np.isfinite(hr["kalman_mean"]) else np.nan
            ),
            half_life_rolling=float(hl_roll) if np.isfinite(hl_roll) else np.nan,
            half_life_expanding=float(hl_exp) if np.isfinite(hl_exp) else np.nan,
            mean_reversion_speed=float(theta) if np.isfinite(theta) else np.nan,
            half_life_trend_slope=(
                float(trend_slope) if np.isfinite(trend_slope) else np.nan
            ),
            zivot_andrews_break=decay["zivot_andrews_break"],
            cusum_first_excursion=decay["cusum_first_excursion"],
            hurst_rs=hurst_result["hurst_rs"],
            hurst_dfa=hurst_result["hurst_dfa"],
            hurst_divergence=hurst_result["hurst_divergence"],
            passes_ml_gate=hurst_result["passes_ml_gate"],
            hurst_interpretation=hurst_result["interpretation"],
            # Eigenportfolio fields initialized as None here;
            # filled in by EigenportfolioDecomposer.run_for_tf() after this loop.
            eigenport_pvalue=None,
            passes_eigenportfolio=None,
            n_factors_removed=None,
            confidence_tier="silver",  # default; upgraded to gold if residual EG passes
            n_bars=int(n_bars),
            n_overlap=int(n_overlap),
            source_a=src_a,
            source_b=src_b,
            kalman_drift_velocity=_kalman_drift_velocity,
        )
        return pair_result, per_bar

    @staticmethod
    def _apply_research_screen_flags(
        pair_results: List["PairResult"],
        tf_label: str,
    ) -> List["PairResult"]:
        """
        Annotate PairResult objects with flags derived from the research/
        comparison-arm screens. Never fetches or modifies pipeline state —
        reads pre-computed parquet files from output/research/ if they exist,
        silently no-ops when they don't (screens may not have been run yet).

        Flags applied:
          thin_info_content — one/both legs in the BUG-D49 price-degeneracy
            screen (genuinely_liquid=True but implausibly few distinct prices).
          permutation_robust — EG circular-shift null result from
            eg_permutation_check.py; None if the pair hasn't been checked.

        Mutates pair_results in place AND returns the list (for call-site
        symmetry with EigenportfolioDecomposer.run_for_tf()).
        """
        import dataclasses as _dc

        research_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "output", "research"
        )

        # --- thin_info_content ---
        degenerate_syms: set = set()
        deg_path = os.path.join(research_dir, f"price_degeneracy_flagged_{tf_label}.parquet")
        if os.path.exists(deg_path):
            try:
                deg_df = pd.read_parquet(deg_path)
                if "symbol" in deg_df.columns:
                    degenerate_syms = set(deg_df["symbol"].tolist())
            except Exception:
                pass

        # --- permutation_robust ---
        perm_lookup: Dict[Tuple[str, str], bool] = {}
        perm_path = os.path.join(research_dir, "eg_permutation_check.parquet")
        if os.path.exists(perm_path):
            try:
                perm_df = pd.read_parquet(perm_path)
                perm_tf = perm_df[perm_df["tf"] == tf_label]
                for _, row in perm_tf.iterrows():
                    key = (row["symbol_a"], row["symbol_b"])
                    perm_lookup[key] = not bool(row["flagged_divergent"])
            except Exception:
                pass

        updated = []
        for pr in pair_results:
            thin = bool(
                degenerate_syms
                and (pr.symbol_a in degenerate_syms or pr.symbol_b in degenerate_syms)
            )
            perm = perm_lookup.get((pr.symbol_a, pr.symbol_b), None)
            if thin != pr.thin_info_content or perm != pr.permutation_robust:
                pr = _dc.replace(pr, thin_info_content=thin, permutation_robust=perm)
            updated.append(pr)
        return updated

    @staticmethod
    def _enrich_with_deep_history(
        discovered_pairs: List[PairResult],
        per_bar_by_pair: Dict[Tuple[str, str], Dict[str, Any]],
        tf_label: str,
    ) -> None:
        """
        Episodic cointegration re-test on IBKR deep history — the purpose
        CLAUDE.md Rule 2 already documents for ibkr_supplement/, finally
        wired up (it existed, fetched by data_ibkr.py, but unread by
        analysis.py until 2026-06-21).

        For each confirmed pair, tries output/cache/ibkr_supplement/
        {symbol}_{tf}_deep.parquet for both legs. Where available, merges
        it with the main cache (supplement's older history + main cache's
        current window, main cache wins on any overlapping date — it's the
        freshest, gap-flag-aware fetch) and recomputes hedge ratio, spread,
        z-score, and a SEPARATE coint_fraction_rolling_deep on the merged
        series — added as a new field alongside (never replacing) the
        original short-window coint_fraction_rolling, so both are visible
        side by side (the project's established fragile-vs-robust
        comparison pattern, applied to the cointegration test itself).

        Mutates discovered_pairs and per_bar_by_pair in place. No-ops
        cleanly when no supplement exists for either leg — by design, not
        by bug, for TFs/pairs where the supplement adds no real depth (3m
        has none at all; 15m's is no deeper than the main cache).

        Known limitation: ibkr_supplement files carry no gap_flag column
        (added by DataAligner, which only ever processed the main cache),
        so DATA_GAP bars within the supplement's OWN history aren't masked
        from this specific deep re-test — documented here and in
        DEVELOPMENT.md rather than silently accepted.
        """
        from ibkr_supplement_reader import load_supplement

        def _merge(main_df, sup_df):
            if sup_df is None:
                return main_df
            combined = pd.concat([sup_df, main_df])
            combined = combined[~combined.index.duplicated(keep="last")]
            return combined.sort_index()

        # Pass 1 (cheap, no process pool): figure out which pairs actually
        # have usable deep data and build their merged close-price series.
        deep_aligned: Dict[str, pd.DataFrame] = {}
        shared_idx_by_pair: Dict[Tuple[str, str], pd.DatetimeIndex] = {}
        pairs_to_test: List[PairResult] = []

        for p in discovered_pairs:
            sup_a = load_supplement(p.symbol_a, tf_label)
            sup_b = load_supplement(p.symbol_b, tf_label)
            if sup_a is None and sup_b is None:
                continue
            main_a = DataStore.load(p.symbol_a, tf_label)
            main_b = DataStore.load(p.symbol_b, tf_label)
            if main_a is None or main_b is None:
                continue

            merged_a = _merge(main_a, sup_a)
            merged_b = _merge(main_b, sup_b)
            shared_idx = merged_a.index.intersection(merged_b.index)
            if len(shared_idx) < 100:
                continue  # not enough overlap to bother re-testing

            deep_aligned[p.symbol_a] = merged_a.loc[shared_idx, ["close"]]
            deep_aligned[p.symbol_b] = merged_b.loc[shared_idx, ["close"]]
            shared_idx_by_pair[(p.symbol_a, p.symbol_b)] = shared_idx
            pairs_to_test.append(p)

        if not pairs_to_test:
            return

        # Pass 2: ONE batched rolling_fraction call covering every pair that
        # needs it, instead of spinning up a fresh ProcessPoolExecutor per
        # pair (the original design — fixed 2026-06-21 after a verification
        # run showed this taking far longer than the main per-pair modeling
        # step, which processes ALL pairs through a single shared pool).
        confirmed_dicts = [
            {"symbol_a": p.symbol_a, "symbol_b": p.symbol_b} for p in pairs_to_test
        ]
        deep_results = CointScanner.rolling_fraction(
            confirmed_dicts, deep_aligned, tf_label, n_workers=min(12, len(pairs_to_test))
        )
        deep_frac_by_key = {
            (r["symbol_a"], r["symbol_b"]): r.get("coint_fraction_rolling", np.nan)
            for r in deep_results
        }

        # Pass 3 (cheap, no process pool — plain numpy/statsmodels calls):
        # refit hedge ratio + spread per pair on its own merged series.
        for p in pairs_to_test:
            key = (p.symbol_a, p.symbol_b)
            shared_idx = shared_idx_by_pair[key]
            close_a = deep_aligned[p.symbol_a]["close"].values
            close_b = deep_aligned[p.symbol_b]["close"].values
            with np.errstate(invalid="ignore", divide="ignore"):
                log_a = np.log(close_a)
                log_b = np.log(close_b)
            log_a[~np.isfinite(log_a)] = np.nan
            log_b[~np.isfinite(log_b)] = np.nan

            try:
                hr_window = min(252, max(60, log_a.size // 4))
                hr = HedgeRatioEstimator.estimate_all_for_pair(log_a, log_b, hr_window)
                sm = SpreadModel.fit_pair(
                    log_a, log_b, hr["ols_series"], hr["ols_point"]
                )
            except Exception as e:
                log.debug(
                    f"  deep-history spread refit failed for "
                    f"{p.symbol_a}/{p.symbol_b}: {type(e).__name__}: {e}"
                )
                continue

            p.coint_fraction_rolling_deep = float(deep_frac_by_key.get(key, np.nan))
            p.deep_history_used = True

            existing_pb = per_bar_by_pair.get(key)
            if existing_pb is None or len(shared_idx) > len(existing_pb["index"]):
                per_bar_by_pair[key] = {
                    "index": shared_idx,
                    "spread": sm["spread"],
                    "z_rolling": sm["z_rolling"],
                    "z_expanding": sm["z_expanding"],
                    "half_life_rolling_series": sm["half_life_rolling_series"],
                    # ibkr_supplement carries no gap_flag — documented
                    # limitation in this method's docstring, not silently
                    # dropped.
                    "gap_flag_a": None,
                    "gap_flag_b": None,
                    "hedge_ratio_ols_t": hr["ols_series"],
                    "hedge_ratio_kalman_t": hr["kalman_series"],
                }
                log.info(
                    f"  [{tf_label}] {p.symbol_a}/{p.symbol_b}: deep history "
                    f"extended series to {len(shared_idx)} bars "
                    f"({shared_idx.min()} to {shared_idx.max()}), "
                    f"coint_fraction_rolling_deep={p.coint_fraction_rolling_deep:.3f}"
                )

    @staticmethod
    def passes_coint_frac_secondary_evidence(p: PairResult) -> bool:
        """
        True if a pair below Config.UNIVERSE.MIN_COINT_FRAC should be kept
        anyway because the OTHER stability-over-time signals (half-life
        trend, structural-break tests) are clean. Pulled out as its own
        testable static method (2026-06-22) rather than left as a nested
        function inside _save_tf_results, specifically so the reasoning
        behind it (see Development.md's coint_fraction_rolling section) can
        be re-verified directly — e.g. debug/_verify_coint_frac_override.py
        — without re-running the full ~140-min analysis.py pipeline.

        Hurst is deliberately NOT part of this check — it answers a
        different question (reversion strength given mean-reversion is
        happening), already gated separately via passes_ml_gate.

        Uses pd.isna() rather than `is None`: zivot_andrews_break/
        cusum_first_excursion are genuine Python None on the live in-memory
        PairResult (set in StrategyDecayDetector.analyze_pair()), but a
        parquet round-trip turns that None into float NaN — caught by
        debug/_verify_coint_frac_override.py running this same function
        against persisted data, not just live objects.
        """
        slope = getattr(p, "half_life_trend_slope", np.nan)
        if not np.isfinite(slope) or slope > 0:
            return False  # decaying or unknown — can't vouch for it
        return bool(
            pd.isna(getattr(p, "zivot_andrews_break", None))
            and pd.isna(getattr(p, "cusum_first_excursion", None))
        )

    @staticmethod
    def _save_tf_results(
        tf_label: str,
        pairs: List[PairResult],
        trios: List[TrioResult],
        regimes: List[RegimeResult],
        cross: List[PairResult],
        calibration: Dict[str, Any],
        per_bar_by_pair: Optional[Dict[Tuple[str, str], Dict[str, Any]]] = None,
        funnel: Optional["FilterFunnel"] = None,
    ) -> List[PairResult]:
        """
        Save all dataclass results to Parquet/JSON in output/results/{tf_label}/.

        Returns discovered_pairs (the actually-persisted set, post structural-
        pair and coint_frac filtering) so the caller can use it as the TF's
        real pair result instead of the pre-filter input. Found 2026-06-23:
        AnalysisPipeline.run()/pairs_by_tf and the run summary log were both
        built from the pre-filter `pairs` argument, so any pair excluded here
        (coint_fraction_rolling < MIN_COINT_FRAC with no secondary-evidence
        override) still showed up as "confirmed" in latest_run_analysis.log
        despite never being written to pairs.parquet/the manifest/spread_series
        — e.g. 1h's PNC/ZION and SPY/VOO, both correctly excluded here, were
        printed as confirmed anyway. Confirmed via the real 07:51 run: log said
        34 total pairs, only 16 were ever actually persisted (matches ml.py's
        own independent "16 confirmed pairs with persisted spread series").
        """
        out_dir = _output_dir(tf_label)

        # Exclude structural pairs (forex triangles, share-class pairs) from the
        # primary pairs.parquet. They are logged in bias_audit.json only.
        # Remove structural pairs (forex triangles, share-class)
        discovered_pairs = [
            p
            for p in pairs
            if not CrossAssetTagger._shared_currency(p.symbol_a, p.symbol_b)
            and not CrossAssetTagger._is_share_class_pair(p.symbol_a, p.symbol_b)
        ]
        # Captured here, before the coint_frac filter below reassigns
        # discovered_pairs again — otherwise n_structural further down would
        # silently include coint_frac exclusions too (found 2026-06-23 while
        # verifying the _save_tf_results return-value fix).
        n_structural = len(pairs) - len(discovered_pairs)
        if funnel is not None:
            funnel.record("structural_exclusion_pairs", len(pairs), len(discovered_pairs))

        # Enforce coint_fraction_rolling minimum (episodic cointegration defense).
        # Pairs cointegrated in <70% of rolling windows are historical episodes.
        # Documented threshold in DEVELOPMENT.md.
        #
        # Secondary-evidence override (added 2026-06-22 — see Development.md,
        # "TF-Level Funnel Analysis" investigation): coint_fraction_rolling
        # alone doesn't always agree with the OTHER signals that measure the
        # same underlying question (is this relationship stable over time,
        # not just historically cointegrated). Checked directly against 3
        # real borderline pairs: D/NEE (0.41) and SPY/VOO (0.45) both showed
        # a decaying half-life trend AND a structural break on both Zivot-
        # Andrews and CUSUM — genuinely unstable, correctly excluded. CRWD/
        # DDOG (0.67) showed neither — an IMPROVING half-life trend and no
        # break on either test — and would have been a false exclusion under
        # a flat cutoff. Hurst is deliberately NOT part of this check: it
        # answers a different question (how strong is the reversion, given
        # it's happening) already gated separately via passes_ml_gate, not
        # whether the relationship itself is stable over time.
        _MIN_COINT_FRAC = getattr(Config.UNIVERSE, "MIN_COINT_FRAC", 0.40)

        _n_before = len(discovered_pairs)
        _n_override = 0
        _kept = []
        for p in discovered_pairs:
            cf = getattr(p, "coint_fraction_rolling", np.nan)
            if not np.isfinite(cf) or cf >= _MIN_COINT_FRAC:
                _kept.append(p)
            elif AnalysisPipeline.passes_coint_frac_secondary_evidence(p):
                p.coint_frac_secondary_override = True
                _kept.append(p)
                _n_override += 1
            # else: excluded
        discovered_pairs = _kept
        if funnel is not None:
            funnel.record("coint_frac_threshold_pairs", _n_before, len(discovered_pairs))
            funnel.save()
        if len(discovered_pairs) < _n_before:
            log.info(
                f"  [{tf_label}] coint_frac filter: "
                f"{_n_before - len(discovered_pairs)} pairs removed "
                f"(coint_fraction_rolling < {_MIN_COINT_FRAC:.2f} and no clean "
                f"secondary evidence); {_n_override} pairs below the threshold "
                f"kept anyway via secondary-evidence override"
            )
        # Write/update the confirmed pairs manifest for data_ibkr.py. This
        # tells the IBKR supplemental pipeline which symbols need deep
        # history for episodic cointegration testing.
        #
        # Runs unconditionally (even when discovered_pairs is empty for this
        # TF), and always clears this TF's tag from every symbol before
        # re-adding it — found 2026-06-23: the old version only ever ADDED
        # entries, never removed them, so a symbol confirmed in a past
        # session/run stayed in the manifest forever even after a later run
        # correctly excluded it (e.g. D/NEE@1m and CRWD/DDOG@1m, both
        # excluded by today's coint_frac filter post the gap-masking fix,
        # were still sitting in the manifest from last night's run — and
        # SPY/VOO@1h was still tagged "1h" despite being excluded today).
        # data_ibkr.py would have kept burning IBKR fetch budget on pairs
        # that are no longer actually confirmed. A symbol whose tfs list
        # becomes empty after this TF's update is dropped from the manifest
        # entirely — it isn't confirmed on ANY timeframe anymore.
        _manifest_path = os.path.join(
            os.path.dirname(out_dir), "confirmed_pairs_manifest.json"
        )
        try:
            _manifest: Dict[str, Any] = {}
            if os.path.exists(_manifest_path):
                with open(_manifest_path) as _f:
                    _manifest = json.load(_f)
            for _entry in _manifest.values():
                if tf_label in _entry["tfs"]:
                    _entry["tfs"].remove(tf_label)
            for _p in discovered_pairs:
                for _sym in (_p.symbol_a, _p.symbol_b):
                    if _sym not in _manifest:
                        _manifest[_sym] = {"tfs": [], "added": tf_label}
                    if tf_label not in _manifest[_sym]["tfs"]:
                        _manifest[_sym]["tfs"].append(tf_label)
            _manifest = {
                _sym: _entry for _sym, _entry in _manifest.items() if _entry["tfs"]
            }
            with open(_manifest_path, "w") as _f:
                json.dump(_manifest, _f, indent=2)
        except Exception as _e:
            log.debug(f"Manifest write failed: {_e}")

        if discovered_pairs:
            pairs_df = pd.DataFrame([asdict(p) for p in discovered_pairs])

            # GICS sector tagging — merge sector/sub_industry onto pair records
            _gics_path = os.path.join(Config.DATA.CACHE_DIR, "gics_tags.csv")
            if os.path.exists(_gics_path):
                try:
                    _gics = pd.read_csv(_gics_path, dtype=str)[
                        ["symbol", "sector", "industry_group", "sub_industry"]
                    ].rename(columns={
                        "sector": "sector_a", "industry_group": "industry_group_a",
                        "sub_industry": "sub_industry_a",
                    })
                    pairs_df = pairs_df.merge(
                        _gics.rename(columns=lambda c: c),
                        left_on="symbol_a", right_on="symbol", how="left"
                    ).drop(columns=["symbol"], errors="ignore")
                    _gics_b = _gics.rename(columns={
                        "sector_a": "sector_b",
                        "industry_group_a": "industry_group_b",
                        "sub_industry_a": "sub_industry_b",
                    })
                    pairs_df = pairs_df.merge(
                        _gics_b, left_on="symbol_b", right_on="symbol", how="left"
                    ).drop(columns=["symbol"], errors="ignore")
                    pairs_df["same_sector"] = (
                        pairs_df["sector_a"].notna() &
                        pairs_df["sector_b"].notna() &
                        (pairs_df["sector_a"] == pairs_df["sector_b"])
                    )
                    n_tagged = pairs_df["sector_a"].notna().sum()
                    log.info(f"  [{tf_label}] GICS tagged: {n_tagged}/{len(pairs_df)} pairs have sector_a")
                except Exception as _ge:
                    log.debug(f"GICS merge failed: {_ge}")

            pairs_df.to_parquet(os.path.join(out_dir, "pairs.parquet"))
            log.info(
                f"  [{tf_label}] saved {len(discovered_pairs)} pairs "
                f"→ {out_dir}/pairs.parquet"
            )

            # Episodic cointegration re-test on IBKR deep history, where
            # available — mutates discovered_pairs/per_bar_by_pair in place
            # BEFORE the persistence step below, so spread_series_*.parquet
            # reflects the deepest available history.
            if per_bar_by_pair:
                AnalysisPipeline._enrich_with_deep_history(
                    discovered_pairs, per_bar_by_pair, tf_label
                )
                # coint_fraction_rolling_deep was added after pairs_df was
                # already built/saved above — re-save with the enriched
                # columns now that they're populated.
                pairs_df = pd.DataFrame([asdict(p) for p in discovered_pairs])
                pairs_df.to_parquet(os.path.join(out_dir, "pairs.parquet"))

            # Persist per-bar spread/z-score/half-life series for every pair
            # that survived EG+FDR and the price-degeneracy filter (`pairs`),
            # NOT just the final post-coint_frac/post-structural set
            # (`discovered_pairs`) — added 2026-06-21 for ml.py's labeled
            # training examples; extended 2026-06-30 (Phase 1 filter-ablation
            # work) to cover the broader `pairs` set specifically so a pair
            # excluded by the coint_frac threshold or the structural-pair
            # filter still has a spread_series file on disk and can be
            # counterfactually backtested via `backtest.py --pairs-override`
            # (research/filter_ablation.py). Before this change, spread_series
            # existed only for `discovered_pairs`, making "what if this filter
            # hadn't excluded these pairs" impossible to test — the very data
            # needed to answer that question was never saved. Price-degeneracy
            # exclusions are NOT covered here (those pairs are dropped from
            # `pairs` itself, one step earlier in `_run_one_tf`, before this
            # function is even called) — an accepted scope limit, since a
            # spread built on a price-degenerate series (2-7 distinct closes)
            # isn't a meaningful counterfactual to begin with. See
            # DEVELOPMENT.md ml.py section. Per-bar regime-state labels
            # deliberately NOT included here (RegimeClassifier.predict_labels()
            # is unused/orphaned today and fitting it would add ~15-20% pipeline
            # runtime) — deferred to a follow-up pass, not this one.
            if per_bar_by_pair:
                _n_persisted = 0
                for _p in pairs:
                    _pb = per_bar_by_pair.get((_p.symbol_a, _p.symbol_b))
                    if _pb is None:
                        continue
                    try:
                        _series_df = pd.DataFrame(
                            {
                                "spread": _pb["spread"],
                                "z_rolling": _pb["z_rolling"],
                                "z_expanding": _pb["z_expanding"],
                                "half_life_rolling": _pb["half_life_rolling_series"],
                                "gap_flag_a": _pb["gap_flag_a"],
                                "gap_flag_b": _pb["gap_flag_b"],
                                "hedge_ratio_ols_t": _pb.get("hedge_ratio_ols_t"),
                                "hedge_ratio_kalman_t": _pb.get("hedge_ratio_kalman_t"),
                            },
                            index=_pb["index"],
                        )
                        _series_df.to_parquet(
                            os.path.join(
                                out_dir,
                                f"spread_series_{_p.symbol_a}_{_p.symbol_b}.parquet",
                            )
                        )
                        _n_persisted += 1
                    except Exception as _e:
                        log.debug(
                            f"  spread_series persist failed for "
                            f"{_p.symbol_a}/{_p.symbol_b}: {_e}"
                        )
                if _n_persisted:
                    log.info(
                        f"  [{tf_label}] persisted per-bar spread/z-score series "
                        f"for {_n_persisted}/{len(pairs)} EG+FDR-confirmed pairs "
                        f"(post price-degeneracy filter, pre coint_frac/structural)"
                    )

            # Persist the full pre-coint_frac/pre-structural candidate set
            # (`pairs`, with the same schema as pairs.parquet) so
            # research/filter_ablation.py can build --pairs-override files
            # for the coint_frac and structural filters directly from this —
            # no need to reconstruct pair metadata from scratch.
            if pairs:
                all_candidates_df = pd.DataFrame([asdict(p) for p in pairs])
                all_candidates_df.to_parquet(os.path.join(out_dir, "all_candidates.parquet"))
                log.info(
                    f"  [{tf_label}] saved {len(pairs)} pre-coint_frac/pre-structural "
                    f"candidates → {out_dir}/all_candidates.parquet"
                )
        if n_structural:
            log.info(
                f"  [{tf_label}] {n_structural} structural pairs excluded "
                f"from pairs.parquet (logged to bias_audit)"
            )

        if cross:
            cross_df = pd.DataFrame([asdict(p) for p in cross])
            cross_df.to_parquet(os.path.join(out_dir, "cross_asset_pairs.parquet"))
            log.info(f"  [{tf_label}] saved {len(cross)} cross-asset pairs")

        # Note: structural forex pairs (triangular arbitrage) are logged to
        # bias_audit.json but not saved as separate results files — they are
        # not primary findings and need no further analysis.

        if trios:
            trios_df = pd.DataFrame([asdict(t) for t in trios])
            trios_df.to_parquet(os.path.join(out_dir, "trios.parquet"))
            log.info(f"  [{tf_label}] saved {len(trios)} trios")

        if regimes:
            # Regimes contain lists (transition matrix); flatten with JSON
            regimes_path = os.path.join(out_dir, "regimes.json")
            with open(regimes_path, "w") as f:
                json.dump([asdict(r) for r in regimes], f, indent=2)
            log.info(f"  [{tf_label}] saved {len(regimes)} regime profiles")

        if calibration:
            calib_path = os.path.join(out_dir, "calibration.json")
            with open(calib_path, "w") as f:
                json.dump(calibration, f, indent=2, default=str)
            log.info(f"  [{tf_label}] saved calibration results")

        return discovered_pairs


# =============================================================================
# ENTRY POINT
# =============================================================================


def main(
    timeframes: Optional[List[str]] = None,
    run_calibration: bool = True,
    n_workers: int = 12,
) -> AnalysisResults:
    """
    Entry point — build universe from cache, then run analysis pipeline.
    Always runs with connect=False; IBKR is never touched by analysis.py.

    Args:
        timeframes:      Subset of Config.DATA.TIMEFRAME_LABELS to process,
                         or None for all.
        run_calibration: Whether to run ThresholdCalibrator on 1D.
        n_workers:       Parallelism for EG / Johansen / rolling tests.
    """
    log.info("=" * 70)
    log.info("CAMARF  —  analysis.py  —  Cross-Asset Co-Movement Analysis")
    log.info("=" * 70)

    # Step 1: build / load universe via data.py
    # connect=False: skips IBKR entirely, loads all data from cache.
    # analysis.py is a consumer of cached data — never fetches from IBKR.
    builder = UniverseBuilder()
    universe = builder.build(connect=False, fetch=False)
    log.info(
        f"Universe loaded: {len(universe.assets)} assets, "
        f"{len(universe.data)} symbol-TF combinations"
    )

    # Step 2: run analysis pipeline
    results = AnalysisPipeline.run(
        universe=universe,
        timeframes=timeframes,
        run_calibration=run_calibration,
        n_workers=n_workers,
    )

    # Step 3: emit final summary
    log.info("=" * 70)
    log.info("ANALYSIS RESULTS — SUMMARY")
    log.info("=" * 70)
    for tf in results.timeframes_processed:
        pairs = results.pairs_by_tf.get(tf, [])
        cross = results.cross_asset_pairs.get(tf, [])
        trios = results.trios_by_tf.get(tf, [])
        regimes = results.regimes_by_tf.get(tf, [])
        log.info(
            f"  {tf:>4s}  pairs={len(pairs):>5d}  "
            f"cross={len(cross):>4d}  trios={len(trios):>4d}  "
            f"regimes={len(regimes):>4d}"
        )
    log.info(f"  Total bias-audit entries: {len(results.bias_audit)}")
    log.info(f"  Runtime: {results.runtime_seconds/60:.1f} min")
    log.info("=" * 70)

    # Write compact run summary for LLM diagnosis
    _write_analysis_summary(results, universe)
    return results


def _write_analysis_summary(results: Any, universe: Any) -> None:
    """
    Write a compact structured run summary to latest_run_analysis.log.
    Designed for direct upload to an LLM for diagnosis.
    """
    import json as _json

    _LOG_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "latest_run_analysis.log"
    )
    lines = [
        "=== CAMARF analysis.py ===",
        f"date:        {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        f"runtime_min: {results.runtime_seconds/60:.1f}",
        f"universe:    {len(universe.assets)} assets  "
        f"{len(universe.data)} symbol-TF keys",
        "",
        "=== results_by_tf ===",
        "tf    pairs cross trios regimes",
    ]
    total_pairs = total_trios = total_regimes = 0
    for tf in results.timeframes_processed:
        p = len(results.pairs_by_tf.get(tf, []))
        cr = len(results.cross_asset_pairs.get(tf, []))
        tr = len(results.trios_by_tf.get(tf, []))
        rg = len(results.regimes_by_tf.get(tf, []))
        total_pairs += p + cr
        total_trios += tr
        total_regimes += rg
        lines.append(f"{tf:<6}{p:<6}{cr:<6}{tr:<6}{rg}")
    lines += [
        f"TOTAL  {total_pairs:<6}      {total_trios:<6}{total_regimes}",
        f"bias_audit_entries: {len(results.bias_audit)}",
        "",
        "=== confirmed_pairs ===",
    ]
    def _fnum(val, fmt):
        return format(val, fmt) if val is not None and np.isfinite(val) else "nan"

    all_pairs = []
    for tf, pairs in results.pairs_by_tf.items():
        for pr in pairs:
            hl = pr.half_life_rolling
            if hl is None or not np.isfinite(hl):
                hl = pr.half_life_expanding
            all_pairs.append(
                f"{tf:<6} {pr.symbol_a:<8} {pr.symbol_b:<8} "
                f"hl={_fnum(hl, '.1f')}  "
                f"H={_fnum(pr.hurst_rs, '.3f')}  "
                f"tier={getattr(pr,'confidence_tier','?')}  "
                f"coint_frac={_fnum(pr.coint_fraction_rolling, '.2f')}"
            )
    lines += all_pairs if all_pairs else ["  none"]
    lines += ["", "=== errors_and_skipped ==="]
    # Collect from bias audit
    skipped_tfs = [
        e
        for e in results.bias_audit
        if "skipped" in str(e).lower() or "mismatch" in str(e).lower()
    ]
    for e in skipped_tfs[:20]:
        lines.append(f"  {str(e)[:100]}")
    lines += ["", "=== end ==="]
    try:
        with open(_LOG_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        log.info(f"Run summary → {_LOG_PATH}")
    except Exception as e:
        log.debug(f"Analysis summary write failed: {e}")


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="CAMARF analysis pipeline")
    p.add_argument(
        "--timeframes",
        nargs="+",
        default=None,
        help="Specific timeframes to process (default: all)",
    )
    p.add_argument(
        "--no-calibration", action="store_true", help="Skip ThresholdCalibrator on 1D"
    )
    p.add_argument("--workers", type=int, default=12, help="Parallel worker count")
    args = p.parse_args()

    main(
        timeframes=args.timeframes,
        run_calibration=not args.no_calibration,
        n_workers=args.workers,
    )
