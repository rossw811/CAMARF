"""
research/asset_volatility_profile.py -- per-asset historical-volatility profile (Ross's queued
item: "historical volatility of asset for asset profile... maybe average daily volatility").

Reuses options.py's realized_vol_proxy (single source of truth for this project's rolling-
realized-vol convention, already used for the options-overlay work) rather than reimplementing
annualized vol from scratch. For each symbol, computes:
  - current short-window (21d) and long-window (63d) annualized realized vol
  - average daily (unannualized) absolute log return -- the literal "average daily volatility"
    Ross asked for, distinct from the annualized figures above
  - a vol PERCENTILE: where the symbol's current 21d vol sits within its own trailing 252-day
    history of 21d vol values -- "is this asset unusually volatile right now, relative to its
    own normal range," not just an absolute vol number with no context

Diagnostic/profile-building output, not yet wired into any position-sizing or filtering logic --
that's the separate, not-yet-scoped "confidence-score filter + position allocation" item.

Verified against synthetic ground truth first: debug/_verify_asset_volatility_profile.py.

Usage:
    python research/asset_volatility_profile.py
"""
import logging
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from options import load_price_series, realized_vol_proxy
from pair_source import confirmed_pairs_list

log = logging.getLogger("asset_volatility_profile")

SHORT_WINDOW = 21
LONG_WINDOW = 63
PERCENTILE_LOOKBACK = 252
_OUT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "output", "research", "asset_volatility_profile.parquet")


def _setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")


def compute_volatility_profile(close: pd.Series, short_window: int = SHORT_WINDOW,
                                 long_window: int = LONG_WINDOW,
                                 percentile_lookback: int = PERCENTILE_LOOKBACK) -> dict:
    """Computes one symbol's volatility profile as of the LAST available bar in `close`.
    Returns NaN fields (never a fabricated 0 or a crash) whenever there isn't enough history
    for a given figure -- each field has its own minimum-length requirement, checked
    independently, so a short series still gets whatever fields it legitimately can support."""
    if close is None or len(close) < short_window + 2:
        return {"current_vol_short": np.nan, "current_vol_long": np.nan,
                "avg_daily_abs_return": np.nan, "vol_percentile": np.nan, "n_bars": 0 if close is None else len(close)}

    vol_short = realized_vol_proxy(close, short_window)
    vol_long = realized_vol_proxy(close, long_window)
    log_ret = np.log(close).diff()
    avg_daily_abs_return = float(log_ret.abs().rolling(short_window).mean().iloc[-1]) \
        if log_ret.abs().rolling(short_window).mean().notna().any() else np.nan

    current_vol_short = float(vol_short.iloc[-1]) if pd.notna(vol_short.iloc[-1]) else np.nan
    current_vol_long = float(vol_long.iloc[-1]) if len(vol_long.dropna()) > 0 and pd.notna(vol_long.iloc[-1]) else np.nan

    vol_short_hist = vol_short.dropna()
    if len(vol_short_hist) >= 20 and np.isfinite(current_vol_short):
        hist_window = vol_short_hist.tail(percentile_lookback)
        vol_percentile = float((hist_window < current_vol_short).mean())
    else:
        vol_percentile = np.nan

    return {
        "current_vol_short": current_vol_short, "current_vol_long": current_vol_long,
        "avg_daily_abs_return": avg_daily_abs_return, "vol_percentile": vol_percentile,
        "n_bars": len(close),
    }


def main():
    _setup_logging()
    log.info("=== asset_volatility_profile.py: per-asset historical-volatility profile "
              f"(short={SHORT_WINDOW}d, long={LONG_WINDOW}d, percentile lookback={PERCENTILE_LOOKBACK}d) ===")

    pairs = confirmed_pairs_list()
    symbols = sorted(set(s for pair in pairs for s in pair if s))
    log.info(f"{len(symbols)} unique symbols across {len(pairs)} confirmed pairs.")

    rows = []
    for sym in symbols:
        close = load_price_series(sym)
        profile = compute_volatility_profile(close)
        profile["symbol"] = sym
        rows.append(profile)

    df = pd.DataFrame(rows)[["symbol", "current_vol_short", "current_vol_long",
                              "avg_daily_abs_return", "vol_percentile", "n_bars"]]
    n_valid = int(df["current_vol_short"].notna().sum())
    log.info(f"{n_valid}/{len(df)} symbols have a valid current volatility figure.")
    if n_valid > 0:
        log.info(f"Cross-sectional current_vol_short: mean={df['current_vol_short'].mean():.4f}, "
                  f"median={df['current_vol_short'].median():.4f}, "
                  f"max={df['current_vol_short'].max():.4f} "
                  f"({df.loc[df['current_vol_short'].idxmax(), 'symbol']})")

    os.makedirs(os.path.dirname(_OUT_PATH), exist_ok=True)
    df.to_parquet(_OUT_PATH)
    log.info(f"Saved -> {_OUT_PATH}")
    log.info("asset_volatility_profile.py complete")


if __name__ == "__main__":
    main()
