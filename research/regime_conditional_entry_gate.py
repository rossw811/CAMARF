"""
CAMARF regime_conditional_entry_gate.py — research script, NOT part of
the production pipeline.

Right-sized comparison arm for Development.md's "Planned Enhancement:
Rich Regime Classification for Entry/Exit Gating" (Session ~8), per
Ross's explicit scope decision: rule-based bucketing of the original
3-level feature list (leg regime, spread regime, macro regime), testing
conditional vs. unconditional Sharpe — NOT the full original HMM-post-hoc-
labeling/analyzer.py rewrite.

Feature source: reuses `trades_layer1.parquet`'s already-computed
per-trade entry columns (`hurst_at_entry` — spread Hurst, a Level 1/2
mean-reversion-strength proxy; `vix_ts_regime`, `yield_regime` — Level 3
macro regime, already classified by production) directly, exactly as
`pair_characteristics_analyzer.py` does. Adds ONE genuinely new Level 2
feature not already in the trades table — spread velocity at entry
(consolidating vs. widening) — computed via `_regime_features.
spread_velocity` on each pair's `spread_series_*.parquet`, looked up at
each trade's own entry timestamp (not a full-series rolling pass).

Regime combination (per the original spec's own worked example):
  GOOD  = hurst_at_entry < 0.45 (mean-reverting) AND spread NOT widening
          (velocity <= 0) AND macro calm (vix_ts_regime == "calm")
  BAD   = hurst_at_entry > 0.55 (trending) AND spread widening
          (velocity > 0)
  other = everything else (NEUTRAL)

Output:
  output/research/regime_conditional_entry_gate.parquet
  latest_run_regime_conditional_entry_gate.log
"""
import logging
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aligned_pair_loader import TF_DIRS, DIR_TO_LABEL, resolve_tf_results_dir
from _regime_features import spread_velocity

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BACKTEST_DIR = os.path.join(_ROOT, "output", "backtest")
_OUT_DIR = os.path.join(_ROOT, "output", "research")

_HURST_MEAN_REVERTING = 0.45
_HURST_TRENDING = 0.55

log = logging.getLogger("regime_conditional_entry_gate")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_regime_conditional_entry_gate.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def classify_regime(hurst_at_entry: float, spread_vel_at_entry: float, vix_regime: str) -> str:
    """Pure function — rule-based bucketing per the original spec's own
    worked example. Called per-trade; also directly unit-testable."""
    if not np.isfinite(hurst_at_entry) or not np.isfinite(spread_vel_at_entry):
        return "unknown"
    mean_reverting = hurst_at_entry < _HURST_MEAN_REVERTING
    trending = hurst_at_entry > _HURST_TRENDING
    widening = spread_vel_at_entry > 0
    calm = vix_regime == "calm"

    if mean_reverting and not widening and calm:
        return "good"
    if trending and widening:
        return "bad"
    return "neutral"


def _sharpe(pnl: np.ndarray) -> float:
    if len(pnl) < 5 or np.std(pnl) == 0:
        return float("nan")
    return float(np.mean(pnl) / np.std(pnl) * np.sqrt(252))


def _spread_velocity_lookup(sym_a: str, sym_b: str, tf_label: str) -> dict:
    """Build a {entry_time: spread_velocity} lookup for one pair by
    loading its spread_series once and computing velocity across the
    whole series (spread_velocity is a cheap vectorized diff, NOT the
    expensive Hurst computation — a full-series pass here is fine)."""
    tf_dir = {v: k for k, v in DIR_TO_LABEL.items()}.get(tf_label)
    if tf_dir is None:
        return {}
    results_dir, _ = resolve_tf_results_dir(tf_dir)
    path = os.path.join(results_dir, f"spread_series_{sym_a}_{sym_b}.parquet")
    if not os.path.exists(path):
        return {}
    df = pd.read_parquet(path)
    if "spread" not in df.columns:
        return {}
    vel = spread_velocity(df["spread"])
    return vel.to_dict()


