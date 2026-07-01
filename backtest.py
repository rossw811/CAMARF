"""
CAMARF backtest.py — Walk-forward backtesting engine.

Layer 1: Event-driven baseline (pure mean-reversion signal, no ML conditioning).
  - Enter when |z_rolling| >= ENTRY_ZSCORE (2.0)
  - Exit when z crosses EXIT_ZSCORE (0.0), OR |z| >= STOP_ZSCORE (3.5),
    OR hold bars >= MAX_HOLD_MULTIPLIER × half_life_at_entry,
    OR rolling correlation drops below CORR_EXIT_THRESHOLD (structural breakdown)
  - Fixed N_SHARES_PER_TRADE leg-A shares, N × hedge_ratio leg-B shares
  - Max capital concentration: MAX_CONCENTRATION_PCT of account per pair

Layer 2: ML-conditioned + regime-conditioned (disabled, LAYER2_ENABLED = False).
  - Regime hard filter: reject entries in unfavorable VIX term structure / yield curve
  - ML gate: only enter when P(converge) >= ML_GO_THRESHOLD
  - Sizing: binary (normal vs. 0) or continuous (weight by hl_ratio)
  Enable by setting Config.BACKTEST.LAYER2_ENABLED = True once Layer 1 is verified.

Bias audit (per Development.md BiasAuditLog):
  EPISODIC SURVIVORSHIP: pairs confirmed as of run date only. Pairs that were
  cointegrated historically but broke down and were never confirmed are absent
  from the universe by construction. Mid-backtest structural breakdown (correlation
  exit, stop trigger) IS captured within the run period — this is a weaker form
  than full-sample survivorship but not zero. Documented, not corrected.

  HEDGE RATIO LOOKAHEAD: OLS hedge ratio estimated on the full sample → lookahead
  bias (strategy wouldn't have known this at entry time). Kalman mean is the
  average of a roll-forward calibrated filter — still some lookahead in the mean,
  but far less than OLS. Both exposed via HEDGE_METHOD = "both". Reported per-method.

  HOLDOUT: last HOLDOUT_PCT (20%) of each pair's history is chronologically reserved.
  Layer 1 full-series run is labeled IS. Layer 2 runs holdout only.

Usage:
    python backtest.py
    python backtest.py --tf 1h --hedge ols --no-layer2
"""
import argparse
import logging
import os
import sys
import warnings
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config
from data import GapFlag

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

_LOG_PATH = "latest_run_backtest.log"

# ---------------------------------------------------------------------------
# Constants (from Config, overridable by args)
# ---------------------------------------------------------------------------
_TF_DIRS = [
    ("1min", "1m"), ("2min", "2m"), ("3min", "3m"), ("5min", "5m"),
    ("15min", "15m"), ("30min", "30m"), ("1hr", "1h"), ("4hr", "4h"),
]

# ---------------------------------------------------------------------------
# Trade record
# ---------------------------------------------------------------------------
@dataclass
class Trade:
    # Identity
    tf: str
    symbol_a: str
    symbol_b: str
    hedge_method: str           # "ols" | "kalman"
    hedge_ratio: float

    # Entry
    entry_time: pd.Timestamp
    entry_z: float
    entry_spread: float
    side: str                   # "long" | "short"
    n_shares_a: int
    n_shares_b: float           # n_shares_a × hedge_ratio
    half_life_at_entry: float
    hurst_at_entry: float

    # Exit
    exit_time: Optional[pd.Timestamp] = None
    exit_z: float = np.nan
    exit_spread: float = np.nan
    exit_reason: str = ""       # "signal_exit" | "stop" | "max_hold" | "corr_exit" | "eod"

    # P&L
    pnl_gross: float = np.nan   # spread units × n_shares_a
    pnl_cost: float = np.nan    # commission (see note in docstring)
    pnl_net: float = np.nan

    # MAE / MFE (adverse / favorable excursion in spread units)
    mae: float = np.nan         # Maximum Adverse Excursion
    mfe: float = np.nan         # Maximum Favorable Excursion
    hold_bars: int = 0

    # Layer 2 context (populated if LAYER2_ENABLED)
    ml_prob: float = np.nan
    vix_ts_regime: str = ""
    yield_regime: str = ""
    comomentum_at_entry: float = np.nan
    regime_size_multiplier: float = 1.0  # 1.0 = unmodified by regime sizing


# ---------------------------------------------------------------------------
# Spread series loader
# ---------------------------------------------------------------------------
def _spread_path(tf_dir: str, sym_a: str, sym_b: str) -> str:
    return f"output/results/{tf_dir}/spread_series_{sym_a}_{sym_b}.parquet"


def _load_spread(tf_dir: str, sym_a: str, sym_b: str) -> Optional[pd.DataFrame]:
    p = _spread_path(tf_dir, sym_a, sym_b)
    if not os.path.exists(p):
        return None
    df = pd.read_parquet(p)
    # Require minimum columns
    required = {"spread", "z_rolling", "half_life_rolling"}
    if not required.issubset(df.columns):
        log.warning("Spread series %s missing columns %s", p, required - set(df.columns))
        return None
    return df


# ---------------------------------------------------------------------------
# Cost model
# ---------------------------------------------------------------------------
def _compute_cost(
    entry_spread: float,
    hedge: float,
    n_shares_a: int,
    commission_per_share: float,
    slippage_bps: float,
) -> float:
    """
    Round-trip cost for 1 entry + 1 exit.
    Commission: flat per share on both legs, both directions.
    Slippage: bps applied to |spread| as a proxy for position value
              (exact would need leg prices — see bias note in module docstring).
    """
    n_shares_b = n_shares_a * abs(hedge)
    commission = commission_per_share * (n_shares_a + n_shares_b) * 2  # round trip
    slippage = slippage_bps / 10_000 * abs(entry_spread) * n_shares_a * 2
    return commission + slippage


