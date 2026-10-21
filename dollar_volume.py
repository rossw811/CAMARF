"""
dollar_volume.py -- USD dollar volume of a daily price frame, one rule for every liquidity gate (code review R1.2,
fixed 2026-10-07).

Price: `close_usd` where the frame has it (Compustat Global listings: `close` is LOCAL currency -- a yen close of 1694
is $10.66), else |close| (CRSP is USD; a negative close is CRSP's bid/ask-midpoint convention for a no-trade day).
Before this module, rolling_adv / flat_adv / data_wrds.compute_symbol_adv_wrds multiplied local `close` by volume
and compared it with a USD threshold (yen listings ~159x too liquid). yfinance non-US files carry no `close_usd`:
since 2026-10-20 (W5.6b) usd_dollar_volume(df, symbol) converts them by exchange suffix with the cached daily yfinance
FX series ({CCY}USD=X_1day.parquet, as of each date); London (.L) quotes in pence. An unknown non-US suffix or a
missing FX series gives NaN -- excluded, never guessed.
debug/_verify_usd_dollar_volume.py, debug/_verify_usd_dollar_volume_yfinance.py
"""
import functools
import os
import re

import pandas as pd

# yfinance exchange suffix -> (currency, price units per currency unit). Only suffixes present in the cache are listed.
_YF_SUFFIX_CCY = {"T": ("JPY", 1.0), "HK": ("HKD", 1.0), "L": ("GBP", 100.0)}   # .L: GBp (pence)
_EQUITY_SUFFIX = re.compile(r"^[A-Z0-9&-]+\.([A-Z]{1,3})$")
_FX_PAIR = re.compile(r"^[A-Z]{3}\.[A-Z]{3}$")   # IBKR-style forex labels (AUD.JPY): not equities, unchanged


@functools.lru_cache(maxsize=None)
def _cached_fx(ccy: str):
    from config import Config
    f = os.path.join(Config.DATA.CACHE_DIR, f"{ccy}USD=X_1day.parquet")
    if not os.path.exists(f):
        return None
    d = pd.read_parquet(f)
    s = pd.to_numeric(d["close"], errors="coerce")
    s.index = pd.to_datetime(d.index)
    return s.dropna().sort_index()


def usd_price(df: pd.DataFrame) -> pd.Series:
    if "close_usd" in df.columns and df["close_usd"].notna().any():
        return pd.to_numeric(df["close_usd"], errors="coerce")
    return pd.to_numeric(df["close"], errors="coerce").abs()


def usd_dollar_volume(df: pd.DataFrame, symbol: str = None, fx_loader=None) -> pd.Series:
    """USD dollar volume per bar. `symbol` (yfinance label) triggers the non-US conversion; `fx_loader(ccy)` returns a
    date-indexed USD-per-unit series (default: the cached yfinance FX file)."""
    vol = pd.to_numeric(df["volume"], errors="coerce")
    if "close_usd" in df.columns and df["close_usd"].notna().any():
        return (usd_price(df) * vol).astype(float)
    m = _EQUITY_SUFFIX.match(str(symbol)) if symbol and not _FX_PAIR.match(str(symbol)) else None
    if m:
        if m.group(1) not in _YF_SUFFIX_CCY:
            return pd.Series(float("nan"), index=df.index)
        ccy, units = _YF_SUFFIX_CCY[m.group(1)]
        fx = (fx_loader or _cached_fx)(ccy)
        if fx is None or len(fx) == 0:
            return pd.Series(float("nan"), index=df.index)
        dates = pd.to_datetime(df.index)
        rate = fx.reindex(fx.index.union(dates)).ffill().reindex(dates).to_numpy()   # as of each date, never later
        px = pd.to_numeric(df["close"], errors="coerce").abs().to_numpy() / units
        return pd.Series(px * rate * vol.to_numpy(), index=df.index, dtype=float)
    return (usd_price(df) * vol).astype(float)
