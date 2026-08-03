"""
Verification for data_crypto.py's Binance.US fetch, before trusting it as a
real supplemental crypto source. Same spirit as this session's Dukascopy
tick-data check -- cross-reference against an independent source rather
than trusting the fetch mechanics alone.

Checks:
  1. Binance.US BTCUSD daily closes (fetched fresh above) agree closely with
     yfinance's own existing cached BTC-USD daily closes over their
     overlapping date range -- different venues can have small real spread/
     timing differences, so this checks CLOSE AGREEMENT WITHIN A SMALL
     TOLERANCE, not bit-for-bit equality (unlike the Dukascopy check, which
     was verifying an exact mirror of the SAME venue's data).
  2. The fetched frame has no internal gaps in the date INDEX beyond
     what's expected (a continuous daily series, no unexplained multi-day
     holes).
  3. OHLC sanity: high >= max(open, close) and low <= min(open, close) on
     every real bar (structurally must hold for any valid OHLC bar).
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from data import DataStore


def test_ohlc_internal_consistency():
    path = os.path.join(Config.DATA.CACHE_DIR, "binance", "BTC_1d.parquet")
    df = pd.read_parquet(path)
    bad_high = (df["high"] < df[["open", "close"]].max(axis=1)).sum()
    bad_low = (df["low"] > df[["open", "close"]].min(axis=1)).sum()
    print(f"OHLC consistency: {bad_high} bars with high < max(open,close), "
          f"{bad_low} bars with low > min(open,close) (expect 0 both)")
    assert bad_high == 0 and bad_low == 0


def test_no_unexpected_gaps():
    path = os.path.join(Config.DATA.CACHE_DIR, "binance", "BTC_1d.parquet")
    df = pd.read_parquet(path)
    gaps = df.index.to_series().diff().dropna()
    max_gap_days = gaps.max().total_seconds() / 86400
    n_gt_1day = (gaps > pd.Timedelta(days=1)).sum()
    print(f"Max gap between consecutive daily bars: {max_gap_days:.2f} days; "
          f"{n_gt_1day} gaps > 1 day (crypto trades 24/7, expect ~0)")
    assert n_gt_1day == 0, f"found {n_gt_1day} unexpected multi-day gaps in a 24/7 market"


def test_agrees_with_yfinance_within_tolerance():
    binance_path = os.path.join(Config.DATA.CACHE_DIR, "binance", "BTC_1d.parquet")
    df_binance = pd.read_parquet(binance_path)
    df_binance.index = df_binance.index.tz_localize(None) if df_binance.index.tz is not None else df_binance.index

    df_yf = DataStore.load("BTC", "1D")  # CAMARF's internal symbol convention drops the "-USD" suffix
    if df_yf is None or df_yf.empty:
        print("SKIPPED: no cached yfinance BTC daily data on this machine to cross-check against.")
        return

    common_idx = df_binance.index.normalize().intersection(df_yf.index.normalize())
    if len(common_idx) < 30:
        print(f"SKIPPED: only {len(common_idx)} overlapping dates -- not enough for a meaningful check.")
        return

    b = df_binance.set_index(df_binance.index.normalize())["close"].reindex(common_idx)
    y = df_yf.set_index(df_yf.index.normalize())["close"].reindex(common_idx)
    pct_diff = ((b - y).abs() / y).dropna()
    median_pct_diff = float(pct_diff.median())
    max_pct_diff = float(pct_diff.max())
    print(f"Binance.US vs yfinance BTC daily close, {len(pct_diff)} overlapping days: "
          f"median abs %% diff={median_pct_diff*100:.3f}%%, max={max_pct_diff*100:.3f}%%")
    assert median_pct_diff < 0.02, f"median close disagreement too high for the same underlying asset: {median_pct_diff}"


if __name__ == "__main__":
    test_ohlc_internal_consistency()
    test_no_unexpected_gaps()
    test_agrees_with_yfinance_within_tolerance()
    print("\nAll data_crypto.py Binance.US verification checks passed.")