# ---------------------------------------------------------------------------
# Layer 2 regime conditioner (stub — enabled by LAYER2_ENABLED flag)
# ---------------------------------------------------------------------------
class RegimeConditioner:
    """
    Loads regime data and, if LAYER2_ENABLED, filters/sizes entries by
    macro regime. Disabled by default.

    Regime data sources:
      - output/research/regime_conditional_analysis.parquet (hl_ratio by regime)
      - output/research/hmm_regimes.parquet (daily HMM states)
      - macro.build() data (yield_curve_regime, vix_term_structure columns)
    """

    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self._hmm: Optional[pd.DataFrame] = None
        self._macro: Optional[pd.DataFrame] = None
        if enabled:
            self._load()

    def _load(self) -> None:
        hmm_path = "output/research/hmm_regimes.parquet"
        if os.path.exists(hmm_path):
            self._hmm = pd.read_parquet(hmm_path)
            log.info("RegimeConditioner: loaded HMM states (%d rows)", len(self._hmm))
        try:
            from macro import build as macro_build
            macro = macro_build(force_refresh=False)
            self._macro = macro.data
            log.info("RegimeConditioner: loaded macro data (%d rows, cols=%s)",
                     len(self._macro), list(self._macro.columns)[:6])
        except Exception as e:
            log.warning("RegimeConditioner: macro load failed (%s) — regime filter disabled", e)

    def _get_regime(self, ts: pd.Timestamp) -> Dict[str, str]:
        """Return regime labels at timestamp ts."""
        out = {"vix_ts": "", "yield": ""}
        if self._macro is None:
            return out
        date = ts.normalize()
        candidates = self._macro[self._macro.index <= date]
        if candidates.empty:
            return out
        row = candidates.iloc[-1]
        out["vix_ts"] = str(row.get("vix_term_structure", ""))
        out["yield"] = str(row.get("yield_curve_regime", ""))
        return out

    def check_entry(self, ts: pd.Timestamp, tf: str) -> Tuple[bool, float, Dict]:
        """
        Returns (allow_entry, size_multiplier, regime_context).
        If not enabled, always returns (True, 1.0, {}).
        """
        if not self.enabled:
            return True, 1.0, {}

        regime = self._get_regime(ts)
        vix_ts = regime.get("vix_ts", "")
        yield_r = regime.get("yield", "")

        # Hard filter: reject if regime is in unfavorable set
        if Config.BACKTEST.REGIME_HARD_FILTER:
            if vix_ts in Config.BACKTEST.UNFAVORABLE_VIX_TS:
                return False, 0.0, regime
            if yield_r in Config.BACKTEST.UNFAVORABLE_YIELD:
                return False, 0.0, regime

        # Sizing multiplier (from hl_ratio lookup in regime_conditional_analysis)
        size_mult = 1.0
        if Config.BACKTEST.REGIME_SIZING == "continuous":
            # hl_ratio < 1.0 → faster convergence → upsize; >1.0 → downsize
            # Approximate from documented findings:
            hl_ratio_map = {
                ("vix_term_structure", "backwardation"): 0.646,
                ("vix_term_structure", "flat"): 0.691,
                ("vix_term_structure", "deep_contango"): 0.802,
                ("vix_term_structure", "contango"): 2.356,
                ("yield_curve_regime", "flat_inverted"): 0.430,
                ("yield_curve_regime", "normal"): 4.387,
            }
            hl = hl_ratio_map.get(("vix_term_structure", vix_ts),
                  hl_ratio_map.get(("yield_curve_regime", yield_r), 1.0))
            # Invert and clip: ratio=0.5 → 2× size, ratio=4.0 → 0.25× size, capped [0.5, 2.0]
            size_mult = float(np.clip(1.0 / hl, 0.5, 2.0))
        elif Config.BACKTEST.REGIME_SIZING == "binary":
            # Favorable: backwardation, flat_inverted → 1.5× size
            favorable_vix = {"backwardation", "flat"}
            favorable_yield = {"flat_inverted"}
            if vix_ts in favorable_vix or yield_r in favorable_yield:
                size_mult = 1.5
        # "none" → size_mult = 1.0

        return True, size_mult, regime


# ---------------------------------------------------------------------------
# ML conditioner stub
# ---------------------------------------------------------------------------
class MLConditioner:
    """
    Layer 2 ML gate: loads the trained ml.py Stage 1/2 model and returns
    P(converge) for each entry candidate. Disabled by default.
    """

    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self._model = None
        self._features: Optional[List[str]] = None
        self._converge_indices: List[int] = []
        if enabled:
            self._load()

    def _load(self) -> None:
        model_path = "output/ml/model_stage1.pkl"
        if not os.path.exists(model_path):
            log.warning("MLConditioner: no model at %s — ML gate disabled", model_path)
            self.enabled = False
            return
        try:
            import pickle
            with open(model_path, "rb") as f:
                saved = pickle.load(f)
            self._model = saved.get("model")
            self._features = saved.get("feature_names", [])
            _classes = saved.get("classes", [])
            self._converge_indices = [
                i for i, c in enumerate(_classes)
                if c in ("converged", "strong_converge", "weak_converge")
            ]
            log.info("MLConditioner: loaded model, features=%s, converge_classes=%s",
                     self._features, [_classes[i] for i in self._converge_indices])
        except Exception as e:
            log.warning("MLConditioner: model load failed (%s) — ML gate disabled", e)
            self.enabled = False

    def predict_prob(self, features: Dict) -> float:
        """Return P(converge). If disabled or model unavailable, return 1.0 (pass-through)."""
        if not self.enabled or self._model is None:
            return 1.0
        try:
            X = pd.DataFrame([features])[self._features].fillna(0.0)
            probs = self._model.predict_proba(X)[0]
            if self._converge_indices:
                return float(sum(probs[i] for i in self._converge_indices))
            return float(probs[0])
        except Exception:
            return 1.0


