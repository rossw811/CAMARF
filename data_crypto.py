"""
data_crypto.py — Binance.US supplemental/deep-intraday-history data pipeline
for CAMARF's crypto universe (2026-08-02).
================================================================================
SEPARATE SCRIPT from data.py, mirroring data_ibkr.py/data_wrds.py's own
precedent (never merge a second fetch path into data.py's main loop —
CLAUDE.md rule 2 exists specifically because that was tried once with IBKR
and cost weeks of instability). Run manually.

WHY THIS EXISTS: yfinance's own intraday depth limits (_YF_INTRADAY_MAP in
data.py) cap 1m history at 5 CALENDAR DAYS -- for crypto specifically, which
trades continuously and has been listed on real exchanges since 2017-2019,
that is a severe depth shortfall relative to what's actually available.

EXCHANGE CHOICE, verified directly, not assumed:
  - Binance.com (the global exchange) is GEO-BLOCKED for US IPs -- confirmed
    directly by hitting its own ToS "Eligibility" restriction from this
    machine. Not usable from a US location.
  - Binance.US (the separate, licensed US-facing entity) has NO such
    restriction and covers 15/15 of CAMARF's CRYPTO universe (config.py).
  - DISCLOSED LIMITATION: Binance.US carries a small fraction of global
    Binance.com's liquidity/volume. This is real, accurate, tradeable
    US-venue market data -- just not the same depth of market as the
    geo-blocked global exchange. Stated here, not silently assumed away.

QUOTE CURRENCY: USDT, not native USD -- a deliberate choice, not the
original plan. Binance.US's native USD pairs were checked first and DO
cover 15/15 symbols, but real-data verification (debug/_verify_data_crypto_
binance.py) caught a genuine 586-DAY GAP in BTCUSD's daily history
(2023-07-14 -> 2025-02-19) -- confirmed via a second fetch that BTCUSDT has
ZERO gap across the identical window. This lines up with real history:
Binance.US lost its USD banking partner after 2023 SEC action and
suspended USD deposits/withdrawals/trading for ~19 months before restoring
it in early 2025; USDT (stablecoin) pairs traded continuously throughout.
Ross's explicit choice (2026-08-02): use USDT for continuity, disclosing
the USDT~USD peg as a standard, widely-accepted approximation in crypto
quant research (not literally USD) -- same "state the approximation
explicitly" convention this project already applies to every other
adjustment/proxy (e.g. WRDS's close_total_return, the realized-vol IV
proxy in options.py). USDT pair coverage independently verified: 15/15
CAMARF crypto symbols.

API access: public market-data endpoints (klines, exchangeInfo) need NO
authentication/API key -- confirmed directly. Rate limit 3600 request-weight
per minute; klines calls cost ~1-2 weight each, so a full historical backfill
for 15 symbols stays trivially within budget even with a conservative
per-request sleep (see _RATE_LIMIT_SLEEP_SEC below).

SCOPE, stated precisely (v1, 2026-08-02): fetches Binance.US's NATIVE
intervals matching CAMARF's TIMEFRAME_LABELS directly -- 1m, 3m, 5m, 15m,
30m, 1h, 4h, 1d. Binance natively supports 3m (unlike yfinance, where
CAMARF derives 3m from 1m due to Yahoo's 8-day 1m limit) -- used directly
here rather than re-derived, since this is a separate supplemental cache,
not required to be bit-identical to the yfinance derivation methodology.
NOT fetched in v1, disclosed rather than silently missing: 2m (no native
Binance interval; CAMARF's yfinance path derives it from 1m -- could be
added the same way here later, not done yet), 7D/1M/3M/6M (would need
resampling from 1d, same pattern data.py already uses for yfinance's
daily-and-coarser derivation -- not built yet).

CHECKPOINTING: per-symbol/interval progress is saved after each successful
fetch, so a crash/interruption resumes rather than restarting a multi-hour
backfill from scratch -- same discipline Ross explicitly requested for
data_wrds.py's long-running scans ("if the scripts crash i don't want to
have to restart. save progress").

Usage:
    python data_crypto.py                  # fetch all symbols, all intervals
    python data_crypto.py --symbols BTC ETH # scope to specific symbols
    python data_crypto.py --intervals 1h 1d # scope to specific intervals
"""
import argparse
import json
import os
import time
import urllib.request
from typing import List, Optional

import pandas as pd

from config import Config

_BASE_URL = "https://api.binance.us/api/v3"
_CACHE_DIR = os.path.join(Config.DATA.CACHE_DIR, "binance")
_CHECKPOINT_PATH = os.path.join(_CACHE_DIR, "_checkpoint.json")

