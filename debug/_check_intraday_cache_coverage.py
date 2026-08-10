"""
debug/_check_intraday_cache_coverage.py -- Step 0 of the PIT-safe episodic
pair-confirmation comparison-arm plan (ancient-mixing-feather.md).

WHY THIS EXISTS: before scoping a new intraday (1h/4h) episodic scanner, the
plan needed to know whether >=2yr of cached 1h/4h history is a PNC/ZION-only
situation or a universe-wide one. An ad-hoc check during planning found
1,535/1,576 (97%) of cached 1h symbols qualify -- this script turns that
ad-hoc check into a committed, rerunnable artifact rather than a one-off
number quoted from memory, so it can be re-verified after any future cache
refresh instead of going stale silently.

Not a statistical method -- pure inventory, so no synthetic ground-truth
verification is needed (nothing here could be "wrong" in a way a synthetic
test would catch; the only failure mode is a silently-skipped unreadable
file, which this script treats as fatal, not skippable).

Usage:
    python debug/_check_intraday_cache_coverage.py
"""
import glob
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE_DIR = os.path.join(_ROOT, "output", "cache")
_OUT_DIR = os.path.join(_ROOT, "output", "research")

# DataStore._TF_SAFE's intraday-relevant entries (data.py:111-123) -- kept as
# a local literal rather than importing DataStore, since this script only
# needs the filename suffix convention, not the full data.py import graph.
_TF_SUFFIXES = {"1h": "1hr", "4h": "4hr"}


def _symbol_from_path(path: str, suffix: str) -> str:
    base = os.path.basename(path)
    assert base.endswith(f"_{suffix}.parquet"), base
    return base[: -len(f"_{suffix}.parquet")]


def scan_tf(tf_label: str) -> pd.DataFrame:
    suffix = _TF_SUFFIXES[tf_label]
    paths = sorted(glob.glob(os.path.join(_CACHE_DIR, f"*_{suffix}.parquet")))
    rows = []
    for p in paths:
        symbol = _symbol_from_path(p, suffix)
        # Raise, don't skip, on a bad read -- a silently-skipped unreadable
        # file would understate coverage without anyone noticing (this is
        # exactly the failure mode the plan's docstring called out).
        df = pd.read_parquet(p)
        if df.empty:
            rows.append(
                dict(symbol=symbol, tf=tf_label, n_bars=0, span_days=0,
                     first_date=pd.NaT, last_date=pd.NaT)
            )
            continue
        idx = df.index if isinstance(df.index, pd.DatetimeIndex) else pd.to_datetime(df.index)
        first_date, last_date = idx.min(), idx.max()
        rows.append(
            dict(
                symbol=symbol,
                tf=tf_label,
                n_bars=len(df),
                span_days=(last_date - first_date).days,
                first_date=first_date,
                last_date=last_date,
            )
        )
    return pd.DataFrame(rows)


def main() -> pd.DataFrame:
    Config.ensure_dirs()
    frames = [scan_tf(tf) for tf in _TF_SUFFIXES]
    result = pd.concat(frames, ignore_index=True)

    os.makedirs(_OUT_DIR, exist_ok=True)
    out_path = os.path.join(_OUT_DIR, "intraday_cache_coverage.parquet")
    result.to_parquet(out_path)

    for tf in _TF_SUFFIXES:
        sub = result[result["tf"] == tf]
        ge2yr = (sub["span_days"] >= 730).sum()
        median_span = sub["span_days"].median() if len(sub) else float("nan")
        print(
            f"[{tf}] {len(sub)} symbols, {ge2yr} ({ge2yr / max(len(sub), 1):.0%}) "
            f">= 2yr, median span {median_span:.0f} days"
        )
    print(f"Wrote {out_path} ({len(result)} rows)")
    return result


if __name__ == "__main__":
    main()