# ---------------------------------------------------------------------------
# Per-pair backtest engine (Layer 1)
# ---------------------------------------------------------------------------
class BacktestEngine:
    """
    Runs the event-driven Layer 1 backtest on a single pair's spread series.
    """

    def __init__(
        self,
        cfg: "BacktestConfig",
        regime_cond: RegimeConditioner,
        ml_cond: MLConditioner,
        layer2_enabled: bool = False,
        allow_negative_hedge: bool = False,
        hub_weights: Optional[Dict[str, float]] = None,
        risk_parity_weights: Optional[Dict[str, float]] = None,
        pnl_cap_by_pair: Optional[Dict[str, float]] = None,
        storm_flags: Optional[Dict[str, bool]] = None,
        mm_hedge_map: Optional[Dict[str, float]] = None,
    ):
        self.cfg = cfg
        self.regime_cond = regime_cond
        self.ml_cond = ml_cond
        self.layer2 = layer2_enabled
        self.allow_negative_hedge = allow_negative_hedge
        # hub_weights: {sym_a/sym_b -> 1/max_hub_peers} — pre-computed from pairs.parquet
        self.hub_weights = hub_weights or {}
        # risk_parity_weights: {sym_a/sym_b -> global_mean_std/pair_std} — from IS trades
        self.risk_parity_weights = risk_parity_weights or {}
        # pnl_cap_by_pair: {sym_a/sym_b -> cap_threshold} — gates new entries above cap
        self.pnl_cap_by_pair = pnl_cap_by_pair or {}
        self._pair_pnl: Dict[str, float] = {}  # cumulative net P&L per pair (for cap)
        # STORM experimental variants
        # storm_flags keys: coint_frac_sizing, garch_stop, session_edge,
        #   session_edge_postopen, mm_exec
        # session_edge: skip pre-open bars (9:00–9:29) and late-day (15:00+)
        # session_edge_postopen: skip first 30-min of trading (9:30–9:59) and late-day
        self.storm_flags = storm_flags or {}
        # mm_hedge_map: {sym_a/sym_b -> beta_mm} loaded from hedge_ratio_comparison.parquet
        self.mm_hedge_map = mm_hedge_map or {}

    def run(
        self,
        pair_row: pd.Series,
        spread_df: pd.DataFrame,
        hedge_method: str,
        holdout_only: bool = False,
        oos_end_date: Optional[pd.Timestamp] = None,
    ) -> List[Trade]:
        """
        Run Layer 1 event loop.
        Returns list of completed Trade records.

        Parameters
        ----------
        pair_row : row from pairs.parquet
        spread_df : spread_series_{A}_{B}.parquet
        hedge_method : "ols" | "kalman"
        holdout_only : if True, run only on the last HOLDOUT_PCT of bars
        oos_end_date : survivorship boundary — truncate OOS window at this date.
                       Pairs involving delisted stocks use this to avoid
                       look-ahead bias. None = no truncation.
        """
        sym_a = pair_row["symbol_a"]
        sym_b = pair_row["symbol_b"]
        tf = pair_row["tf_label"]
        _pair_key = f"{sym_a}/{sym_b}"

        # Scalar fallbacks from pairs.parquet (used when point-in-time series absent)
        hedge_scalar_ols = float(pair_row.get("hedge_ratio_ols", np.nan))
        hedge_scalar_kalman = float(pair_row.get("hedge_ratio_kalman_mean",
                                                  hedge_scalar_ols))
        hedge_scalar = hedge_scalar_ols if hedge_method == "ols" else hedge_scalar_kalman
        if not np.isfinite(hedge_scalar) or (hedge_scalar <= 0 and not self.allow_negative_hedge):
            log.debug("SKIP %s/%s@%s: invalid hedge ratio %.3f", sym_a, sym_b, tf, hedge_scalar)
            return []

        hurst = float(pair_row.get("hurst_rs", np.nan))

        # Drop rows with NaN z_rolling or z_rolling == 0 (warm-up period)
        df = spread_df.dropna(subset=["z_rolling", "spread"]).copy()
        df = df[df["z_rolling"] != 0.0]
        if len(df) < 60:
            return []

        # Holdout split (chronological)
        if holdout_only:
            cutoff = int(len(df) * (1 - self.cfg.HOLDOUT_PCT))
            df = df.iloc[cutoff:]
        if len(df) < 30:
            return []

        # Survivorship boundary: truncate OOS window at delist/removal date
        if oos_end_date is not None:
            oos_end_ts = pd.Timestamp(oos_end_date)
            df = df[df.index <= oos_end_ts]
            if len(df) < 30:
                log.debug(
                    "SKIP %s/%s@%s: oos_end_date %s truncates to < 30 bars",
                    sym_a, sym_b, tf, oos_end_date,
                )
                return []

        trades: List[Trade] = []
        in_position = False
        current_trade: Optional[Trade] = None
        mae_val = mfe_val = 0.0

        z_arr = df["z_rolling"].values
        spread_arr = df["spread"].values
        hl_arr = df["half_life_rolling"].values
        timestamps = df.index
        n = len(df)

        # STORM: pre-compute rolling z-score volatility for garch_stop variant
        _garch_stop = self.storm_flags.get("garch_stop", False)
        _rolling_z_std = None
        _hist_z_std = 1.0
        if _garch_stop:
            _hist_z_std = float(np.nanstd(z_arr)) or 1.0
            _rolling_z_std = (pd.Series(z_arr)
                               .rolling(100, min_periods=10)
                               .std()
                               .fillna(_hist_z_std)
                               .values)

        # STORM: MM execution — look up beta_mm for this pair
        _mm_exec = self.storm_flags.get("mm_exec", False)
        _pair_key_full = f"{sym_a}/{sym_b}"
        _beta_mm = self.mm_hedge_map.get(_pair_key_full) if _mm_exec else None

        # STORM: intraday TF detection for session_edge filters
        _session_edge = self.storm_flags.get("session_edge", False)
        _session_edge_postopen = self.storm_flags.get("session_edge_postopen", False)
        _is_intraday = any(c in tf for c in ["m", "h"]) and "D" not in tf and "W" not in tf

        # STORM: coint_frac — read fraction; apply threshold gate or continuous sizing
        _coint_frac = float(pair_row.get("coint_fraction_rolling", 1.0))
        if not np.isfinite(_coint_frac) or _coint_frac <= 0:
            _coint_frac = 1.0
        _coint_frac_threshold = float(self.storm_flags.get("coint_frac_threshold", 0.0))
        if _coint_frac_threshold > 0 and _coint_frac < _coint_frac_threshold:
            log.debug("SKIP %s/%s@%s: coint_frac %.3f < threshold %.3f",
                      sym_a, sym_b, tf, _coint_frac, _coint_frac_threshold)
            return []
        _coint_frac_sizing = self.storm_flags.get("coint_frac_sizing", False)

        # Point-in-time causal hedge ratio series (added to spread_series by
        # analysis.py after the lookahead-bias fix). Falls back to scalar when
        # the column is absent (pre-fix spread_series files).
        _pit_col = "hedge_ratio_ols_t" if hedge_method == "ols" else "hedge_ratio_kalman_t"
        _pit_series = df[_pit_col].values if _pit_col in df.columns else None
        _has_pit = _pit_series is not None and np.any(np.isfinite(_pit_series))

        # Static pair features for ML gate (constant per pair, avoid recomputing in loop)
        _ml_coint_frac = float(pair_row.get("coint_fraction_rolling", np.nan))
        _ml_hl_slope = float(pair_row.get("half_life_trend_slope", np.nan))
        _ml_mean_rev = float(pair_row.get("mean_reversion_speed", np.nan))
        _ml_hedge_drift = np.nan
        if (np.isfinite(hedge_scalar_ols) and hedge_scalar_ols != 0
                and np.isfinite(hedge_scalar_kalman)):
            _ml_hedge_drift = abs(hedge_scalar_ols - hedge_scalar_kalman) / abs(hedge_scalar_ols)

        # Rolling correlation for structural breakdown exit
        _default_flags = pd.Series(0, index=df.index)
        gap_a = df.get("gap_flag_a", _default_flags).fillna(0).astype(int).values
        gap_b = df.get("gap_flag_b", _default_flags).fillna(0).astype(int).values

        for i in range(n):
            z = z_arr[i]
            spread = spread_arr[i]
            hl = hl_arr[i]
            ts = timestamps[i]

            if not np.isfinite(z) or not np.isfinite(spread):
                continue

            # Skip bars with DATA_GAP on either leg
            if int(gap_a[i]) == int(GapFlag.DATA_GAP) or int(gap_b[i]) == int(GapFlag.DATA_GAP):
                if in_position:
                    # Force close at this bar (gap invalidates position)
                    current_trade.exit_time = ts
                    current_trade.exit_z = z
                    current_trade.exit_spread = spread
                    current_trade.exit_reason = "data_gap"
                    self._close_trade(current_trade, mae_val, mfe_val)
                    trades.append(current_trade)
                    in_position = False
                    current_trade = None
                continue

            if not in_position:
                # ---- Entry logic ----
                # STORM: session_edge filter — skip pre-open (9:00–9:29) and late-day
                if _session_edge and _is_intraday:
                    _hr, _mn = getattr(ts, "hour", -1), getattr(ts, "minute", 0)
                    if (_hr == 9 and _mn < 30) or _hr >= 15:
                        continue
                # STORM: session_edge_postopen — skip first 30-min of trading (9:30–9:59) and late-day
                if _session_edge_postopen and _is_intraday:
                    _hr, _mn = getattr(ts, "hour", -1), getattr(ts, "minute", 0)
                    if (_hr == 9 and _mn >= 30) or _hr >= 15:
                        continue

                if abs(z) < self.cfg.ENTRY_ZSCORE:
                    continue
                hl_at_entry = hl if np.isfinite(hl) and hl >= self.cfg.MIN_HALF_LIFE_BARS else np.nan
                if not np.isfinite(hl_at_entry):
                    continue  # can't set max hold without half-life

                # Point-in-time hedge ratio at this bar (causal, no lookahead).
                # Uses the Kalman/OLS trajectory from analysis.py if available;
                # falls back to the scalar from pairs.parquet when the spread_series
                # file predates the lookahead-bias fix (analysis.py re-run required).
                if _has_pit:
                    hedge_pit = float(_pit_series[i])
                    if not np.isfinite(hedge_pit) or (hedge_pit <= 0 and not self.allow_negative_hedge):
                        hedge_pit = hedge_scalar  # warmup bars: scalar fallback
                else:
                    hedge_pit = hedge_scalar

                # Layer 2: regime check
                allow, size_mult, regime_ctx = self.regime_cond.check_entry(ts, tf)
                if not allow:
                    continue

                # Layer 2: ML gate — feature names must match ml.py's _FEATURE_COLS exactly
                ml_features = {
                    "zscore": abs(z),
                    "zscore_velocity": float(z_arr[i] - z_arr[max(0, i - 5)]),
                    "half_life_current": hl_at_entry,
                    "hurst_exponent": hurst,
                    "coint_fraction_rolling": _ml_coint_frac,
                    "half_life_trend_slope": _ml_hl_slope,
                    "mean_reversion_speed": _ml_mean_rev,
                    "hedge_ratio_drift": _ml_hedge_drift,
                }
                ml_prob = self.ml_cond.predict_prob(ml_features)
                if self.layer2 and ml_prob < self.cfg.ML_GO_THRESHOLD:
                    continue

                # P&L cap: gate new entries once pair has hit its IS-calibrated budget
                _cap = self.pnl_cap_by_pair.get(_pair_key)
                if _cap is not None and self._pair_pnl.get(_pair_key, 0.0) >= _cap:
                    continue

                # N_SHARES: hub-count and risk-parity multipliers on top of Layer 2 size_mult
                hub_w = self.hub_weights.get(_pair_key, 1.0)
                rp_w = self.risk_parity_weights.get(_pair_key, 1.0)
                n_shares = max(1, int(self.cfg.N_SHARES_PER_TRADE * size_mult * hub_w * rp_w))

                # STORM: coint_frac_sizing — scale shares by rolling confirmation fraction
                if _coint_frac_sizing:
                    n_shares = max(1, int(n_shares * _coint_frac))

                # STORM: mm_exec — use MM hedge ratio for position sizing if available
                if _mm_exec and _beta_mm is not None and np.isfinite(_beta_mm) and _beta_mm > 0:
                    hedge_pit = _beta_mm

                side = "short" if z > 0 else "long"

                current_trade = Trade(
                    tf=tf, symbol_a=sym_a, symbol_b=sym_b,
                    hedge_method=hedge_method, hedge_ratio=hedge_pit,
                    entry_time=ts, entry_z=z, entry_spread=spread, side=side,
                    n_shares_a=n_shares, n_shares_b=n_shares * abs(hedge_pit),
                    half_life_at_entry=hl_at_entry, hurst_at_entry=hurst,
                    ml_prob=ml_prob,
                    vix_ts_regime=regime_ctx.get("vix_ts", ""),
                    yield_regime=regime_ctx.get("yield", ""),
                    regime_size_multiplier=size_mult,
                )
                in_position = True
                mae_val = mfe_val = 0.0

            else:
                # ---- Position management ----
                pnl_raw_now = (spread - current_trade.entry_spread)
                if current_trade.side == "short":
                    pnl_raw_now = -pnl_raw_now

                mae_val = min(mae_val, pnl_raw_now)
                mfe_val = max(mfe_val, pnl_raw_now)
                current_trade.hold_bars += 1
                max_hold = int(self.cfg.MAX_HOLD_MULTIPLIER * current_trade.half_life_at_entry)

                # Exit conditions (checked in priority order)
                exit_reason = ""

                # STORM: garch_stop — tighten stop when conditional vol > 2× historical
                _effective_stop = self.cfg.STOP_ZSCORE
                if _garch_stop and _rolling_z_std is not None:
                    if _rolling_z_std[i] > 2.0 * _hist_z_std:
                        _effective_stop = min(_effective_stop, 3.0)

                # 1. Stop loss: spread widened further
                if abs(z) >= _effective_stop:
                    exit_reason = "stop"

                # 2. Signal exit: z crossed toward zero past EXIT_ZSCORE
                elif (current_trade.side == "short" and z <= self.cfg.EXIT_ZSCORE) or \
                     (current_trade.side == "long" and z >= -self.cfg.EXIT_ZSCORE):
                    exit_reason = "signal_exit"

                # 3. Max hold
                elif current_trade.hold_bars >= max_hold:
                    exit_reason = "max_hold"

                # 4. Structural breakdown: rolling correlation check
                # (simplified: if z widens past 2.5× entry z, flag as breakdown)
                elif abs(z) > 2.0 * abs(current_trade.entry_z) and current_trade.hold_bars > 5:
                    exit_reason = "corr_exit"

                if exit_reason:
                    current_trade.exit_time = ts
                    current_trade.exit_z = z
                    current_trade.exit_spread = spread
                    current_trade.exit_reason = exit_reason
                    self._close_trade(current_trade, mae_val, mfe_val)
                    trades.append(current_trade)
                    in_position = False
                    current_trade = None

        # Close any open position at end of series
        if in_position and current_trade is not None:
            current_trade.exit_time = timestamps[-1]
            current_trade.exit_z = z_arr[-1]
            current_trade.exit_spread = spread_arr[-1]
            current_trade.exit_reason = "eod"
            self._close_trade(current_trade, mae_val, mfe_val)
            trades.append(current_trade)

        return trades

    def _close_trade(self, trade: Trade, mae: float, mfe: float) -> None:
        """Compute P&L and excursion metrics at close."""
        n = trade.n_shares_a
        direction = 1 if trade.side == "long" else -1
        gross = direction * (trade.exit_spread - trade.entry_spread) * n
        cost = _compute_cost(
            trade.entry_spread, trade.hedge_ratio, n,
            self.cfg.COMMISSION_PER_SHARE, self.cfg.SLIPPAGE_BPS,
        )
        trade.pnl_gross = round(gross, 4)
        trade.pnl_cost = round(cost, 4)
        trade.pnl_net = round(gross - cost, 4)
        trade.mae = round(mae * n, 4)
        trade.mfe = round(mfe * n, 4)
        _key = f"{trade.symbol_a}/{trade.symbol_b}"
        self._pair_pnl[_key] = self._pair_pnl.get(_key, 0.0) + trade.pnl_net


