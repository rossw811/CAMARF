"""
Regression test for code-review finding D2 (2026-09-26): the daily incremental refresh never worked.
  (a) get_equity_history(period="1mo") -> _download_chunk checked DataStore.is_fresh(..., max_age_hours=
      None), which is True whenever the file exists, so it returned the OLD cached frame without
      downloading; the caller then "appended" the old frame to itself and logged it as updated
      (yfinance 1D files were frozen at 2026-06-17);
  (b) had a download happened, a 1-month slice (~21 bars) fails clean()'s 100-bar minimum;
  (c) get_equity_history then DataStore.save()d its results -- overwriting the full history (and the
      7D/1M derived from it) with the 1-month slice.

Required behaviour of get_equity_history(..., incremental=True):
  1. actually downloads (bypasses the exists-only cache check);
  2. accepts a short recent slice (no MIN_BARS rejection);
  3. never overwrites the cache itself -- the caller merges with DataStore.append, and the full
     history grows (300 cached + 10 new days = 310), it is never replaced by the slice.

yf.download is mocked; the cache lives in a temp directory.

Run: python debug/_verify_daily_incremental_refresh.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import data
from config import Config
from data import DataStore, YFinanceFeed

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def _ohlcv(idx, seed):
    c = 50 * np.exp(np.cumsum(np.random.default_rng(seed).normal(0, 0.01, len(idx))))
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1e6}, index=idx)


def main():
    orig_dir, orig_dl = Config.DATA.CACHE_DIR, data.yf.download
    days = pd.bdate_range("2025-03-03", "2026-06-30")
    hist, recent = days[days <= "2026-06-17"], days[days > "2026-06-01"]
    calls = []

    def fake_download(tickers, period=None, interval=None, **kw):
        calls.append((period, interval))
        if interval != "1d":
            return pd.DataFrame()
        df = _ohlcv(recent, 7)
        if isinstance(tickers, (list, tuple)) and len(tickers) > 1:
            return pd.concat({t: df for t in tickers}, axis=1).swaplevel(0, 1, axis=1)
        return df

    with tempfile.TemporaryDirectory() as d:
        Config.DATA.CACHE_DIR = d
        data.yf.download = fake_download
        try:
            h = _ohlcv(hist, 1).rename(columns=str.lower)
            DataStore.save("SYNTH", "1D", h)
            n_before, last_before = len(h), h.index.max()
            res = YFinanceFeed.get_equity_history(["SYNTH"], chunk_size=50, period="1mo", incremental=True)
            new = res.get("SYNTH", {}).get("1D")
            check("downloads_despite_existing_cache", any(p == "1mo" for p, _ in calls), f"calls={calls[:3]}")
            check("short_slice_not_rejected", new is not None and len(new) > 0,
                  f"slice rows={0 if new is None else len(new)}")
            after = DataStore.load("SYNTH", "1D")
            check("cache_not_overwritten_by_fetch", after is not None and len(after) == n_before,
                  f"cache rows after fetch={None if after is None else len(after)} (was {n_before})")
            if new is not None:
                combined = DataStore.append("SYNTH", "1D", new)
                check("append_extends_history", len(combined) > n_before and combined.index.max() > last_before
                      and combined.index.min() == h.index.min(),
                      f"{n_before} -> {len(combined)} rows, last {last_before.date()} -> {combined.index.max().date()}")
        finally:
            Config.DATA.CACHE_DIR, data.yf.download = orig_dir, orig_dl
    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
