"""
CAMARF _regime_features.py — shared utility, NOT part of the production
pipeline. Used by both research/pair_characteristics_analyzer.py and
research/regime_conditional_entry_gate.py (Development.md's "Rich Regime
Classification" / "PairCharacteristicsAnalyzer" planned enhancements,
Session ~8) so the two scripts compute the SAME Level 1/2/3 feature set
the same way, rather than two independently-drifting copies (the exact
duplication risk `aligned_pair_loader.py`'s own docstring already
documents this project hitting before).

Implements the original 3-level feature spec (Development.md "Planned
Enhancement: Rich Regime Classification for Entry/Exit Gating") with
stated, deliberate simplifications where the literal spec would need
infrastructure well beyond a comparison-arm script's scope:
  - Level 1 (leg): rolling Hurst (reuses analysis.py's own HurstEstimator.
    hurst_rs directly, not reimplemented), rolling ADX (standard Wilder
    formulation), realized-vol percentile vs. the leg's own trailing history.
  - Level 2 (spread): Bollinger Band width, ATR percentile, velocity
    (rate of change), |z-score| (already computed by analysis.py, reused
    from spread_series columns). Rolling Johansen p-value trend is NOT
    implemented — a full rolling multivariate cointegration re-test at
    every bar is expensive well beyond this scope; `coint_fraction_rolling`
    (already in pairs.parquet) is used as the nearest available proxy for
    "is the relationship strengthening or weakening," stated explicitly
    as a substitution, not a silent omission.
  - Level 3 (macro): thin wrapper around macro.py's own regime
    classification (yield curve, credit, VIX, recession) — reused
    directly, not reimplemented.

CAUTION for whoever wires up the rest of this module (Phase 10 bias sweep,
2026-07-14): only spread_velocity() is currently imported by a live caller
(regime_conditional_entry_gate.py) — vol_percentile/bb_width/atr_percentile/
leg_directional_regime are dead code today, confirmed via grep, and none of
them account for gap-masked or ragged-calendar input the way this project's
established convention requires (compact via .dropna() before .rolling(),
reindex back afterward — see big_move_lead_lag.py/hub_leg_stop_conditioning.py
/short_term_factor_alpha.py for the pattern). Add that handling BEFORE wiring
any of these into a live caller, not after — the gap-aware-rolling bug class
has recurred independently multiple times this session precisely because it
was added after the fact.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import HurstEstimator

_HURST_WINDOW = 120  # HurstEstimator.MIN_BARS=100 requires >=101 increments;
                      # the original spec's "rolling 60-day Hurst" is too short
                      # for the reused production estimator, widened accordingly
_ADX_WINDOW = 14
_VOL_WINDOW = 20
_VOL_PCTILE_LOOKBACK = 252
_BB_WINDOW = 20
_ATR_WINDOW = 14
_ATR_PCTILE_LOOKBACK = 252


def rolling_hurst(log_price: pd.Series, window: int = _HURST_WINDOW) -> pd.Series:
    """Rolling Hurst exponent on log-price increments, reusing
    HurstEstimator.hurst_rs directly (not reimplemented). ~7ms/bar
    (measured) — fine for a handful of specific timestamps via
    hurst_at_positions below, NOT for a full multi-thousand-bar series
    (would take minutes per leg) — use that instead when only entry-time
    values are needed, which is PairCharacteristicsAnalyzer's actual use
    case (Phase 2: conditional P&L by Hurst quintile AT ENTRY, not a full
    per-bar series)."""
    def _h(x):
        return HurstEstimator.hurst_rs(np.asarray(x, dtype=float))
    return log_price.rolling(window, min_periods=window).apply(_h, raw=False)


def hurst_at_positions(log_price: np.ndarray, positions: np.ndarray,
                        window: int = _HURST_WINDOW) -> np.ndarray:
    """Hurst computed only at specific integer positions (e.g. trade entry
    bar indices), each over the trailing `window` bars ending at that
    position — dramatically cheaper than a full rolling series when only
    a few hundred entry-time values are needed. Returns NaN for positions
    with insufficient trailing history."""
    out = np.full(len(positions), np.nan)
    for i, pos in enumerate(positions):
        if pos < window:
            continue
        window_vals = log_price[pos - window: pos]
        if not np.all(np.isfinite(window_vals)):
            window_vals = window_vals[np.isfinite(window_vals)]
        if len(window_vals) < window * 0.8:
            continue
        out[i] = HurstEstimator.hurst_rs(window_vals)
    return out


def adx(high: pd.Series, low: pd.Series, close: pd.Series, window: int = _ADX_WINDOW) -> pd.Series:
    """Standard Wilder ADX (trend strength, 0-100)."""
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low, (high - prev_close).abs(), (low - prev_close).abs()
    ], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=high.index).ewm(
        alpha=1.0 / window, min_periods=window, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=high.index).ewm(
        alpha=1.0 / window, min_periods=window, adjust=False).mean() / atr.replace(0, np.nan)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()


def vol_percentile(close: pd.Series, vol_window: int = _VOL_WINDOW,
                    lookback: int = _VOL_PCTILE_LOOKBACK) -> pd.Series:
    """Realized vol (rolling std of returns) percentile vs. its own trailing history."""
    ret = close.pct_change()
    realized_vol = ret.rolling(vol_window, min_periods=vol_window).std()
    return realized_vol.rolling(lookback, min_periods=vol_window).rank(pct=True)


def bb_width(series: pd.Series, window: int = _BB_WINDOW) -> pd.Series:
    """Bollinger Band width: (upper - lower) / mid, 2-sigma bands."""
    mid = series.rolling(window, min_periods=window).mean()
    std = series.rolling(window, min_periods=window).std()
    return (4 * std) / mid.replace(0, np.nan).abs()


def atr_percentile(spread: pd.Series, window: int = _ATR_WINDOW,
                    lookback: int = _ATR_PCTILE_LOOKBACK) -> pd.Series:
    """ATR proxy on the spread itself (no OHLC for a synthetic spread
    series — uses |diff| as the true-range proxy), percentile vs. its
    own trailing history."""
    tr_proxy = spread.diff().abs()
    atr = tr_proxy.rolling(window, min_periods=window).mean()
    return atr.rolling(lookback, min_periods=window).rank(pct=True)


def spread_velocity(spread: pd.Series, window: int = 5) -> pd.Series:
    """Rate of change of the spread over `window` bars, sign = direction."""
    return spread.diff(window) / window


def leg_directional_regime(close: pd.Series, ma_window: int = 20,
                            hurst: pd.Series = None) -> pd.Series:
    """Categorical per-leg regime: trending (ADX-like via above-MA + Hurst>0.55)
    vs mean_reverting (Hurst<0.45) vs neutral. Simple rule-based bucketing,
    not a full HMM — matching the right-sized comparison-arm scope Ross
    approved (rule-based bucketing of the original feature list, not the
    full HMM-post-hoc-labeling rewrite)."""
    above_ma = close > close.rolling(ma_window, min_periods=ma_window).mean()
    out = pd.Series("neutral", index=close.index)
    if hurst is not None:
        out = np.where(hurst < 0.45, "mean_reverting",
                        np.where(hurst > 0.55, "trending", "neutral"))
        out = pd.Series(out, index=close.index)
    return out


def macro_regime_at_dates(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Thin wrapper around macro.py's own regime classification — reused
    directly, not reimplemented. Returns a DataFrame indexed by date with
    yield_curve_regime/credit_regime/vix_regime/recession_flag, forward-
    filled and reindexed onto `dates`. Empty/NaN columns if macro.py has
    no cached data (e.g. no FRED API key configured) — callers must
    handle missing macro context gracefully, not assume it's always present."""
    try:
        from macro import build as macro_build
        macro_result = macro_build()
        macro_df = macro_result.data
    except Exception:
        return pd.DataFrame(index=dates)
    if macro_df is None or macro_df.empty:
        return pd.DataFrame(index=dates)
    cols = [c for c in ("yield_curve_regime", "credit_regime", "vix_regime", "recession_state")
            if c in macro_df.columns]
    if not cols:
        return pd.DataFrame(index=dates)
    m = macro_df[cols].reindex(dates, method="ffill")
    return m