# ---------------------------------------------------------------------------
# Performance metrics
# ---------------------------------------------------------------------------
def compute_metrics(trades: List[Trade], tf: str, sym_a: str, sym_b: str,
                    hedge_method: str) -> Dict:
    if not trades:
        return {}
    pnl = np.array([t.pnl_net for t in trades])
    n = len(trades)
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    win_rate = len(wins) / n if n > 0 else np.nan
    profit_factor = (wins.sum() / abs(losses.sum())) if losses.sum() != 0 else np.inf

    # Sharpe: annualize using TF-specific bars per year
    bars_per_year = {
        "1m": 390 * 252, "2m": 195 * 252, "3m": 130 * 252, "5m": 78 * 252,
        "15m": 26 * 252, "30m": 13 * 252, "1h": 6.5 * 252, "4h": 252,
    }
    bpy = bars_per_year.get(tf, 252)
    sharpe = (pnl.mean() / pnl.std() * np.sqrt(bpy)) if pnl.std() > 0 else np.nan

    # Drawdown
    cum = np.cumsum(pnl)
    running_max = np.maximum.accumulate(cum)
    dd = running_max - cum
    max_dd = float(dd.max()) if len(dd) > 0 else 0.0

    # Calmar
    total_pnl = float(pnl.sum())
    calmar = total_pnl / max_dd if max_dd > 0 else np.nan

    # MAE / MFE
    mae_arr = np.array([t.mae for t in trades if np.isfinite(t.mae)])
    mfe_arr = np.array([t.mfe for t in trades if np.isfinite(t.mfe)])
    avg_mae = float(mae_arr.mean()) if len(mae_arr) > 0 else np.nan
    avg_mfe = float(mfe_arr.mean()) if len(mfe_arr) > 0 else np.nan
    bliss = abs(avg_mfe / avg_mae) if avg_mae and avg_mae != 0 else np.nan

    # Hold period
    holds = [t.hold_bars for t in trades]
    avg_hold = float(np.mean(holds)) if holds else np.nan

    # Exit reason distribution
    exit_counts = {}
    for t in trades:
        exit_counts[t.exit_reason] = exit_counts.get(t.exit_reason, 0) + 1

    return {
        "tf": tf, "symbol_a": sym_a, "symbol_b": sym_b, "hedge_method": hedge_method,
        "n_trades": n, "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4) if np.isfinite(profit_factor) else profit_factor,
        "sharpe": round(sharpe, 4) if np.isfinite(sharpe) else np.nan,
        "calmar": round(calmar, 4) if np.isfinite(calmar) else np.nan,
        "total_pnl": round(total_pnl, 2),
        "max_drawdown": round(max_dd, 2),
        "avg_hold_bars": round(avg_hold, 1),
        "avg_mae": round(avg_mae, 4) if np.isfinite(avg_mae) else np.nan,
        "avg_mfe": round(avg_mfe, 4) if np.isfinite(avg_mfe) else np.nan,
        "bliss": round(bliss, 4) if np.isfinite(bliss) else np.nan,
        **{f"exit_{k}": v for k, v in exit_counts.items()},
    }


