"""
Regression test for code-review finding D10 (2026-09-26): IBKRFeed.get_bars requests useRTH=False (extended hours)
and wrote the cleaned-but-UNSNAPPED bars to the cache (DataStore.append) before returning. Only one of its five
callers snapped afterwards (and appended the snapped copy too), so the cache held extended-hours bars and off-grid
stamps next to the snapped ones; the other callers (get_intraday, get_full_history, the 1D sweep and the depth
upgrade) persisted and used the raw bars directly. The yfinance fallbacks inside get_bars were cached unsnapped the
same way.
Fix: get_bars snaps (snap_timestamps, the production function) before every cache write and returns the snapped frame.
Checks (fake IB connection returning 1h bars from 04:00 to 19:00 ET; cache redirected to a temp dir):
  1. every cached stamp is a valid NYSE 1h bar open (09:30..15:30), no extended-hours bars;
  2. the cache equals snap_timestamps(DataCleaner.clean(raw)) -- exactly what the snapping caller would store;
  3. get_bars' return value equals the cached frame.
Run: python debug/_verify_ibkr_cache_snapped.py
"""
import os
import shutil
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import data as D
from config import Config

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


class _FakeIB:
    RequestTimeout = 0

    def __init__(self, bars):
        self._bars = bars

    def reqHistoricalData(self, *a, **k):
        return self._bars

    def isConnected(self):
        return True


def main():
    import ib_insync as ibi
    days = pd.bdate_range("2026-01-05", periods=160)
    bars = []
    for d in days:
        for h in range(4, 20):
            px = 100 + h * 0.1
            ts = pd.Timestamp(d) + pd.Timedelta(hours=h)
            bars.append(ibi.BarData(date=ts.to_pydatetime(), open=px, high=px, low=px, close=px, volume=1000,
                                    average=px, barCount=10))
    raw = ibi.util.df(bars)

    tmp = tempfile.mkdtemp(prefix="verify_d10_")
    orig_dir = Config.DATA.CACHE_DIR
    Config.DATA.CACHE_DIR = tmp
    try:
        f = D.IBKRFeed()  # constructor builds an ibi.IB() but does not connect
        f._ib = _FakeIB(bars)
        f.ensure_connected = lambda: True
        f._build_contract = lambda s, a: object()
        f._wait_rate_limit = lambda tf: None
        out = f.get_bars("TEST", "equity", "1 hour", "1h", "1 Y")
        cached = D.DataStore.load("TEST", "1h")
        tods = sorted(set(cached.index.strftime("%H:%M")))
        valid = [f"{h:02d}:30" for h in range(9, 16)]
        check("cache_only_session_grid", set(tods) <= set(valid), f"cached times={tods}")
        cleaned, _ = D.DataCleaner.clean(raw, "TEST", "equity", "1h", "1 hour", source="ibkr")
        exp = D.snap_timestamps(cleaned, "1h", symbol="TEST")
        check("cache_equals_snapped_clean", cached.index.equals(exp.index)
              and (cached["close"].to_numpy() == exp["close"].to_numpy()).all(),
              f"cached={len(cached)} expected={len(exp)}")
        check("return_equals_cache", out is not None and out.index.equals(cached.index))
    finally:
        Config.DATA.CACHE_DIR = orig_dir
        shutil.rmtree(tmp, ignore_errors=True)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
