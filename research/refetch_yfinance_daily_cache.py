"""
research/refetch_yfinance_daily_cache.py -- regenerate the yfinance DAILY cache (1D + derived 7D/1M) with
the corrected data layer (2026-09-27, Ross-approved; code review D1 + D2).

Why: every cached yfinance daily file was written through DataCleaner._liquidity_filter (D1, removed),
which NaN'd bars under a $1M dollar-volume threshold and forward-filled -- fabricated flat bars (573 of
1,697 files had >20% zero-change days; forex 100% NaN) -- and the daily refresh never ran (D2), so files
are frozen at 2026-06-17. A full-history re-download through the fixed code replaces both.

Scope: DAILY and coarser only. yfinance's own daily history is complete, so nothing is lost. Intraday
files are deliberately NOT touched: yfinance serves only 60-730 days of intraday history, so the
accumulated older intraday bars (and IBKR supplements) are irreplaceable -- how to handle their D1/D3/D4
contamination is a decision for Ross.

Safety: each symbol's 1D/7D/1M files are MOVED (not deleted) to a dated backup directory first; if the
new download fails for a symbol, its originals are moved back. Every symbol's old-vs-new row count,
last bar and zero-change-close fraction are written to output/research/refetch_yfinance_daily_report.parquet.

2026-09-27: `--classes futures,commodity` regenerates the 27 yfinance =F files written through the removed
_roll_adjust (code review D9), which roughly doubled every >5% daily move.

Usage (project root):
    python research/refetch_yfinance_daily_cache.py --sample 25     # first, a checked sample
    python research/refetch_yfinance_daily_cache.py                 # then the full universe
"""
import argparse
import os
import shutil
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from data import DataStore, UniverseBuilder, YFinanceFeed, _to_yf_ticker

_YF_CLASSES = ("equity", "equity_intl", "crypto", "forex", "etf", "fx_spot")
_TFS = ("1D", "7D", "1M", "3M", "6M")  # 3M/6M added 2026-09-27 (D13: all derived TFs re-derived together)


def _stats(df):
    if df is None or len(df) == 0 or "close" not in df.columns:
        return 0, None, np.nan
    c = df["close"].dropna()
    return len(df), df.index.max(), float((c.diff() == 0).mean()) if len(c) > 1 else np.nan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=None)
    ap.add_argument("--chunk-size", type=int, default=Config.DATA.YF_CHUNK_SIZE)
    ap.add_argument("--classes", default=",".join(_YF_CLASSES),
                    help="comma-separated asset classes; e.g. 'futures,commodity' for the D9 refetch "
                         "(those files were written with the inverted >5%% 'roll adjustment')")
    ap.add_argument("--include-missing", action="store_true",
                    help="also fetch symbols with no cached 1D file (12 of 27 futures/commodities had none)")
    args = ap.parse_args()

    raw = UniverseBuilder()._build_raw_list()
    excl = UniverseBuilder.load_exclusions()
    assets = sorted({(s, c) for s, c in raw if s not in excl and c in set(args.classes.split(","))})
    if not args.include_missing:
        assets = [(s, c) for s, c in assets if os.path.exists(DataStore._path(s, "1D"))]
    if args.sample:
        assets = assets[:args.sample]
    backup = os.path.join(Config.DATA.CACHE_DIR, f"_yf_daily_backup_{time.strftime('%Y%m%d')}")
    os.makedirs(backup, exist_ok=True)
    print(f"{len(assets)} yfinance daily symbols to regenerate; backup -> {backup}")

    old = {}
    for s, _ in assets:
        old[s] = _stats(DataStore.load(s, "1D"))
        for tf in _TFS:
            src = DataStore._path(s, tf)
            if os.path.exists(src):
                shutil.move(src, os.path.join(backup, os.path.basename(src)))

    res = YFinanceFeed.get_equity_history([s for s, _ in assets], chunk_size=args.chunk_size,
                                          yf_tickers=[_to_yf_ticker(s, c) for s, c in assets])
    rows, n_restored = [], 0
    for s, c in assets:
        new = (res.get(s) or {}).get("1D")
        n_new, last_new, zc_new = _stats(new)
        restored = False
        if new is None or n_new == 0:
            for tf in _TFS:
                b = os.path.join(backup, os.path.basename(DataStore._path(s, tf)))
                if os.path.exists(b) and not os.path.exists(DataStore._path(s, tf)):
                    shutil.move(b, DataStore._path(s, tf))
            restored, n_restored = True, n_restored + 1
        n_old, last_old, zc_old = old[s]
        rows.append({"symbol": s, "asset_class": c, "yf_ticker": _to_yf_ticker(s, c), "rows_old": n_old,
                     "rows_new": n_new, "last_old": last_old, "last_new": last_new,
                     "zero_change_old": zc_old, "zero_change_new": zc_new, "restored_original": restored})
    rep = pd.DataFrame(rows)
    os.makedirs("output/research", exist_ok=True)
    out = "output/research/refetch_yfinance_daily_report.parquet"
    if args.sample and os.path.exists(out):
        rep = pd.concat([pd.read_parquet(out), rep]).drop_duplicates("symbol", keep="last")
    rep.to_parquet(out)
    ok = rep[~rep["restored_original"]]
    print(f"regenerated {len(ok)}, restored originals for {n_restored}")
    if len(ok):
        print(f"median zero-change fraction: old {ok['zero_change_old'].median():.3f} -> new {ok['zero_change_new'].median():.3f}; "
              f"files >20% flat: old {(ok['zero_change_old'] > .2).sum()} -> new {(ok['zero_change_new'] > .2).sum()}")
        print(f"last bar: old mode {ok['last_old'].mode().iloc[0]} -> new max {ok['last_new'].max()}")
    print(rep.head(30).to_string(index=False))


if __name__ == "__main__":
    main()