# ---------------------------------------------------------------------------
# Portfolio-level aggregation
# ---------------------------------------------------------------------------
def aggregate_portfolio(
    all_trades: List[Trade],
    all_metrics: List[Dict],
) -> Dict:
    """Compute portfolio-level Sharpe, drawdown, concentration stats."""
    if not all_trades:
        return {}

    # Sort all trades by entry time for portfolio P&L timeline
    sorted_trades = sorted(all_trades, key=lambda t: t.entry_time or pd.Timestamp.min)
    pnl_series = pd.Series(
        [t.pnl_net for t in sorted_trades],
        index=[t.exit_time or t.entry_time for t in sorted_trades],
    )

    # Portfolio-level Sharpe (daily P&L aggregation across all pairs)
    daily_pnl = pnl_series.resample("1D").sum()
    sharpe_port = (daily_pnl.mean() / daily_pnl.std() * np.sqrt(252)
                   if daily_pnl.std() > 0 else np.nan)

    # Portfolio drawdown
    cum = daily_pnl.cumsum()
    max_dd_port = float((cum.cummax() - cum).max()) if len(cum) > 0 else 0.0

    # Concentration: pairs by total P&L contribution
    pair_pnl = {}
    for t in sorted_trades:
        key = f"{t.symbol_a}/{t.symbol_b}@{t.tf}"
        pair_pnl[key] = pair_pnl.get(key, 0.0) + t.pnl_net
    total = sum(pair_pnl.values())
    concentration = {k: round(v / total, 4) if total != 0 else 0.0
                     for k, v in pair_pnl.items()}
    max_conc_pair = max(concentration, key=lambda k: abs(concentration[k])) if concentration else ""
    max_conc_pct = abs(concentration.get(max_conc_pair, 0.0))

    return {
        "n_pairs": len(set(f"{t.symbol_a}/{t.symbol_b}" for t in sorted_trades)),
        "n_trades_total": len(sorted_trades),
        "total_pnl_portfolio": round(total, 2),
        "sharpe_portfolio": round(sharpe_port, 4) if np.isfinite(sharpe_port) else np.nan,
        "max_drawdown_portfolio": round(max_dd_port, 2),
        "max_concentration_pair": max_conc_pair,
        "max_concentration_pct": round(max_conc_pct, 4),
    }


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------
_OUT_DIR = "output/backtest"


