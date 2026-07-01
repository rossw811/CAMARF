"""
absorption_ratio.py — Kritzman, Li, Page & Rigobon (2011), "Principal
Components as a Measure of Systemic Risk," Journal of Portfolio Management.

Motivation (2026-06-30 discussion with Ross): CAMARF already computes
eigenportfolio decomposition with Marchenko-Pastur factor removal
(analysis.py's EigenportfolioDecomposer) for a different purpose — gating
pair confirmation tiers. The Absorption Ratio is a natural, low-cost reuse
of that same eigendecomposition machinery for a different question: what
fraction of the UNIVERSE's total variance is explained by a small, fixed
number of top principal components, tracked as a rolling time series. A
high fraction means the market is "unified" — most of its variance is
explained by very few common factors, so a shock anywhere propagates
broadly. Kritzman et al. find AR spikes precede or accompany major
drawdowns; it's proposed as a systemic-fragility early-warning indicator,
NOT a return predictor, and is not used here to size or filter individual
pairs — see analysis.py's DCC-GARCH peak-correlation concentration-risk
flag (stats.py) for the complementary pair-level version of this same
"are my positions about to move together" question.

Method:
  1. Universe: every unique symbol appearing in any confirmed pair across
     any timeframe (a reasonably-sized, already-relevant universe, not the
     full ~1,600-asset candidate pool).
  2. Daily close prices -> daily log returns, aligned to a common date index.
  3. Rolling window (252 bars, 21-bar step — same convention as analysis.py's
     coint_fraction_rolling): per window, pairwise-complete correlation
     (UniverseFilter._pairwise_corr, reused directly) -> eigendecomposition
     (EigenportfolioDecomposer._eigendecompose, reused directly) ->
     AR = sum(top-K eigenvalues) / sum(all eigenvalues), where K is a FIXED
     fraction of N (Kritzman et al.'s convention: round(N/5), NOT the
     Marchenko-Pastur K used elsewhere in this project for a different
     purpose — these are two different K definitions for two different
     questions, not the same number reused).

Output:
  output/stats/absorption_ratio.parquet — [date, absorption_ratio, n_assets, k_components]
  latest_run_absorption_ratio.log
"""
import glob
import logging
import os
import sys
import time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analysis import EigenportfolioDecomposer, UniverseFilter

_ROOT = os.path.dirname(os.path.abspath(__file__))
_CACHE_DIR = os.path.join(_ROOT, "output", "cache")
_RESULTS_DIR = os.path.join(_ROOT, "output", "results")
_STATS_DIR = os.path.join(_ROOT, "output", "stats")

_WINDOW = 252
_STEP = 21
_MIN_ASSETS = 10  # below this, an N/5 top-K split isn't meaningful

log = logging.getLogger("absorption_ratio")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_absorption_ratio.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def confirmed_universe_symbols() -> List[str]:
    """Every unique symbol appearing in any output/results/*/pairs.parquet."""
    symbols = set()
    for path in glob.glob(os.path.join(_RESULTS_DIR, "*", "pairs.parquet")):
        try:
            df = pd.read_parquet(path, columns=["symbol_a", "symbol_b"])
            symbols.update(df["symbol_a"])
            symbols.update(df["symbol_b"])
        except Exception as e:
            log.debug("Skipping %s: %s", path, e)
    return sorted(symbols)


def _load_daily_log_returns(symbols: List[str]) -> pd.DataFrame:
    """Returns a (dates x symbols) DataFrame of daily log returns, outer-joined
    across symbols (NaN where a symbol has no data that day — pairwise-complete
    correlation downstream handles this natively, no forward-fill)."""
    series: Dict[str, pd.Series] = {}
    for sym in symbols:
        path = os.path.join(_CACHE_DIR, f"{sym}_1day.parquet")
        if not os.path.exists(path):
            continue
        df = pd.read_parquet(path)
        if "close" not in df.columns:
            continue
        close = df["close"].dropna()
        close.index = pd.to_datetime(close.index)
        log_ret = np.log(close).diff().dropna()
        if len(log_ret) > 0:
            series[sym] = log_ret
    if not series:
        return pd.DataFrame()
    return pd.DataFrame(series).sort_index()


def rolling_absorption_ratio(
    returns_df: pd.DataFrame, window: int = _WINDOW, step: int = _STEP
) -> pd.DataFrame:
    """
    Core computation, kept data-loading-free so debug/_verify_absorption_ratio.py
    can call it directly on synthetic returns_df inputs.

    Returns a DataFrame [date, absorption_ratio, n_assets, k_components],
    one row per window end-date.
    """
    n_assets = returns_df.shape[1]
    if n_assets < _MIN_ASSETS:
        log.warning("Only %d assets — below _MIN_ASSETS=%d, skipping", n_assets, _MIN_ASSETS)
        return pd.DataFrame()

    k = max(1, round(n_assets / 5))
    values = returns_df.values.T  # (N, T) to match UniverseFilter._pairwise_corr's convention
    dates = returns_df.index
    T = values.shape[1]

    rows = []
    for end in range(window, T + 1, step):
        start = end - window
        window_vals = values[:, start:end]
        corr = UniverseFilter._pairwise_corr(window_vals)
        eigenvalues, _, _, _ = EigenportfolioDecomposer._eigendecompose(corr, window)
        total = float(np.sum(eigenvalues))
        if total <= 0:
            continue
        ar = float(np.sum(eigenvalues[:k]) / total)
        rows.append({
            "date": dates[end - 1],
            "absorption_ratio": ar,
            "n_assets": n_assets,
            "k_components": k,
        })
    return pd.DataFrame(rows)


def main():
    _setup_logging()
    t0 = time.time()
    log.info("=== absorption_ratio.py: Kritzman-Li-Page-Rigobon (2011) systemic risk measure ===")

    symbols = confirmed_universe_symbols()
    log.info("Universe: %d unique symbols across all confirmed pairs", len(symbols))
    if len(symbols) < _MIN_ASSETS:
        log.warning("Too few symbols (%d) — run analysis.py first. Aborting.", len(symbols))
        return

    returns_df = _load_daily_log_returns(symbols)
    log.info("Loaded daily returns: %d dates x %d symbols", *returns_df.shape)
    if returns_df.empty or returns_df.shape[0] < _WINDOW:
        log.warning("Insufficient daily history (%d days, need >= %d) — aborting.",
                    returns_df.shape[0], _WINDOW)
        return

    ar_df = rolling_absorption_ratio(returns_df)
    if ar_df.empty:
        log.warning("No absorption-ratio windows computed.")
        return

    os.makedirs(_STATS_DIR, exist_ok=True)
    out_path = os.path.join(_STATS_DIR, "absorption_ratio.parquet")
    ar_df.to_parquet(out_path, index=False)
    log.info(
        "Saved %d windows -> %s (mean AR=%.3f, min=%.3f, max=%.3f, k=%d of %d assets)",
        len(ar_df), out_path, ar_df["absorption_ratio"].mean(),
        ar_df["absorption_ratio"].min(), ar_df["absorption_ratio"].max(),
        ar_df["k_components"].iloc[0], ar_df["n_assets"].iloc[0],
    )

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("absorption_ratio.py complete (%.1f min)", runtime)


if __name__ == "__main__":
    main()
