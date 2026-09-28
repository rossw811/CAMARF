"""
research/restamp_coarse_bars_d13.py -- one-off cache migration for code review D13 (2026-09-27).

The resamplers now stamp every coarse bar at calendar period end (period_bars.py). Cached files written before the
fix still carry period-START stamps (lookahead). This script rewrites them from each symbol's own 1D file:
  - yfinance DataStore cache (output/cache/{SYM}_1day.parquet): 7D/1M/3M/6M re-derived with
    YFinanceFeed._resample_from_daily -- the production function, not a copy;
  - WRDS cache (output/cache/wrds/{LABEL}_1D.parquet): existing 7D/3M/6M/1Y files re-derived with
    data_wrds.resample_daily_to; native CRSP monthly {LABEL}_1M.parquet restamped to calendar month end
    (values untouched).
Every file is copied to output/cache/_backup_d13_<date>/ before it is overwritten. Writes are atomic (tmp + replace).
Report: output/research/restamp_coarse_bars_d13_report.parquet.
Usage: python research/restamp_coarse_bars_d13.py [--limit N]
"""
import argparse
import os
import shutil
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data_wrds as dw
from config import Config
from data import DataStore, YFinanceFeed
from period_bars import restamp_to_period_end

_BACKUP = os.path.join("output", "cache", f"_backup_d13_{pd.Timestamp.now():%Y%m%d}")


def _write(df, path, backup_sub, stats, source, tf):
    existed = os.path.exists(path)
    if existed:
        dst = os.path.join(_BACKUP, backup_sub, os.path.basename(path))
        if not os.path.exists(dst):  # a re-run never overwrites the original backup
            shutil.copy2(path, dst)
    df.to_parquet(path + ".tmp")
    os.replace(path + ".tmp", path)
    stats.append((source, tf, os.path.basename(path), "replaced" if existed else "created", len(df),
                  df.index[-1] if len(df) else pd.NaT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    for sub in ("yf", "wrds"):
        os.makedirs(os.path.join(_BACKUP, sub), exist_ok=True)
    stats, t0 = [], time.time()

    yf_dir = Config.DATA.CACHE_DIR
    yf_files = sorted(e.name for e in os.scandir(yf_dir) if e.is_file() and e.name.endswith("_1day.parquet"))
    for i, name in enumerate(yf_files[: args.limit], 1):
        sym = name[: -len("_1day.parquet")]
        df = pd.read_parquet(os.path.join(yf_dir, name))
        for tf, d in YFinanceFeed._resample_from_daily(df).items():
            if d is not None and not d.empty:
                _write(d, DataStore._path(sym, tf), "yf", stats, "yf", tf)
        if i % 500 == 0:
            print(f"yf {i}/{len(yf_files)} ({time.time() - t0:.0f}s)", flush=True)

    wdir = dw._OUT_DIR
    names = {e.name for e in os.scandir(wdir) if e.is_file()}
    labels = sorted(n[: -len("_1D.parquet")] for n in names if n.endswith("_1D.parquet"))
    done = 0
    for label in labels:
        derived = [tf for tf in ("7D", "3M", "6M", "1Y") if f"{label}_{tf}.parquet" in names]
        has_1m = f"{label}_1M.parquet" in names
        if not derived and not has_1m:
            continue
        done += 1
        if args.limit and done > args.limit:
            break
        if derived:
            df = pd.read_parquet(os.path.join(wdir, f"{label}_1D.parquet"))
            for tf in derived:
                d = dw.resample_daily_to(df, tf)
                if d is not None and not d.empty:
                    _write(d, os.path.join(wdir, f"{label}_{tf}.parquet"), "wrds", stats, "wrds", tf)
        if has_1m:
            m = pd.read_parquet(os.path.join(wdir, f"{label}_1M.parquet"))
            _write(restamp_to_period_end(m, "1M"), os.path.join(wdir, f"{label}_1M.parquet"), "wrds", stats, "wrds",
                   "1M_native")
        if done % 500 == 0:
            print(f"wrds {done} ({time.time() - t0:.0f}s)", flush=True)

    S = pd.DataFrame(stats, columns=["source", "tf", "file", "action", "rows", "last_stamp"])
    os.makedirs(os.path.join("output", "research"), exist_ok=True)
    S.to_parquet(os.path.join("output", "research", "restamp_coarse_bars_d13_report.parquet"))
    print(S.groupby(["source", "tf", "action"]).size().to_string())
    print(f"done in {time.time() - t0:.0f}s; backups in {_BACKUP}")


if __name__ == "__main__":
    main()