def _save_results(
    all_trades: List[Trade],
    all_metrics: List[Dict],
    portfolio_stats: Dict,
    label: str = "layer1",
) -> None:
    os.makedirs(_OUT_DIR, exist_ok=True)
    if all_trades:
        trade_rows = [asdict(t) for t in all_trades]
        pd.DataFrame(trade_rows).to_parquet(
            os.path.join(_OUT_DIR, f"trades_{label}.parquet"), index=False
        )
    if all_metrics:
        pd.DataFrame(all_metrics).to_parquet(
            os.path.join(_OUT_DIR, f"summary_{label}.parquet"), index=False
        )
    if portfolio_stats:
        pd.DataFrame([portfolio_stats]).to_parquet(
            os.path.join(_OUT_DIR, f"portfolio_{label}.parquet"), index=False
        )


# ---------------------------------------------------------------------------
# Console reporting
# ---------------------------------------------------------------------------
def _print_summary(all_metrics: List[Dict], portfolio_stats: Dict, label: str) -> None:
    if not all_metrics:
        print(f"\n[{label}] No results produced.")
        return
    df = pd.DataFrame(all_metrics)

    print(f"\n{'='*70}")
    print(f"  BACKTEST SUMMARY — {label.upper()}")
    print(f"{'='*70}")
    print(f"  Pairs tested: {len(df)}")
    print(f"  Total trades: {df['n_trades'].sum()}")
    print(f"  Total net P&L (spread units): {df['total_pnl'].sum():.2f}")

    by_tf = df.groupby("tf")[["n_trades", "win_rate", "sharpe", "total_pnl"]].mean()
    print(f"\n  By timeframe (mean):")
    print(by_tf.to_string())

    by_hedge = df.groupby("hedge_method")[["n_trades", "win_rate", "sharpe", "total_pnl"]].mean()
    print(f"\n  OLS vs Kalman:")
    print(by_hedge.to_string())

    print(f"\n  Top 10 pairs by net P&L:")
    top = df.nlargest(10, "total_pnl")[
        ["tf", "symbol_a", "symbol_b", "hedge_method", "n_trades", "win_rate", "sharpe", "total_pnl"]
    ]
    print(top.to_string(index=False))

    print(f"\n  Bottom 5 pairs by net P&L:")
    bot = df.nsmallest(5, "total_pnl")[
        ["tf", "symbol_a", "symbol_b", "hedge_method", "n_trades", "total_pnl"]
    ]
    print(bot.to_string(index=False))

    if portfolio_stats:
        print(f"\n  Portfolio-level stats:")
        for k, v in portfolio_stats.items():
            print(f"    {k}: {v}")

    print(f"\n  Bias notes (episodic survivorship + hedge lookahead — see docstring):")
    print("    Full-series run = IN-SAMPLE. Layer 2 holdout run = OOS.")
    print(f"{'='*70}\n")


# ---------------------------------------------------------------------------
# STORM helper: MM hedge map loader
# ---------------------------------------------------------------------------
def load_mm_hedge_map() -> Dict[str, float]:
    """Load MM hedge ratios from stats.py output for STORM mm_exec variant."""
    p = os.path.join("output", "stats", "hedge_ratio_comparison.parquet")
    if not os.path.exists(p):
        log.warning("MM hedge map: %s not found — mm_exec disabled", p)
        return {}
    df = pd.read_parquet(p)
    result: Dict[str, float] = {}
    for _, row in df.iterrows():
        key = f"{row['symbol_a']}/{row['symbol_b']}"
        beta_mm = float(row.get("beta_mm", np.nan))
        if np.isfinite(beta_mm) and beta_mm > 0:
            result[key] = beta_mm
    log.info("MM hedge map: %d pairs loaded", len(result))
    return result


# ---------------------------------------------------------------------------
# Concentration-risk helpers
# ---------------------------------------------------------------------------
def compute_hub_weights(tf_dirs: List[Tuple[str, str]], tf_filter: Optional[str]) -> Dict[str, float]:
    """
    Inverse hub-count N_SHARES multipliers: 1 / max(peers_A, peers_B).

    DD appears in 8 confirmed 1h pairs → each DD pair gets weight 1/8 ≈ 0.125.
    A standalone pair (CMS/DUK) gets weight 1.0.
    Computed at load time from pairs.parquet — no cross-pair runtime state needed.
    """
    from collections import Counter
    symbol_counts: Counter = Counter()
    pair_keys = []
    for tf_dir, tf_label in tf_dirs:
        if tf_filter and tf_label != tf_filter:
            continue
        ppath = f"output/results/{tf_dir}/pairs.parquet"
        if not os.path.exists(ppath):
            continue
        pairs = pd.read_parquet(ppath)
        for _, row in pairs.iterrows():
            sym_a, sym_b = row["symbol_a"], row["symbol_b"]
            symbol_counts[sym_a] += 1
            symbol_counts[sym_b] += 1
            pair_keys.append((sym_a, sym_b))

    weights: Dict[str, float] = {}
    for sym_a, sym_b in pair_keys:
        hub_count = max(symbol_counts[sym_a], symbol_counts[sym_b])
        weights[f"{sym_a}/{sym_b}"] = 1.0 / hub_count if hub_count > 0 else 1.0

    if weights:
        vals = list(weights.values())
        log.info("Hub weights: %d pairs, range [%.3f, %.3f], mean=%.3f",
                 len(weights), min(vals), max(vals), sum(vals) / len(vals))
    return weights


