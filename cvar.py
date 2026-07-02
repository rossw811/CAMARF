"""
cvar.py — Historical (non-parametric) Conditional Value at Risk / Expected
Shortfall on CAMARF's portfolio-level daily P&L.

Motivation (STORM infrastructure gap analysis, 2026-07-01): no portfolio-
level tail-risk metric existed anywhere in this pipeline. VaR is deliberately
NOT what's implemented here: the STORM survey's own Skeptic-lens research
found VaR badly failed institutions heading into 2008 specifically because
its normal-distribution assumption understates fat-tail/asymmetric risk, and
this project's own trade P&L is already known to be strongly skewed and
fat-tailed (deflated_sharpe.py's IS/OOS skew=2.4-2.9, kurtosis=14.2-14.3 —
far from normal). Reporting a parametric VaR number here would repeat the
exact failure mode the survey flagged. Historical CVaR sidesteps the
normal-distribution assumption entirely: it is just the mean of the worst
(1-alpha) fraction of REALIZED daily P&L observations, not a fitted-
distribution quantile.

Method: reuses the same exit-date daily-P&L grouping convention as
deflated_sharpe.py's _daily_pnl_stats() and stats.py's permutation test
(group closed-trade pnl_net by exit date, sum to one portfolio P&L per day).
CVaR_alpha = mean loss among the worst (1-alpha) fraction of days, where
"loss" = -daily_pnl (so a profitable day contributes a negative "loss").

Output: output/stats/cvar.json
"""
import json
import logging
import os
import sys
import time

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.abspath(__file__))
_BACKTEST_DIR = os.path.join(_ROOT, "output", "backtest")
_STATS_DIR = os.path.join(_ROOT, "output", "stats")

log = logging.getLogger("cvar")

_ALPHAS = (0.95, 0.99)


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(os.path.join(_ROOT, "latest_run_cvar.log"), mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def daily_pnl_series(trades_path: str) -> "pd.Series | None":
    if not os.path.exists(trades_path):
        return None
    trades = pd.read_parquet(trades_path)
    if trades.empty or "pnl_net" not in trades.columns:
        return None
    tr = trades.copy()
    tr["exit_date"] = pd.to_datetime(tr["exit_time"]).dt.date
    daily = tr.groupby("exit_date")["pnl_net"].sum()
    return daily if len(daily) >= 3 else None


def historical_cvar(daily_pnl: np.ndarray, alpha: float) -> dict:
    """
    Historical (empirical) VaR and CVaR at confidence level alpha, in P&L
    dollar units. losses = -daily_pnl, so VaR/CVaR are positive numbers
    representing a dollar loss magnitude (0 or negative means no tail loss
    at that confidence level — e.g. an all-profitable day set).
    """
    losses = -np.asarray(daily_pnl, dtype=float)
    var = float(np.quantile(losses, alpha))
    tail = losses[losses >= var]
    cvar = float(tail.mean()) if len(tail) > 0 else var
    return {
        "alpha": alpha,
        "var": var,
        "cvar": cvar,
        "n_tail_days": int(len(tail)),
        "n_total_days": int(len(losses)),
    }


def main():
    _setup_logging()
    t0 = time.time()
    log.info("=== cvar.py: Historical CVaR / Expected Shortfall (portfolio daily P&L) ===")

    results = {}
    for suffix, description in [
        ("layer1", "in-sample baseline"),
        ("layer1_holdout", "out-of-sample holdout baseline"),
    ]:
        trades_path = os.path.join(_BACKTEST_DIR, f"trades_{suffix}.parquet")
        daily = daily_pnl_series(trades_path)
        if daily is None:
            log.warning("  [%s] no usable trades at %s — skipping", suffix, trades_path)
            continue
        vals = daily.values.astype(float)
        entry = {"description": description, "n_days": len(vals), "mean_daily_pnl": float(np.mean(vals))}
        for alpha in _ALPHAS:
            r = historical_cvar(vals, alpha)
            entry[f"var_{int(alpha*100)}"] = r["var"]
            entry[f"cvar_{int(alpha*100)}"] = r["cvar"]
            entry[f"n_tail_days_{int(alpha*100)}"] = r["n_tail_days"]
            log.info(
                "  [%s] %s: VaR_%.0f%% = $%.2f, CVaR_%.0f%% (mean of worst %d/%d days) = $%.2f",
                suffix, description, alpha * 100, r["var"], alpha * 100,
                r["n_tail_days"], r["n_total_days"], r["cvar"],
            )
        results[suffix] = entry

    if results:
        os.makedirs(_STATS_DIR, exist_ok=True)
        out_path = os.path.join(_STATS_DIR, "cvar.json")
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2)
        log.info("Saved => %s", out_path)
    else:
        log.warning("No results produced — no usable trades_*.parquet found.")

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("cvar.py complete (%.1f min)", runtime)


if __name__ == "__main__":
    main()