def main():
    _setup_logging()
    t0 = time.time()
    log.info("=== regime_conditional_entry_gate.py: rule-based regime bucketing, "
             "conditional vs. unconditional Sharpe ===")

    frames = []
    for fname in ("trades_layer1.parquet", "trades_layer1_holdout.parquet"):
        fpath = os.path.join(_BACKTEST_DIR, fname)
        if os.path.exists(fpath):
            frames.append(pd.read_parquet(fpath))
    if not frames:
        log.warning("No trades_layer1*.parquet found — run backtest.py first.")
        return
    trades = pd.concat(frames, ignore_index=True)
    if "vix_ts_regime" not in trades.columns:
        trades["vix_ts_regime"] = "unknown"
    trades["vix_ts_regime"] = trades["vix_ts_regime"].fillna("unknown")

    vel_cache = {}
    spread_vel_vals = []
    for _, row in trades.iterrows():
        key = (row["symbol_a"], row["symbol_b"], row["tf"])
        if key not in vel_cache:
            vel_cache[key] = _spread_velocity_lookup(row["symbol_a"], row["symbol_b"], row["tf"])
        lookup = vel_cache[key]
        spread_vel_vals.append(lookup.get(row["entry_time"], np.nan))
    trades["spread_velocity_at_entry"] = spread_vel_vals

    trades["regime_bucket"] = [
        classify_regime(h, v, r) for h, v, r in
        zip(trades["hurst_at_entry"], trades["spread_velocity_at_entry"], trades["vix_ts_regime"])
    ]

    log.info("Regime bucket distribution:\n%s", trades["regime_bucket"].value_counts().to_string())

    unconditional_sharpe = _sharpe(trades["pnl_net"].values)
    log.info("\n--- Unconditional (all %d trades) Sharpe: %.3f ---", len(trades), unconditional_sharpe)

    summary_rows = []
    for bucket, grp in trades.groupby("regime_bucket"):
        sh = _sharpe(grp["pnl_net"].values)
        win_rate = float((grp["pnl_net"] > 0).mean())
        summary_rows.append({
            "regime_bucket": bucket, "n_trades": len(grp), "sharpe": sh,
            "win_rate": win_rate, "mean_pnl": float(grp["pnl_net"].mean()),
            "total_pnl": float(grp["pnl_net"].sum()),
        })
        log.info("  %-10s n=%4d  Sharpe=%7s  win_rate=%.2f  mean_pnl=$%.2f  total_pnl=$%.2f",
                  bucket, len(grp), f"{sh:.3f}" if np.isfinite(sh) else "n/a", win_rate,
                  grp["pnl_net"].mean(), grp["pnl_net"].sum())

    summary_df = pd.DataFrame(summary_rows)
    good_row = summary_df[summary_df["regime_bucket"] == "good"]
    bad_row = summary_df[summary_df["regime_bucket"] == "bad"]
    if not good_row.empty and not bad_row.empty:
        good_sh, bad_sh = good_row["sharpe"].iloc[0], bad_row["sharpe"].iloc[0]
        if np.isfinite(good_sh) and np.isfinite(bad_sh):
            log.info("\nGOOD-regime Sharpe (%.3f) vs BAD-regime Sharpe (%.3f) vs unconditional (%.3f): "
                      "spread = %.3f", good_sh, bad_sh, unconditional_sharpe, good_sh - bad_sh)
    log.info("\nHonest scope note: regime bucketing is rule-based (fixed thresholds on hurst_at_entry/"
             "spread_velocity/vix_ts_regime), not the original spec's full HMM-discovered-state design. "
             "'good'/'bad' bucket sizes may be small — read Sharpe comparisons in light of n_trades per "
             "bucket, not as a settled finding at low n.")

    os.makedirs(_OUT_DIR, exist_ok=True)
    trades[["symbol_a", "symbol_b", "tf", "entry_time", "hurst_at_entry", "spread_velocity_at_entry",
            "vix_ts_regime", "regime_bucket", "pnl_net"]].to_parquet(
        os.path.join(_OUT_DIR, "regime_conditional_entry_gate.parquet"), index=False)
    log.info("Saved -> output/research/regime_conditional_entry_gate.parquet")

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("regime_conditional_entry_gate.py complete (%.1f min)", runtime)


if __name__ == "__main__":
    main()