def compute_risk_parity_weights(
    is_trades_path: str = "output/backtest/trades_layer1.parquet",
) -> Dict[str, float]:
    """
    Inverse-volatility N_SHARES multipliers from IS trade P&L std.

    multiplier = global_mean_std / pair_pnl_std, clipped to [0.1, 5.0].
    High-variance pairs (DD/JHG) get fewer shares; quiet pairs get more.
    Grouped by (symbol_a, symbol_b) — TF and hedge_method averaged out.
    """
    if not os.path.exists(is_trades_path):
        log.warning("Risk parity: IS trades not found at %s — flat sizing", is_trades_path)
        return {}
    trades = pd.read_parquet(is_trades_path)
    grp = trades.groupby(["symbol_a", "symbol_b"])["pnl_net"].std()
    valid = grp[grp > 0].dropna()
    if valid.empty:
        log.warning("Risk parity: no pairs with positive P&L std — flat sizing")
        return {}
    global_mean_std = float(valid.mean())
    weights: Dict[str, float] = {}
    for (sym_a, sym_b), std in valid.items():
        weights[f"{sym_a}/{sym_b}"] = float(np.clip(global_mean_std / std, 0.1, 5.0))
    vals = list(weights.values())
    log.info("Risk parity: %d pairs, range [%.3f, %.3f], mean=%.3f (global_mean_std=%.4f)",
             len(weights), min(vals), max(vals), sum(vals) / len(vals), global_mean_std)
    return weights


