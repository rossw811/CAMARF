"""
research/rebuild_intraday_pool_symbols.py -- rebuild the 1h/4h intraday data of the Purity pool's intraday-pair
symbols through the corrected data layer (2026-09-27, Ross-approved "rebuild from IBKR").

Why: cached intraday bars were written through the removed per-bar liquidity filter (code review D1: a DAILY
$1M threshold applied per bar, NaN + forward-fill -- nearly every 1m bar of a mid-cap fabricated) and the old
snap_timestamps (D3/D4: 4h afternoon bar stamped at 09:30, 1h bars collided/lost, up to 90-min lookahead).
Older intraday history cannot be re-downloaded from yfinance (60-730 day windows), so the deep history is
rebuilt from IBKR.

Steps (the Purity pool's intraday pairs are 6 x 1h + 6 x 4h -> 19 symbols; other TFs untouched):
  1. MOVE (not delete) each symbol's yfinance 1h/4h cache files and IBKR {sym}_{1hr,4hr}_deep supplement files to
     output/cache/_intraday_backup_<date>/ (restored automatically if a rebuild step returns nothing).
  2. Re-fetch the recent yfinance 1h window (4h derived from it, session-aligned) via
     YFinanceFeed.get_intraday_fallback -> now through the fixed clean()/snap_timestamps.
  3. Then run `python data_ibkr.py --symbols ... --tfs 1h 4h --force` (separate step, printed at the end) to
     rebuild the IBKR deep history and merge it with the clean recent yfinance window.

Usage: python research/rebuild_intraday_pool_symbols.py [--pairs output/research/purity_pairs.parquet]
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
from data import DataStore, YFinanceFeed

_TFS = ("1h", "4h")
_SUPP = os.path.join("output", "cache", "ibkr_supplement")
_ETFS = {"SPY", "QQQ", "VOO", "IVV", "DIA", "IWM"}


def _stats(df):
    if df is None or len(df) == 0:
        return 0, None, None, np.nan
    c = df["close"].dropna() if "close" in df.columns else pd.Series(dtype=float)
    return len(df), df.index.min(), df.index.max(), float((c.diff() == 0).mean()) if len(c) > 1 else np.nan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default=os.path.join("output", "research", "purity_pairs.parquet"))
    ap.add_argument("--symbols", nargs="*", default=None)
    args = ap.parse_args()
    if args.symbols:
        syms = sorted(args.symbols)
    else:
        p = pd.read_parquet(args.pairs)
        tfc = "tf_label" if "tf_label" in p.columns else [c for c in p.columns if c.startswith("tf")][0]
        i = p[p[tfc].isin(_TFS)]
        syms = sorted(set(i["symbol_a"]) | set(i["symbol_b"]))
    backup = os.path.join(Config.DATA.CACHE_DIR, f"_intraday_backup_{time.strftime('%Y%m%d')}")
    os.makedirs(os.path.join(backup, "ibkr_supplement"), exist_ok=True)
    print(f"{len(syms)} symbols: {syms}\nbackup -> {backup}")

    rows = []
    for s in syms:
        moved = []
        for tf in _TFS:
            old = DataStore.load(s, tf)
            src = DataStore._path(s, tf)
            if os.path.exists(src):
                dst = os.path.join(backup, os.path.basename(src)); shutil.move(src, dst); moved.append((dst, src))
            safe = DataStore._TF_SAFE.get(tf, tf)
            sp = os.path.join(_SUPP, f"{s}_{safe}_deep.parquet")
            if os.path.exists(sp):
                dst = os.path.join(backup, "ibkr_supplement", os.path.basename(sp)); shutil.move(sp, dst); moved.append((dst, sp))
            ac = "etf" if s in _ETFS else "equity"
            new = YFinanceFeed.get_intraday_fallback(s, ac, tf)
            n_old, _, last_old, zc_old = _stats(old)
            n_new, first_new, last_new, zc_new = _stats(new)
            restored = False
            if new is None or n_new == 0:
                for dst, orig in moved:
                    if orig == src and os.path.exists(dst):
                        shutil.move(dst, orig); restored = True
            else:
                DataStore.save(s, tf, new)
            rows.append({"symbol": s, "tf": tf, "rows_old": n_old, "last_old": last_old, "zero_change_old": zc_old,
                         "rows_new": n_new, "first_new": first_new, "last_new": last_new, "zero_change_new": zc_new,
                         "restored_original_yf": restored})
    R = pd.DataFrame(rows)
    os.makedirs("output/research", exist_ok=True)
    R.to_parquet("output/research/rebuild_intraday_pool_symbols_report.parquet")
    pd.set_option("display.width", 220)
    print(R.to_string(index=False))
    print("\nNext (IBKR deep history, merges onto the clean recent window):")
    print("  python data_ibkr.py --symbols " + " ".join(syms) + " --tfs 1h 4h --force")


if __name__ == "__main__":
    main()