# Binance's native intervals that map directly onto CAMARF's own
# TIMEFRAME_LABELS -- see module docstring's SCOPE section for what's
# deliberately not included in v1.
_INTERVALS = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"]
_INTERVAL_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
}
_MAX_ROWS_PER_CALL = 1000  # Binance's own per-request cap
_RATE_LIMIT_SLEEP_SEC = 0.25  # conservative; well within the 3600 weight/min budget


def _http_get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "CAMARF-research/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _load_checkpoint() -> dict:
    if os.path.exists(_CHECKPOINT_PATH):
        with open(_CHECKPOINT_PATH) as f:
            return json.load(f)
    return {}


def _save_checkpoint(checkpoint: dict) -> None:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    with open(_CHECKPOINT_PATH, "w") as f:
        json.dump(checkpoint, f)


def fetch_klines(symbol_pair: str, interval: str, start_time_ms: int = 0,
                  end_time_ms: Optional[int] = None) -> pd.DataFrame:
    """
    Paginates Binance.US's /klines endpoint from start_time_ms forward until
    either end_time_ms is reached or the exchange returns fewer than
    _MAX_ROWS_PER_CALL rows (i.e. we've caught up to the present). Returns a
    DataFrame with columns [open, high, low, close, volume], DatetimeIndex
    (UTC), matching data.py's own OHLCV column convention.
    """
    rows = []
    cursor = start_time_ms
    while True:
        url = (f"{_BASE_URL}/klines?symbol={symbol_pair}&interval={interval}"
               f"&startTime={cursor}&limit={_MAX_ROWS_PER_CALL}")
        if end_time_ms is not None:
            url += f"&endTime={end_time_ms}"
        batch = _http_get_json(url)
        if not batch:
            break
        rows.extend(batch)
        last_open_time = batch[-1][0]
        cursor = last_open_time + _INTERVAL_MS[interval]
        time.sleep(_RATE_LIMIT_SLEEP_SEC)
        if len(batch) < _MAX_ROWS_PER_CALL:
            break
        if end_time_ms is not None and cursor >= end_time_ms:
            break

    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = pd.DataFrame(rows, columns=[
        "open_time", "open", "high", "low", "close", "volume", "close_time",
        "quote_volume", "n_trades", "taker_buy_base", "taker_buy_quote", "ignore",
    ])
    df = df[["open_time", "open", "high", "low", "close", "volume"]].copy()
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    df.index = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df.index.name = None
    df = df.drop(columns=["open_time"])
    df = df[~df.index.duplicated(keep="first")].sort_index()
    return df


def run(symbols: Optional[List[str]] = None, intervals: Optional[List[str]] = None) -> None:
    symbols = symbols or list(Config.UNIVERSE.CRYPTO)
    intervals = intervals or _INTERVALS
    os.makedirs(_CACHE_DIR, exist_ok=True)
    checkpoint = _load_checkpoint()

    print(f"Fetching {len(symbols)} symbols x {len(intervals)} intervals from Binance.US...")
    for symbol in symbols:
        symbol_usdt = f"{symbol}USDT"
        for interval in intervals:
            key = f"{symbol}_{interval}"
            if checkpoint.get(key) == "done":
                print(f"  {key}: already done (checkpoint), skipping")
                continue
            try:
                df = fetch_klines(symbol_usdt, interval, start_time_ms=0)
            except Exception as e:
                print(f"  {key}: FAILED — {type(e).__name__}: {e}")
                continue
            if df.empty:
                print(f"  {key}: no data returned (symbol may not exist on Binance.US)")
                checkpoint[key] = "done"  # no point retrying a nonexistent pair every run
                _save_checkpoint(checkpoint)
                continue
            out_path = os.path.join(_CACHE_DIR, f"{symbol}_{interval}.parquet")
            df.to_parquet(out_path)
            checkpoint[key] = "done"
            _save_checkpoint(checkpoint)
            print(f"  {key}: {len(df)} bars, {df.index.min()} -> {df.index.max()} -> {out_path}")

    print("Done.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="CAMARF data_crypto.py — Binance.US deep-intraday-history fetch")
    p.add_argument("--symbols", nargs="+", default=None, help="Subset of CAMARF crypto symbols (default: all)")
    p.add_argument("--intervals", nargs="+", default=None, help="Subset of intervals (default: all)")
    args = p.parse_args()
    run(symbols=args.symbols, intervals=args.intervals)
