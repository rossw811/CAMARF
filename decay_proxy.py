"""
decay_proxy.py — per-pair decay z-score, a per-run diagnostic (not
live/streaming — recomputed whenever backtest.py's IS trades are refreshed,
matching CAMARF's current capability; no live-trading infrastructure exists
yet for true real-time monitoring).

Motivation (2026-06-30 design discussion, locked in 2026-07-01): "is my edge
decaying abnormally" cannot detect specific competitors (rival positions are
fundamentally unobservable — confirmed in the STORM literature survey), but
CAMARF CAN check whether a confirmed pair's RECENT trades are underperforming
its own historical variability by an abnormal amount — the same logic Do &
Faff (2010) applied market-wide (comparing eras), applied here within a
single pair's own trade history instead of externally.

Method: for each confirmed pair with enough IS trades, build a rolling series
of historical Sharpe outcomes (sliding WINDOW_SIZE-trade windows, stepped by
STEP trades, across all but the most recent window) — conceptually the same
idea as wfa.py's sequential fold structure (compare performance across
sequential sub-periods), just applied directly to trade-level P&L rather than
re-running the full walk-forward backtest engine. The most recent
WINDOW_SIZE-trade window's Sharpe is then compared against the historical
rolling-window Sharpe distribution via a z-score. A pair whose recent Sharpe
is more than Z_THRESHOLD standard deviations BELOW its own historical
distribution is flagged — not auto-excluded; ordinary noise at CAMARF's
trade-count scale will produce some false flags, so this is a review flag,
not a decision rule.

Output:
  output/stats/decay_proxy.parquet — per-pair z-score + flag
  latest_run_decay_proxy.log
"""
import logging
import os
import sys
import time
from typing import Dict, Optional

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.abspath(__file__))
_BACKTEST_DIR = os.path.join(_ROOT, "output", "backtest")
_STATS_DIR = os.path.join(_ROOT, "output", "stats")

_WINDOW_SIZE = 15   # trades per rolling window
_STEP = 3           # trades to step between rolling windows
_MIN_TRADES = 40    # minimum total trades before attempting this at all
_Z_THRESHOLD = -2.0 # flag recent Sharpe this many std devs below historical

log = logging.getLogger("decay_proxy")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_decay_proxy.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def _window_sharpe(pnls: np.ndarray) -> float:
    std = np.std(pnls, ddof=1)
    if not np.isfinite(std) or std == 0:
        return float("nan")
    return float(np.mean(pnls) / std)


def compute_pair_decay_zscore(
    pnls_chronological: np.ndarray,
    window_size: int = _WINDOW_SIZE,
    step: int = _STEP,
    min_trades: int = _MIN_TRADES,
) -> Optional[Dict]:
    """
    Pure function, kept data-loading-free so debug/_verify_decay_proxy.py can
    call it directly on synthetic P&L sequences. pnls_chronological must
    already be sorted oldest-to-newest. Returns None if there aren't enough
    trades to compute a meaningful historical distribution.
    """
    n = len(pnls_chronological)
    if n < min_trades:
        return None

    recent_window = pnls_chronological[-window_size:]
    recent_sharpe = _window_sharpe(recent_window)

    historical = pnls_chronological[:-window_size]
    historical_sharpes = []
    for start in range(0, len(historical) - window_size + 1, step):
        historical_sharpes.append(_window_sharpe(historical[start:start + window_size]))
    historical_sharpes = np.array([s for s in historical_sharpes if np.isfinite(s)])
    if len(historical_sharpes) < 3:
        return None

    hist_mean = float(np.mean(historical_sharpes))
    hist_std = float(np.std(historical_sharpes, ddof=1))
    if not np.isfinite(hist_std) or hist_std == 0:
        return None

    z_score = (recent_sharpe - hist_mean) / hist_std
    return {
        "n_trades": n,
        "n_historical_windows": len(historical_sharpes),
        "recent_sharpe": recent_sharpe,
        "historical_mean_sharpe": hist_mean,
        "historical_std_sharpe": hist_std,
        "z_score": float(z_score),
        "flagged": bool(z_score < _Z_THRESHOLD),
    }


def main():
    _setup_logging()
    t0 = time.time()
    log.info("=== decay_proxy.py: per-pair decay z-score (per-run diagnostic, not live) ===")

    trades_path = os.path.join(_BACKTEST_DIR, "trades_layer1.parquet")
    if not os.path.exists(trades_path):
        log.warning("No IS trades at %s — run backtest.py first.", trades_path)
        return
    trades = pd.read_parquet(trades_path)
    trades["pair_key"] = trades["symbol_a"] + "/" + trades["symbol_b"]
    trades = trades.sort_values("entry_time")

    rows = []
    for pair_key, group in trades.groupby("pair_key"):
        pnls = group["pnl_net"].values.astype(float)
        result = compute_pair_decay_zscore(pnls)
        if result is None:
            log.info("  %-20s SKIP (insufficient trades: %d < %d)", pair_key, len(pnls), _MIN_TRADES)
            continue
        result["pair_key"] = pair_key
        rows.append(result)
        flag_str = " ** FLAGGED **" if result["flagged"] else ""
        log.info("  %-20s recent_sharpe=%.3f hist_mean=%.3f hist_std=%.3f z=%.2f%s",
                  pair_key, result["recent_sharpe"], result["historical_mean_sharpe"],
                  result["historical_std_sharpe"], result["z_score"], flag_str)

    if not rows:
        log.warning("No pairs had enough trades to compute a decay z-score.")
        return

    result_df = pd.DataFrame(rows)
    n_flagged = int(result_df["flagged"].sum())
    log.info("\n%d/%d evaluated pairs flagged (recent Sharpe < %.1f std devs below their own "
             "historical distribution). Review flag, not an exclusion decision — some false "
             "flags expected from ordinary noise at these trade counts.",
             n_flagged, len(result_df), abs(_Z_THRESHOLD))

    os.makedirs(_STATS_DIR, exist_ok=True)
    out_path = os.path.join(_STATS_DIR, "decay_proxy.parquet")
    result_df.to_parquet(out_path, index=False)
    log.info("Saved -> %s", out_path)

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("decay_proxy.py complete (%.1f min)", runtime)


if __name__ == "__main__":
    main()
