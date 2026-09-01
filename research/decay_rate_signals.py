"""
research/decay_rate_signals.py -- Thread Q new path: cointegration decay-RATE
signals (2026-08-24 scoping, see Development.md). Not the LEVEL of a
relationship (coint_fraction_rolling_t itself, or age since onset -- Thread Q
Idea 1's compute_regime_age_weights), but its DERIVATIVE: is the relationship
currently strengthening or weakening. 3 raw signals x 3 smoothing methods,
all reusing production machinery directly, no reimplementation of EG/half-life
estimation.

Raw signals (all causal/PIT-safe, forward-filled between refresh points, same
convention CointScanner.expanding_coint_fraction/SpreadModel.rolling_half_life
already establish):
  - coint_fraction: analysis.py's own CointScanner.expanding_coint_fraction
    output (coint_fraction_rolling_t column, already persisted in
    spread_series_*.parquet -- reused directly, not recomputed).
  - eg_pvalue: NEW here (expanding_eg_pvalue_series) -- same windowed/batched
    EG machinery as expanding_coint_fraction (same window/step/gap-handling,
    same _batched_eg_fixed_lag_tstat call), but forward-fills the raw p-value
    at each window's end instead of accumulating a running significant
    fraction. Kept in research/ (not analysis.py) since this is a
    comparison-arm signal, not a production pipeline output -- computed
    fresh from cached log-prices, not persisted anywhere in
    output/results/.
  - half_life: analysis.py's own SpreadModel.rolling_half_life output
    (half_life_rolling_series column, already persisted) -- the raw rolling
    half-life LEVEL, not the pre-computed half_life_trend_slope_t (which is
    itself one specific smoothing -- expanding OLS -- of this same raw
    series; reproduced here as one of the 3 smoothing options below for a
    fair, apples-to-apples comparison against the other 2).

Smoothing methods (Ross's own 2026-08-24 direction: "if slopes are noisy we
should figure out a way to average it or kalman it or use a fast/slow filter
for comparison"):
  - sma: trailing simple moving average of the raw level, THEN first-
    difference the smoothed level.
  - kalman: causal 1D Kalman filter (pure random-walk state model, no
    separate velocity state -- the simplest well-posed causal filter, this
    project has no independent motivation for a more complex one) on the
    raw level, THEN first-difference the filtered level.
  - fast_slow: (fast trailing mean) - (slow trailing mean) of the raw level,
    MACD-style -- already a rate-of-change-like quantity by construction, no
    separate differencing step needed.

All smoothing operates on the COMPACTED (real-bar-only) series, never the
dense gap-padded grid directly -- same fix class as big_move_lead_lag.py's
_big_move_dates docstring (a rolling window over the dense grid almost never
lands on `window` consecutive real values).

Verified first: debug/_verify_decay_rate_signals.py.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analysis import _batched_eg_fixed_lag_tstat, longest_gap_respecting_segment
from statsmodels.tsa.stattools import mackinnonp

SIGNAL_NAMES = ("coint_fraction", "eg_pvalue", "half_life")
SMOOTHING_NAMES = ("sma", "kalman", "fast_slow")


# ---------------------------------------------------------------------------
# Raw signal: EG p-value rolling series (new -- see module docstring)
# ---------------------------------------------------------------------------

def expanding_eg_pvalue_series(log_a: np.ndarray, log_b: np.ndarray, tf_label: str,
                                window: int = 252, step: int = 21) -> np.ndarray:
    """Causal, point-in-time-safe per-bar EG p-value series -- structurally
    identical windowing/gap-handling to analysis.py's own
    CointScanner.expanding_coint_fraction, but forward-fills the raw p-value
    at each window's end instead of accumulating a running significant
    fraction. Returns NaN before the first full window."""
    mask = np.isfinite(log_a) & np.isfinite(log_b)
    keep = longest_gap_respecting_segment(mask, tf_label)
    pval_series = np.full(log_a.size, np.nan, dtype=float)
    n = int(np.sum(keep))
    if n < window + step:
        new_window = max(60, n // 3)
        new_step = max(5, new_window // 10)
        if new_window < window + new_step:
            return pval_series
        window, step = new_window, new_step
    a = log_a[keep]
    b = log_b[keep]
    real_positions = np.flatnonzero(keep)
    starts = list(range(0, n - window + 1, step))
    if not starts:
        return pval_series
    a_windows = np.stack([a[s:s + window] for s in starts])
    b_windows = np.stack([b[s:s + window] for s in starts])
    t_stats = _batched_eg_fixed_lag_tstat(a_windows, b_windows)
    for i, start in enumerate(starts):
        t = t_stats[i]
        if not np.isfinite(t):
            continue
        p = mackinnonp(float(t), regression="c", N=2)
        end_pos_full = real_positions[start + window - 1]
        pval_series[end_pos_full] = p
    return pd.Series(pval_series).ffill().values


# ---------------------------------------------------------------------------
# Smoothing + slope
# ---------------------------------------------------------------------------

def _compact(series: np.ndarray):
    """Returns (compact_values, real_index_positions) -- rolling operations
    run on the compacted series, results scattered back to the dense index."""
    idx = np.flatnonzero(np.isfinite(series))
    return series[idx], idx


def smooth_sma(series: np.ndarray, window: int = 10) -> np.ndarray:
    """Trailing SMA of the compacted series, scattered back to dense index."""
    compact, idx = _compact(series)
    out = np.full(series.size, np.nan, dtype=float)
    if compact.size < window:
        return out
    sm = pd.Series(compact).rolling(window, min_periods=window).mean().values
    out[idx] = sm
    return out


def smooth_kalman(series: np.ndarray, process_var: float = 1e-4, obs_var: float = 1e-2) -> np.ndarray:
    """Causal 1D Kalman filter, pure random-walk state model (x_t = x_{t-1} +
    process noise, y_t = x_t + observation noise) -- the simplest well-posed
    causal filter for a noisy level series, no separate velocity state this
    project has no independent motivation to add. process_var/obs_var are
    the filter's own noise-variance hyperparameters, stated not tuned --
    real tuning is future comparison-arm work, not assumed correct here."""
    compact, idx = _compact(series)
    out = np.full(series.size, np.nan, dtype=float)
    n = compact.size
    if n < 2:
        return out
    x = compact[0]
    p = 1.0
    filtered = np.empty(n, dtype=float)
    filtered[0] = x
    for t in range(1, n):
        p = p + process_var
        k = p / (p + obs_var)
        x = x + k * (compact[t] - x)
        p = (1 - k) * p
        filtered[t] = x
    out[idx] = filtered
    return out


def smooth_fast_slow(series: np.ndarray, fast_window: int = 5, slow_window: int = 20) -> np.ndarray:
    """MACD-style fast-minus-slow trailing mean of the compacted series --
    already a rate-of-change-like quantity, no separate differencing step."""
    compact, idx = _compact(series)
    out = np.full(series.size, np.nan, dtype=float)
    if compact.size < slow_window:
        return out
    s = pd.Series(compact)
    fast = s.rolling(fast_window, min_periods=fast_window).mean()
    slow = s.rolling(slow_window, min_periods=slow_window).mean()
    out[idx] = (fast - slow).values
    return out


def causal_slope(series: np.ndarray, lookback: int = 10) -> np.ndarray:
    """First-difference-style causal slope: value now minus value
    `lookback` real bars ago, on the compacted series. Used for sma/kalman
    (level series that need explicit differencing); fast_slow is already a
    rate-of-change quantity and should NOT be passed through this again."""
    compact, idx = _compact(series)
    out = np.full(series.size, np.nan, dtype=float)
    if compact.size <= lookback:
        return out
    diff = np.full(compact.size, np.nan, dtype=float)
    diff[lookback:] = compact[lookback:] - compact[:-lookback]
    out[idx] = diff
    return out


def decay_rate_series(raw_level_series: np.ndarray, smoothing: str, lookback: int = 10) -> np.ndarray:
    """raw_level_series -> a decay-rate series under one of the 3 smoothing
    methods. Positive = level rising, negative = level falling -- caller
    must know the SIGN CONVENTION per signal (rising coint_fraction vs.
    rising eg_pvalue vs. rising half_life do NOT all mean the same thing --
    see decay_rate_direction() below, not assumed uniform)."""
    if smoothing == "sma":
        return causal_slope(smooth_sma(raw_level_series), lookback)
    if smoothing == "kalman":
        return causal_slope(smooth_kalman(raw_level_series), lookback)
    if smoothing == "fast_slow":
        return smooth_fast_slow(raw_level_series)
    raise ValueError(f"Unknown smoothing: {smoothing!r} (expected one of {SMOOTHING_NAMES})")


def decay_rate_direction(signal_name: str) -> int:
    """+1 if a POSITIVE decay_rate_series value means the relationship is
    STRENGTHENING for this signal, -1 if it means WEAKENING -- the 3 raw
    signals do not share a sign convention:
      - coint_fraction rising = strengthening (+1)
      - eg_pvalue rising = LESS significant = weakening (-1)
      - half_life rising = slower mean reversion = weakening (-1)
    Callers should multiply decay_rate_series's output by this so "positive
    decay_rate" always means "strengthening" uniformly downstream, regardless
    of which raw signal was used."""
    if signal_name == "coint_fraction":
        return 1
    if signal_name in ("eg_pvalue", "half_life"):
        return -1
    raise ValueError(f"Unknown signal: {signal_name!r} (expected one of {SIGNAL_NAMES})")