def compute_pnl_cap_thresholds(
    is_trades_path: str = "output/backtest/trades_layer1.parquet",
) -> Dict[str, float]:
    """
    Per-pair P&L caps from IS total pair P&L.

    Cap = IS mean pair P&L across all profitable pairs. Once a pair's cumulative
    OOS P&L hits this level, no new entries are taken. Prevents DD/JHG-style
    34.8% OOS concentration from a single pair running unconstrained.
    """
    if not os.path.exists(is_trades_path):
        log.warning("P&L cap: IS trades not found at %s — cap disabled", is_trades_path)
        return {}
    trades = pd.read_parquet(is_trades_path)
    pair_totals = trades.groupby(["symbol_a", "symbol_b"])["pnl_net"].sum()
    profitable = pair_totals[pair_totals > 0]
    if profitable.empty:
        log.warning("P&L cap: no profitable IS pairs — cap disabled")
        return {}
    cap_threshold = float(profitable.mean())
    thresholds = {f"{a}/{b}": cap_threshold for (a, b) in pair_totals.index}
    log.info("P&L cap: IS mean profitable-pair P&L = %.2f → cap on %d pairs",
             cap_threshold, len(thresholds))
    return thresholds


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser(description="CAMARF backtest.py — Layer 1 event-driven baseline")
    p.add_argument("--tf", default=None,
                   help="Run only this TF label (e.g. 1h). Default: all.")
    p.add_argument("--hedge", choices=["ols", "kalman", "both"], default="both",
                   help="Hedge ratio method. Default: both (runs OLS + Kalman separately).")
    p.add_argument("--holdout", action="store_true",
                   help="Run on hold-out slice only (last 20%% of each pair).")
    p.add_argument("--layer2", action="store_true",
                   help="Enable Layer 2 (ML + regime gate). Requires trained model.")
    p.add_argument("--neg-hedge", action="store_true",
                   help="Option B: allow negative hedge ratios (e.g. ARLO pairs). "
                        "Default (Option A): skip hedge<=0 pairs.")
    p.add_argument("--hub-weight", action="store_true",
                   help="Inverse hub-count N_SHARES weighting. DD in 8 pairs → 1/8 sizing.")
    p.add_argument("--risk-parity", action="store_true",
                   help="Inverse-volatility N_SHARES scaling from IS P&L std. "
                        "Requires trades_layer1.parquet (IS run first).")
    p.add_argument("--pnl-cap", action="store_true",
                   help="Cap each pair's cumulative P&L at IS mean pair P&L. "
                        "Requires trades_layer1.parquet (IS run first).")
    # STORM experimental variants
    p.add_argument("--storm-coint-frac", action="store_true",
                   help="STORM: scale N_SHARES by coint_fraction_rolling (0–1 continuous sizing).")
    p.add_argument("--storm-garch-stop", action="store_true",
                   help="STORM: tighten stop to |z|>3.0 when rolling z-vol > 2× historical.")
    p.add_argument("--storm-session-edge", action="store_true",
                   help="STORM: skip pre-open entries (9:00-9:29 ET) and late-day (15:00+) (intraday only).")
    p.add_argument("--storm-session-edge-postopen", action="store_true",
                   help="STORM: skip first 30-min of trading (9:30-9:59 ET) and late-day (15:00+) (intraday only).")
    p.add_argument("--storm-mm-exec", action="store_true",
                   help="STORM: use MM (outlier-robust) hedge ratio for execution sizing.")
    p.add_argument("--storm-all", action="store_true",
                   help="STORM: enable all 4 experimental variants simultaneously.")
    p.add_argument("--entry-z", type=float, default=None,
                   help="Override ENTRY_ZSCORE (default: Config.BACKTEST.ENTRY_ZSCORE=2.0). "
                        "Use --entry-z 1.5 for DD/GPN and DD/JCI zero-trade diagnostic.")
    args = p.parse_args()

    layer2 = args.layer2 or Config.BACKTEST.LAYER2_ENABLED
    regime_cond = RegimeConditioner(enabled=layer2)
    ml_cond = MLConditioner(enabled=layer2)

    hub_weights = compute_hub_weights(_TF_DIRS, args.tf) if args.hub_weight else {}
    risk_parity_weights = compute_risk_parity_weights() if args.risk_parity else {}
    pnl_cap_by_pair = compute_pnl_cap_thresholds() if args.pnl_cap else {}

    # STORM flags
    _storm_all = getattr(args, "storm_all", False)
    storm_flags = {
        "coint_frac_sizing":       getattr(args, "storm_coint_frac", False) or _storm_all,
        "garch_stop":              getattr(args, "storm_garch_stop", False) or _storm_all,
        "session_edge":            getattr(args, "storm_session_edge", False) or _storm_all,
        "session_edge_postopen":   getattr(args, "storm_session_edge_postopen", False),
        "mm_exec":                 getattr(args, "storm_mm_exec", False) or _storm_all,
    }
    mm_hedge_map = load_mm_hedge_map() if storm_flags.get("mm_exec") else {}

    # --entry-z override for z=1.5 comparison arm (DD/GPN, DD/JCI zero-trade diagnostic)
    _backtest_cfg = Config.BACKTEST
    if args.entry_z is not None:
        import copy
        _backtest_cfg = copy.copy(Config.BACKTEST)
        _backtest_cfg.ENTRY_ZSCORE = args.entry_z
        log.info("entry-z override: ENTRY_ZSCORE = %.2f", args.entry_z)

    engine = BacktestEngine(
        cfg=_backtest_cfg, regime_cond=regime_cond, ml_cond=ml_cond,
        layer2_enabled=layer2,
        allow_negative_hedge=args.neg_hedge,
        hub_weights=hub_weights,
        risk_parity_weights=risk_parity_weights,
        pnl_cap_by_pair=pnl_cap_by_pair,
        storm_flags=storm_flags,
        mm_hedge_map=mm_hedge_map,
    )

    hedge_methods = (["ols", "kalman"] if args.hedge == "both"
                     else [args.hedge])
    label = "layer2" if layer2 else "layer1"
    if args.holdout:
        label += "_holdout"
    if args.neg_hedge:
        label += "_neghedge"
    if args.hub_weight:
        label += "_hubw"
    if args.risk_parity:
        label += "_riskparity"
    if args.pnl_cap:
        label += "_pnlcap"
    if args.entry_z is not None:
        label += f"_ez{str(args.entry_z).replace('.', '')}"
    if _storm_all:
        label += "_stormall"
    elif any(storm_flags.values()):
        sfx = "_storm"
        if storm_flags.get("coint_frac_sizing"):     sfx += "_cfrac"
        if storm_flags.get("garch_stop"):            sfx += "_gstop"
        if storm_flags.get("session_edge"):          sfx += "_sedge"
        if storm_flags.get("session_edge_postopen"): sfx += "_sedge_post"
        if storm_flags.get("mm_exec"):               sfx += "_mmexec"
        label += sfx

    # Load survivorship exclusions for OOS-end-date truncation
    _surv_path = os.path.join(os.path.dirname(__file__), "output", "cache", "survivorship_exclusions.csv")
    _survivorship: pd.DataFrame = pd.DataFrame()
    if os.path.exists(_surv_path):
        try:
            from survivorship import load_exclusions as _load_surv, get_oos_end_date as _get_oos_end
            _survivorship = _load_surv(_surv_path)
            log.info("Survivorship exclusions loaded: %d delist events", len(_survivorship))
        except Exception as _e:
            log.warning("Could not load survivorship exclusions: %s", _e)

    # Run over confirmed pairs
    all_trades: List[Trade] = []
    all_metrics: List[Dict] = []

    for tf_dir, tf_label in _TF_DIRS:
        if args.tf and tf_label != args.tf:
            continue
        pairs_path = f"output/results/{tf_dir}/pairs.parquet"
        if not os.path.exists(pairs_path):
            continue
        pairs = pd.read_parquet(pairs_path)
        # Ensure tf_label column exists
        if "tf_label" not in pairs.columns:
            pairs["tf_label"] = tf_label
        log.info("[%s] %d confirmed pairs", tf_label, len(pairs))

        for _, row in pairs.iterrows():
            sym_a, sym_b = row["symbol_a"], row["symbol_b"]
            spread_df = _load_spread(tf_dir, sym_a, sym_b)
            if spread_df is None:
                log.debug("SKIP %s/%s@%s: no spread series", sym_a, sym_b, tf_label)
                continue

            # Survivorship boundary: use earliest delist date of either symbol
            _oos_end = None
            if len(_survivorship) > 0:
                from survivorship import get_oos_end_date as _get_oos_end
                d_a = _get_oos_end(sym_a, _survivorship)
                d_b = _get_oos_end(sym_b, _survivorship)
                if d_a is not None or d_b is not None:
                    candidates = [d for d in [d_a, d_b] if d is not None]
                    _oos_end = min(candidates)

            for hm in hedge_methods:
                trades = engine.run(row, spread_df, hm, holdout_only=args.holdout,
                                    oos_end_date=_oos_end)
                if not trades:
                    continue
                all_trades.extend(trades)
                metrics = compute_metrics(trades, tf_label, sym_a, sym_b, hm)
                if metrics:
                    all_metrics.append(metrics)
                    n_trades = metrics["n_trades"]
                    wr = metrics["win_rate"]
                    sr = metrics["sharpe"]
                    pnl = metrics["total_pnl"]
                    log.info("  %s/%s@%s[%s] %d trades | WR=%.0f%% | SR=%.2f | PnL=%.2f",
                             sym_a, sym_b, tf_label, hm, n_trades, wr * 100,
                             sr if np.isfinite(sr) else float("nan"), pnl)

    portfolio_stats = aggregate_portfolio(all_trades, all_metrics)
    _save_results(all_trades, all_metrics, portfolio_stats, label=label)
    _print_summary(all_metrics, portfolio_stats, label=label)

    # Write run log (same pattern as data.py / analysis.py)
    with open(_LOG_PATH, "w") as f:
        f.write(f"backtest.py run: {label}\n")
        f.write(f"layer2_enabled: {layer2}\n")
        f.write(f"n_pairs_run: {len(set(f'{t.symbol_a}/{t.symbol_b}' for t in all_trades))}\n")
        f.write(f"n_trades_total: {len(all_trades)}\n")
        if all_metrics:
            df = pd.DataFrame(all_metrics)
            f.write(f"total_net_pnl: {df['total_pnl'].sum():.2f}\n")
            f.write(f"mean_sharpe: {df['sharpe'].mean():.4f}\n")
            f.write(f"mean_win_rate: {df['win_rate'].mean():.4f}\n")
        if portfolio_stats:
            f.write(f"portfolio_sharpe: {portfolio_stats.get('sharpe_portfolio', 'n/a')}\n")
            f.write(f"max_concentration_pct: {portfolio_stats.get('max_concentration_pct', 'n/a')}\n")
        f.write(f"outputs: output/backtest/trades_{label}.parquet, "
                f"summary_{label}.parquet, portfolio_{label}.parquet\n")
    log.info("Run summary → %s", _LOG_PATH)


if __name__ == "__main__":
    main()
