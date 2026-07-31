"""
sensitivity.py — Parameter sensitivity / stability test

Sweeps key backtest parameters over a grid and reports OOS Sharpe for each
combination.  Standard robustness requirement for systematic strategy papers.

Parameters swept:
  entry_z     : entry threshold (z-score of spread)       [1.5, 2.0, 2.5, 3.0]
  exit_z      : exit threshold (z-score toward mean)       [0.0, 0.25, 0.5, 0.75]
  max_hl      : maximum allowed half-life (bars)           [20, 35, 50, 75]
  adv_usd     : ADV liquidity filter threshold ($M)        [0, 10, 25, 50, 100] (×1e6)

Primary output: 2D grid of (entry_z × exit_z) portfolio Sharpe at baseline max_hl
and baseline ADV, plus 1D sensitivity curves for max_hl and ADV.

Run: python sensitivity.py [--entry_z 2.0 --exit_z 0.5 --max_hl 50 --adv 25]
"""

import os
import sys
import json
import logging
import time
import itertools
import warnings
from typing import List, Dict, Any, Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config

_ROOT = os.path.dirname(os.path.abspath(__file__))
_RESULTS_DIR = os.path.join(_ROOT, "output", "results")
_STATS_DIR = os.path.join(_ROOT, "output", "stats")
_OUT_DIR = os.path.join(_ROOT, "output", "sensitivity")

_TF_DIRS = [("1hr", "1h")]

# Sweep grids -- sourced directly from Config.BACKTEST (2026-07-20, Grand
# Sweep task #24), not duplicated as local constants. ENTRY_Z_LEVELS/
# EXIT_Z_LEVELS/STOP_Z_LEVELS previously happened to match
# COARSE_ENTRY_ZSCORE/COARSE_EXIT_ZSCORE/COARSE_STOP_ZSCORE by coincidence,
# not by import -- the exact same silent-drift risk BUG-D71 found in
# wfa.py. MAX_HL_LEVELS/ADV_LEVELS_M had no config.py home before this
# (added as SENSITIVITY_MAX_HL_LEVELS/SENSITIVITY_ADV_LEVELS_M).
ENTRY_Z_LEVELS = Config.BACKTEST.COARSE_ENTRY_ZSCORE
EXIT_Z_LEVELS  = Config.BACKTEST.COARSE_EXIT_ZSCORE
STOP_Z_LEVELS  = Config.BACKTEST.COARSE_STOP_ZSCORE  # NEW sweep dimension -- was
                                                       # in config.py but never
                                                       # actually swept before this
MAX_HL_LEVELS  = Config.BACKTEST.SENSITIVITY_MAX_HL_LEVELS
ADV_LEVELS_M   = Config.BACKTEST.SENSITIVITY_ADV_LEVELS_M   # in millions USD

# Baseline for 1D sweeps (while varying the other axis)
BASELINE_ENTRY_Z = Config.BACKTEST.ENTRY_ZSCORE
BASELINE_EXIT_Z  = 0.5  # deliberately NOT Config.BACKTEST.EXIT_ZSCORE (0.0) --
                         # this baseline predates that field and 0.5 sits at
                         # the grid's midpoint; kept as its own named constant
                         # rather than silently changing the existing baseline
BASELINE_STOP_Z  = Config.BACKTEST.STOP_ZSCORE
BASELINE_MAX_HL  = 50
BASELINE_ADV_M   = 0

log = logging.getLogger("sensitivity")


