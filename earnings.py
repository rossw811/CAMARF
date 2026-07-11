"""
CAMARF earnings.py — standalone module, fetch + cache earnings
announcement dates per symbol, for backtest.py's --storm-earnings-blackout
STORM variant.

Builds Development.md's "Planned: Earnings Blackout as STORM Variant"
(flagged 2026-06-29): skip entry signals within +-3 days of either pair
leg's earnings announcement date, since earnings moves are large,
idiosyncratic, and unrelated to the cointegration relationship — the
spread can gap violently and not revert within the holding window.

Data source: `yf.Ticker(sym).earnings_dates` (historical quarterly
earnings dates, typically 8 quarters back — sufficient for IS/OOS
backtest validation per the original plan). Read-only company metadata,
not historical bars — does not touch data.py's own cache/pipeline, same
convention as research/investigate_price_degeneracy_cause.py and
research/annotate_symbol_metadata.py (0.3s courteous inter-request delay,
given this project's yfinance rate-limit history, BUG-D31).

Cache: output/cache/earnings_dates.json — {symbol: [iso date strings]},
refreshed on demand via EarningsCalendar.build(symbols), read via
EarningsCalendar.load().

Usage:
    from earnings import EarningsCalendar
    cal = EarningsCalendar.load_or_build(["AMD", "DD"])
    cal.near_earnings("AMD", pd.Timestamp("2024-05-01"), window_days=3)
"""
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf

from config import Config

log = logging.getLogger("earnings")

_CACHE_PATH = os.path.join(Config.DATA.CACHE_DIR, "earnings_dates.json")
_INTER_REQUEST_DELAY = 0.3


@dataclass
class EarningsCalendar:
    dates_by_symbol: Dict[str, List[pd.Timestamp]] = field(default_factory=dict)

    @staticmethod
    def _fetch_one(symbol: str) -> List[pd.Timestamp]:
        try:
            ed = yf.Ticker(symbol).earnings_dates
        except Exception as e:
            log.debug("earnings_dates fetch failed for %s: %s", symbol, e)
            return []
        if ed is None or ed.empty:
            return []
        idx = pd.to_datetime(ed.index)
        if hasattr(idx, "tz") and idx.tz is not None:
            idx = idx.tz_localize(None)
        return sorted(pd.Timestamp(d) for d in idx)

    @classmethod
    def build(cls, symbols: List[str], save: bool = True) -> "EarningsCalendar":
        dates_by_symbol = {}
        for i, sym in enumerate(symbols):
            dates_by_symbol[sym] = cls._fetch_one(sym)
            if i < len(symbols) - 1:
                time.sleep(_INTER_REQUEST_DELAY)
        cal = cls(dates_by_symbol=dates_by_symbol)
        if save:
            cal.save()
        return cal

    def save(self, path: str = _CACHE_PATH) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        serializable = {
            sym: [d.isoformat() for d in dates]
            for sym, dates in self.dates_by_symbol.items()
        }
        with open(path, "w") as f:
            json.dump(serializable, f, indent=2)

    @classmethod
    def load(cls, path: str = _CACHE_PATH) -> Optional["EarningsCalendar"]:
        if not os.path.exists(path):
            return None
        with open(path) as f:
            raw = json.load(f)
        dates_by_symbol = {
            sym: [pd.Timestamp(d) for d in dates]
            for sym, dates in raw.items()
        }
        return cls(dates_by_symbol=dates_by_symbol)

    @classmethod
    def load_or_build(cls, symbols: List[str], force_refresh: bool = False) -> "EarningsCalendar":
        if not force_refresh:
            cached = cls.load()
            if cached is not None:
                missing = [s for s in symbols if s not in cached.dates_by_symbol]
                if not missing:
                    return cached
                log.info("Fetching earnings dates for %d symbols missing from cache", len(missing))
                fresh = cls.build(missing, save=False)
                cached.dates_by_symbol.update(fresh.dates_by_symbol)
                cached.save()
                return cached
        log.info("Building fresh earnings calendar for %d symbols", len(symbols))
        return cls.build(symbols)

    def near_earnings(self, symbol: str, dt: pd.Timestamp, window_days: int = 3) -> bool:
        """True if `dt` falls within +-window_days of ANY known earnings
        date for `symbol`. False (not blacked out) if the symbol has no
        known earnings dates — an absence of data is not treated as
        evidence of an earnings blackout."""
        dates = self.dates_by_symbol.get(symbol, [])
        if not dates:
            return False
        dt = pd.Timestamp(dt).normalize()
        for d in dates:
            if abs((dt - d.normalize()).days) <= window_days:
                return True
        return False
