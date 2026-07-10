"""
research/financial_turbulence_index.py — comparison/diagnostic method, NOT
part of the production pipeline.

Kritzman & Li (2010), "Skulls, Financial Turbulence, and Risk Management,"
Financial Analysts Journal 66(5) — a companion systemic-risk measure to
absorption_ratio.py (Kritzman, Li, Page & Rigobon 2011, same author group,
already in production as a research diagnostic). Absorption Ratio asks "how
much of the universe's variance is explained by a few common factors, right
now" (in-sample, current window); Turbulence asks a genuinely different
question — "how statistically unusual is TODAY's return vector relative to
the RECENT historical distribution" — a Mahalanobis distance:

    d_t = (y_t - mu)' Sigma^-1 (y_t - mu)

where mu/Sigma are estimated from a trailing historical window (NOT
including day t itself — this is an out-of-sample-relative-to-its-own-
estimation-window statistic, unlike Absorption Ratio's fully in-window
eigenvalue computation) and y_t is the actual realized return vector on day
t. High d_t = today's joint pattern of returns is unusual relative to
recent history (not just any one asset moving a lot, but the CORRELATION
STRUCTURE of the move being atypical) — a genuinely different signal from a
simple volatility spike.

Sigma^-1 uses Ledoit-Wolf shrinkage (sklearn.covariance.ledoit_wolf, the
same estimator this project's own HRP comparison already uses) rather than
the raw sample covariance inverse — with N assets potentially comparable to
or exceeding the window length, a raw sample covariance is often singular or
near-singular, making its literal inverse numerically unstable; shrinkage is
the standard, well-established fix (and this project already trusts it
elsewhere, not a new dependency).

Reuses absorption_ratio.py's universe-construction and daily-log-return
loading directly (confirmed_universe_symbols, _load_daily_log_returns) —
same universe (every symbol in any confirmed pair), same daily-close data
source, no duplicated logic.

Read-only. Never fetches, never modifies absorption_ratio.py's own output.

Usage:
    python research/financial_turbulence_index.py
"""
import logging
import os
import sys
import time

import numpy as np
import pandas as pd
from sklearn.covariance import ledoit_wolf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from absorption_ratio import confirmed_universe_symbols, _load_daily_log_returns

_STATS_DIR = os.path.join("output", "stats")
_WINDOW = 252
_MIN_ASSETS = 10

log = logging.getLogger("financial_turbulence_index")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler("latest_run_financial_turbulence_index.log", mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def rolling_turbulence(returns_df: pd.DataFrame, window: int = _WINDOW) -> pd.DataFrame:
    """
    For each day t (t >= window), estimate mu/Sigma from the trailing
    `window` days STRICTLY BEFORE t (no lookahead — day t itself is never
    part of its own estimation window), then compute day t's Mahalanobis
    turbulence against that estimate. Kept data-loading-free so a debug/
    verify script can call it directly on synthetic returns_df inputs.
    """
    n_assets = returns_df.shape[1]
    if n_assets < _MIN_ASSETS:
        log.warning("Only %d assets — below _MIN_ASSETS=%d, skipping", n_assets, _MIN_ASSETS)
        return pd.DataFrame()

    # Column-wise fill: turbulence needs a complete matrix per window (unlike
    # absorption_ratio's pairwise-complete correlation) — 0-fill missing
    # returns (a no-move day for that asset), documented, not silently dropped.
    values = returns_df.fillna(0.0).to_numpy()
    dates = returns_df.index
    T = values.shape[0]

    rows = []
    for t in range(window, T):
        hist = values[t - window:t]
        y_t = values[t]
        mu = hist.mean(axis=0)
        cov, shrinkage = ledoit_wolf(hist)
        try:
            cov_inv = np.linalg.pinv(cov)
        except np.linalg.LinAlgError:
            continue
        diff = y_t - mu
        d_t = float(diff @ cov_inv @ diff)
        rows.append({
            "date": dates[t], "turbulence": d_t, "shrinkage": float(shrinkage),
            "n_assets": n_assets,
        })
    return pd.DataFrame(rows)


def main():
    _setup_logging()
    t0 = time.time()
    log.info("=== financial_turbulence_index.py: Kritzman & Li (2010) turbulence measure ===")

    symbols = confirmed_universe_symbols()
    log.info("Universe: %d unique symbols across all confirmed pairs", len(symbols))
    if len(symbols) < _MIN_ASSETS:
        log.warning("Too few symbols (%d) — run analysis.py first. Aborting.", len(symbols))
        return

    returns_df = _load_daily_log_returns(symbols)
    log.info("Loaded daily returns: %d dates x %d symbols", *returns_df.shape)
    if returns_df.empty or returns_df.shape[0] < _WINDOW + 30:
        log.warning("Insufficient daily history (%d days, need >= %d) — aborting.",
                    returns_df.shape[0], _WINDOW + 30)
        return

    turb_df = rolling_turbulence(returns_df)
    if turb_df.empty:
        log.warning("No turbulence windows computed.")
        return

    # Turbulent-day flag: top decile, the convention Kritzman & Li use to
    # define a "turbulent regime" for downstream risk-scaling decisions.
    threshold_90 = turb_df["turbulence"].quantile(0.90)
    n_turbulent = int((turb_df["turbulence"] >= threshold_90).sum())

    os.makedirs(_STATS_DIR, exist_ok=True)
    out_path = os.path.join(_STATS_DIR, "financial_turbulence_index.parquet")
    turb_df.to_parquet(out_path, index=False)
    log.info(
        "Saved %d days -> %s (mean=%.2f, median=%.2f, 90th pct threshold=%.2f, "
        "%d/%d days >= 90th pct 'turbulent')",
        len(turb_df), out_path, turb_df["turbulence"].mean(), turb_df["turbulence"].median(),
        threshold_90, n_turbulent, len(turb_df),
    )

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("financial_turbulence_index.py complete (%.1f min)", runtime)


if __name__ == "__main__":
    main()
