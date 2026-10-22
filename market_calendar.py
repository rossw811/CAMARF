"""Trading calendars per market, for counting data holes in trading days (Ross 2026-10-22: Amendment 5's 5-day rule and
backtest.py's B1 gap exit count a day as missing only if the leg's market traded that day; counting weekdays turned
exchange closures longer than five weekdays -- Lunar New Year on some Asian listings, 6-7 -- into "holes").

Markets (`market_of`):
  US          CRSP / yfinance US listings: the NYSE calendar (data.DataAligner._get_nyse_calendar)
  CRYPTO      Binance labels: every calendar day
  FX          forex labels (=X): weekdays
  yf:<suffix> yfinance non-US (.T, .HK, .L, ...): derived from that suffix group's own data
  exchg:<cd>  Compustat Global: derived from the listings on the same exchange (comp.g_security.exchg,
              output/cache/wrds/global_security_exchange.parquet from WRDS job 35)
Derived calendars (`derive_calendar`): a weekday is a trading day if at least half of the group's listings live on it
(first valid date <= day <= last) have a valid price; where fewer than MIN_GROUP listings are live it falls back to
every weekday (the old rule), so thin history is never made stricter or looser than before. Built once from the
pre-seal caches by research/build_market_calendars.py -> output/research/market_calendars.parquet.
debug/_verify_market_calendar_holes.py
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Dict, Optional

import numpy as np
import pandas as pd

from config import Config

MIN_GROUP = 5
CALENDARS_PATH = os.path.join(Config.DATA.OUTPUT_DIR, "research", "market_calendars.parquet")
EXCHANGE_PATH = os.path.join(Config.DATA.CACHE_DIR, "wrds", "global_security_exchange.parquet")
_CAL_START, _CAL_END = "1925-01-01", "2030-12-31"


def market_of(symbol: str, exchange_by_label: Optional[Dict[str, str]] = None) -> str:
    s = str(symbol)
    if s.startswith("GVKEY"):
        base = s.split("_seg")[0]
        ex = (exchange_by_label if exchange_by_label is not None else _exchange_by_label()).get(base)
        return f"exchg:{ex}" if ex is not None else "UNKNOWN"
    if s.endswith("=X"):
        return "FX"
    if _is_crypto(s):
        return "CRYPTO"
    if "." in s and not s.startswith("PERMNO"):
        suf = "." + s.rsplit(".", 1)[1]
        if suf not in (".A", ".B", ".C"):          # share classes are US
            return f"yf:{suf}"
    return "US"


def _is_crypto(s: str) -> bool:
    """Crypto labels are "<ROOT>-USD" (universe_loader / data.py, D16), never a bare root (LTC is a stock)."""
    return s.endswith("-USD")


@lru_cache(maxsize=1)
def _exchange_by_label() -> Dict[str, str]:
    if not os.path.exists(EXCHANGE_PATH):
        return {}
    e = pd.read_parquet(EXCHANGE_PATH, columns=["gvkey", "iid", "exchg"]).dropna(subset=["exchg"])
    return {f"GVKEY{str(g).zfill(6)}_{i}": str(int(x)) if str(x).replace(".0", "").isdigit() else str(x)
            for g, i, x in zip(e["gvkey"], e["iid"], e["exchg"])}


def derive_calendar(valid_dates_by_member: Dict[str, pd.DatetimeIndex], min_group: int = MIN_GROUP) -> pd.DatetimeIndex:
    """Weekdays on which at least half of the members live that day have a valid price; weekdays with fewer than
    `min_group` live members are kept (fallback to the weekday rule)."""
    spans = [(v.min(), v.max()) for v in valid_dates_by_member.values() if len(v)]
    if not spans:
        return pd.DatetimeIndex([])
    wd = pd.bdate_range(min(a for a, _ in spans), max(b for _, b in spans))
    live = np.zeros(len(wd), dtype=int)
    have = np.zeros(len(wd), dtype=int)
    for v in valid_dates_by_member.values():
        if not len(v):
            continue
        lo, hi = wd.searchsorted(v.min()), wd.searchsorted(v.max(), side="right")
        live[lo:hi] += 1
        ix = wd.get_indexer(pd.DatetimeIndex(v).normalize().unique())
        have[ix[ix >= 0]] += 1
    keep = (live < min_group) | (have >= 0.5 * live)
    return pd.DatetimeIndex(wd[keep])


@lru_cache(maxsize=1)
def _derived() -> Dict[str, pd.DatetimeIndex]:
    if not os.path.exists(CALENDARS_PATH):
        return {}
    c = pd.read_parquet(CALENDARS_PATH)
    return {m: pd.DatetimeIndex(g["date"]).sort_values() for m, g in c.groupby("market")}


@lru_cache(maxsize=64)
def _market_calendar(market: str) -> Optional[pd.DatetimeIndex]:
    if market == "US":
        from data import DataAligner
        return DataAligner._get_nyse_calendar(_CAL_START, _CAL_END)
    if market == "CRYPTO":
        return pd.date_range(_CAL_START, _CAL_END, freq="D")
    if market == "FX":
        return pd.bdate_range(_CAL_START, _CAL_END)
    return _derived().get(market)          # None -> weekday fallback (reported by build_market_calendars)


def calendar_for(symbol: str) -> Optional[pd.DatetimeIndex]:
    """The symbol's market trading days, or None (callers fall back to weekdays)."""
    return _market_calendar(market_of(symbol))


def pair_calendar(sym_a: str, sym_b: str) -> Optional[pd.DatetimeIndex]:
    """Days both legs' markets traded (a pair can only have a bar when both are open); None if either is unknown."""
    a, b = calendar_for(sym_a), calendar_for(sym_b)
    if a is None or b is None:
        return None
    return a.intersection(b)


def missing_trading_days(days: np.ndarray, cal: Optional[pd.DatetimeIndex]) -> np.ndarray:
    """For consecutive dates (datetime64[D], ascending): trading days strictly between each pair. cal None -> weekdays
    (np.busday_count, the previous rule)."""
    days = np.asarray(days, dtype="datetime64[D]")
    if len(days) < 2:
        return np.zeros(0, dtype=int)
    if cal is None:
        return np.maximum(np.busday_count(days[:-1] + 1, days[1:]), 0)
    c = np.asarray(cal.values.astype("datetime64[D]"))
    lo = np.searchsorted(c, days[:-1], side="right")     # first calendar day after the earlier date
    hi = np.searchsorted(c, days[1:], side="left")       # calendar days before the later date
    return np.maximum(hi - lo, 0)