# =============================================================================
# UTILITIES
# =============================================================================


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(os.path.join(_ROOT, "latest_run_sensitivity.log"), mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def load_pairs_and_spreads(tf_dir: str, tf_label: str):
    """Load confirmed pairs and their spread_series for one TF."""
    pairs_path = os.path.join(_RESULTS_DIR, tf_dir, "pairs.parquet")
    tiers_path = os.path.join(_STATS_DIR, "cointegration_tiers.parquet")
    if not os.path.exists(pairs_path):
        return [], {}

    pairs = pd.read_parquet(pairs_path)
    if "tf_label" not in pairs.columns:
        pairs["tf_label"] = tf_label

    # Merge half_life_rolling from tiers so we can use it for max_hl filter
    if os.path.exists(tiers_path):
        tiers = pd.read_parquet(tiers_path)
        tier_tf = tiers[tiers["tf_label"] == tf_label][
            ["symbol_a", "symbol_b", "tf_label", "half_life_rolling"]
        ]
        if "half_life_rolling" not in pairs.columns:
            pairs = pairs.merge(tier_tf, on=["symbol_a", "symbol_b", "tf_label"], how="left")

    # Load per-pair ADV from 1hr cache (for ADV sweep)
    adv_map: Dict[str, float] = {}
    cache_dir = Config.DATA.CACHE_DIR
    all_syms = set(pairs["symbol_a"].tolist() + pairs["symbol_b"].tolist())
    for sym in all_syms:
        fpath = os.path.join(cache_dir, f"{sym}_1hr.parquet")
        if not os.path.exists(fpath):
            adv_map[sym] = float("nan")
            continue
        try:
            hr = pd.read_parquet(fpath)
            if "close" in hr.columns and "volume" in hr.columns:
                hr.index = pd.to_datetime(hr.index)
                dv = hr["close"] * hr["volume"]
                daily_dv = dv.groupby(hr.index.date).sum()
                adv_map[sym] = float(daily_dv.mean()) if len(daily_dv) > 0 else float("nan")
            else:
                adv_map[sym] = float("nan")
        except Exception:
            adv_map[sym] = float("nan")

    # Load spread_series for each pair
    spreads: Dict[str, pd.DataFrame] = {}
    for _, row in pairs.iterrows():
        a, b = row["symbol_a"], row["symbol_b"]
        sp_path = os.path.join(_RESULTS_DIR, tf_dir, f"spread_series_{a}_{b}.parquet")
        if os.path.exists(sp_path):
            spreads[f"{a}_{b}"] = pd.read_parquet(sp_path)

    return pairs, spreads, adv_map


def _portfolio_sharpe(trades: list) -> float:
    """Daily-bucketed equity-curve Sharpe from BacktestEngine trade list.

    Uses resample("1D") (zero-filling every calendar day between first and last
    exit), matching aggregate_portfolio()'s convention in backtest.py -- NOT
    groupby(exit_date), which silently drops zero-P&L calendar days and
    understates N (BUG-D62, portfolio_sim.py, 2026-07-13). This function had
    the identical bug, found as a byproduct of task #20's risk-management
    comparison-arm work, applying the same fix here.
    """
    if not trades:
        return float("nan")
    exit_times = [t.exit_time for t in trades if t.exit_time is not None]
    if not exit_times:
        return float("nan")
    pnl = [t.pnl_net for t in trades if t.exit_time is not None]
    s = pd.Series(pnl, index=pd.DatetimeIndex(pd.to_datetime(exit_times))).sort_index()
    daily = s.resample("1D").sum()
    if len(daily) < 5 or daily.std() == 0:
        return float("nan")
    return float(daily.mean() / daily.std() * np.sqrt(252))


def run_variant(pairs: pd.DataFrame, spreads: dict, adv_map: dict,
                entry_z: float, exit_z: float, max_hl: int, adv_usd: float,
                stop_z: float = None) -> Dict[str, Any]:
    """Run one parameter combination through BacktestEngine and return metrics.

    max_hl: pre-filter pairs whose half_life_rolling > max_hl (pair-selection filter,
            not a BacktestConfig param since HL ceiling is set at analysis.py time).
    adv_usd: pre-filter pairs where either symbol has ADV < adv_usd.
    entry_z / exit_z / stop_z: patched directly onto BacktestConfig for this call.
        stop_z defaults to Config.BACKTEST.STOP_ZSCORE (baseline, unswept)
        unless explicitly overridden by the stop_z 1D sweep (added 2026-07-20,
        Grand Sweep task #24 -- STOP_ZSCORE existed in config.py's own
        COARSE_STOP_ZSCORE grid but was never actually swept before this).
    """
    from backtest import BacktestEngine, RegimeConditioner, MLConditioner

    # Half-life filter (pair-selection level)
    if max_hl > 0 and "half_life_rolling" in pairs.columns:
        pairs = pairs[pairs["half_life_rolling"].fillna(9999) <= max_hl]

    # ADV filter
    if adv_usd > 0:
        pairs = pairs[
            pairs.apply(
                lambda r: adv_map.get(r.symbol_a, 0) >= adv_usd and
                          adv_map.get(r.symbol_b, 0) >= adv_usd,
                axis=1,
            )
        ]

    if len(pairs) == 0:
        return {"entry_z": entry_z, "exit_z": exit_z,
                "stop_z": stop_z if stop_z is not None else Config.BACKTEST.STOP_ZSCORE,
                "max_hl": max_hl, "adv_m": adv_usd / 1e6, "sharpe": float("nan"),
                "n_trades": 0, "n_pairs": 0}

    # Patch config for this run
    cfg = Config.BACKTEST
    original_entry = cfg.ENTRY_ZSCORE
    original_exit  = cfg.EXIT_ZSCORE
    original_stop  = cfg.STOP_ZSCORE
    used_stop_z    = stop_z if stop_z is not None else original_stop

    cfg.ENTRY_ZSCORE = entry_z
    cfg.EXIT_ZSCORE  = exit_z
    cfg.STOP_ZSCORE  = used_stop_z

    try:
        engine = BacktestEngine(
            cfg=cfg,
            regime_cond=RegimeConditioner(enabled=False),
            ml_cond=MLConditioner(enabled=False),
            storm_flags={},
            mm_hedge_map={},
        )
        all_trades = []
        for _, row in pairs.iterrows():
            key = f"{row['symbol_a']}_{row['symbol_b']}"
            spread_df = spreads.get(key)
            if spread_df is None:
                continue
            trades = engine.run(row, spread_df, hedge_method="ols", holdout_only=True)
            all_trades.extend(trades)
    finally:
        cfg.ENTRY_ZSCORE  = original_entry
        cfg.EXIT_ZSCORE   = original_exit
        cfg.STOP_ZSCORE   = original_stop

    sh = _portfolio_sharpe(all_trades)
    return {
        "entry_z": entry_z, "exit_z": exit_z, "stop_z": used_stop_z,
        "max_hl": max_hl, "adv_m": adv_usd / 1e6, "sharpe": round(sh, 3) if np.isfinite(sh) else float("nan"),
        "n_trades": len(all_trades), "n_pairs": len(pairs),
    }


# =============================================================================
# MAIN
# =============================================================================


def main():
    _setup_logging()
    t0 = time.time()
    log.info("sensitivity.py — parameter stability grid")
    log.info("=" * 60)

    os.makedirs(_OUT_DIR, exist_ok=True)

    # Check BacktestConfig has the needed attributes
    cfg = Config.BACKTEST
    if not hasattr(cfg, "ENTRY_ZSCORE"):
        log.error("BacktestConfig missing ENTRY_ZSCORE — check config.py")
        return
    if not hasattr(cfg, "MAX_HALF_LIFE"):
        log.error("BacktestConfig missing MAX_HALF_LIFE — check config.py")
        return

    all_results = []

    for tf_dir, tf_label in _TF_DIRS:
        log.info("\n--- Timeframe: %s ---", tf_label)
        result_tuple = load_pairs_and_spreads(tf_dir, tf_label)
        if not result_tuple or len(result_tuple) < 3:
            log.warning("  No pairs found for %s", tf_label)
            continue
        pairs, spreads, adv_map = result_tuple
        if len(pairs) == 0:
            log.warning("  No pairs found for %s", tf_label)
            continue
        log.info("  Loaded %d pairs, %d spread files", len(pairs), len(spreads))

        # 2D grid: entry_z × exit_z (at baseline max_hl and ADV)
        log.info("  Running 2D entry_z x exit_z grid (max_hl=%d, ADV=$%.0fM)...",
                 BASELINE_MAX_HL, BASELINE_ADV_M)
        for ez, xz in itertools.product(ENTRY_Z_LEVELS, EXIT_Z_LEVELS):
            r = run_variant(pairs, spreads, adv_map,
                            ez, xz, BASELINE_MAX_HL, BASELINE_ADV_M * 1e6)
            r["sweep"] = "entry_exit_2d"
            r["tf_label"] = tf_label
            all_results.append(r)
            log.info("    entry_z=%.2f exit_z=%.2f  => Sharpe=%.3f  n=%d",
                     ez, xz, r["sharpe"] if np.isfinite(r["sharpe"]) else float("nan"), r["n_trades"])

        # 1D: max_hl sweep (at baseline entry_z, exit_z, ADV)
        log.info("  Running 1D max_hl sweep...")
        for hl in MAX_HL_LEVELS:
            r = run_variant(pairs, spreads, adv_map,
                            BASELINE_ENTRY_Z, BASELINE_EXIT_Z, hl, BASELINE_ADV_M * 1e6)
            r["sweep"] = "max_hl_1d"
            r["tf_label"] = tf_label
            all_results.append(r)
            log.info("    max_hl=%d  => Sharpe=%.3f  n=%d",
                     hl, r["sharpe"] if np.isfinite(r["sharpe"]) else float("nan"), r["n_trades"])

        # 1D: ADV sweep (at baseline entry_z, exit_z, max_hl)
        log.info("  Running 1D ADV sweep...")
        for adv_m in ADV_LEVELS_M:
            r = run_variant(pairs, spreads, adv_map,
                            BASELINE_ENTRY_Z, BASELINE_EXIT_Z, BASELINE_MAX_HL, adv_m * 1e6)
            r["sweep"] = "adv_1d"
            r["tf_label"] = tf_label
            all_results.append(r)
            log.info("    ADV>=$%.0fM  n_pairs=%d  => Sharpe=%.3f  n=%d",
                     adv_m, r["n_pairs"],
                     r["sharpe"] if np.isfinite(r["sharpe"]) else float("nan"), r["n_trades"])

        # 1D: STOP_ZSCORE sweep (at baseline entry_z, exit_z, max_hl, ADV) --
        # NEW 2026-07-20 (Grand Sweep task #24). STOP_ZSCORE has always had a
        # coarse grid in config.py (COARSE_STOP_ZSCORE) but was never actually
        # swept by this script before this -- "test for all the values in
        # config as well" per Ross's direction.
        log.info("  Running 1D stop_z sweep...")
        for sz in STOP_Z_LEVELS:
            r = run_variant(pairs, spreads, adv_map,
                            BASELINE_ENTRY_Z, BASELINE_EXIT_Z, BASELINE_MAX_HL,
                            BASELINE_ADV_M * 1e6, stop_z=sz)
            r["sweep"] = "stop_z_1d"
            r["tf_label"] = tf_label
            all_results.append(r)
            log.info("    stop_z=%.2f  => Sharpe=%.3f  n=%d",
                     sz, r["sharpe"] if np.isfinite(r["sharpe"]) else float("nan"), r["n_trades"])

    if not all_results:
        log.warning("No results generated.")
        return

    res_df = pd.DataFrame(all_results)
    out_path = os.path.join(_OUT_DIR, "sensitivity_grid.parquet")
    res_df.to_parquet(out_path, index=False)
    log.info("Saved => %s (%d rows)", out_path, len(res_df))

    # Print heat map for 2D grid
    log.info("\n=== 2D entry_z x exit_z SHARPE HEAT MAP ===")
    g2d = res_df[res_df["sweep"] == "entry_exit_2d"]
    if len(g2d) > 0:
        pivot = g2d.pivot_table(index="entry_z", columns="exit_z", values="sharpe", aggfunc="mean")
        log.info("\n%s", pivot.to_string())

    log.info("\n=== 1D max_hl sweep ===")
    g1d_hl = res_df[res_df["sweep"] == "max_hl_1d"].sort_values("max_hl")
    if len(g1d_hl) > 0:
        log.info("\n%s", g1d_hl[["max_hl", "sharpe", "n_trades", "n_pairs"]].to_string(index=False))

    log.info("\n=== 1D ADV sweep ===")
    g1d_adv = res_df[res_df["sweep"] == "adv_1d"].sort_values("adv_m")
    if len(g1d_adv) > 0:
        log.info("\n%s", g1d_adv[["adv_m", "sharpe", "n_trades", "n_pairs"]].to_string(index=False))

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("sensitivity.py complete (%.1f min)", runtime)


if __name__ == "__main__":
    main()
