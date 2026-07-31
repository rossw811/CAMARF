"""
CAMARF research/relational_regime_indicator.py — comparison/diagnostic
script, NOT part of the production pipeline (2026-07-14, task #61:
CAMARF-native relational regime indicator).

A rolling average pairwise correlation across the confirmed-pair
universe's underlying LEGS (not spread returns), as an internally-
generated stress/regime signal — no external data dependency (unlike
macro.py's FRED-based approach).

Distinct from research/comomentum.py, which already exists and measures
something related but different: comomentum tracks correlation among
SPREAD returns (a crowding/arbitrage-activity signal, Lou & Polk 2022).
This script tracks correlation among the LEGS' own price returns — a
general market-stress/regime signal, not specific to arbitrage crowding.
Checked before building to avoid reinventing comomentum's ground.

Validation note, corrected 2026-07-14: an earlier draft of this docstring
assumed the 2007/2008/2020 sanity check would be impossible, generalizing
from task #71's finding that the main 1h cache only goes back to
2023-07-24. That finding does NOT generalize to daily data — checked
directly, the daily cache for these symbols (several long-listed
utilities/industrials) actually reaches back to 1972. The sanity check
DOES run and DOES pass: the indicator spikes exactly at 2008-2009 (GFC,
peak 0.66-0.73), 2011-2012 (US downgrade/European debt crisis, peak
0.80), and 2020 (COVID crash, peak 0.79) — real, correctly-timed crisis
peaks, not coincidence. Left this correction in the docstring rather than
quietly fixing it, since assuming a finding from one timeframe/cache
generalizes to another without checking is exactly the kind of mistake
this project's discipline exists to catch.

Usage:
    python research/relational_regime_indicator.py --tf 1D --window 60
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from data import DataStore, _gap_aware_returns

# Same stable 9-pair set used throughout today's session -> 17 unique legs.
_DEFAULT_PAIRS = [
    ("LNT", "VTR"), ("LNT", "WELL"), ("AME", "MAR"), ("CMS", "DUK"),
    ("EG", "WRB"), ("HAL", "NOV"), ("MET", "TMHC"), ("PFG", "STLD"),
    ("UMBF", "FHB"),
]


def _unique_symbols(pairs):
    out = []
    seen = set()
    for a, b in pairs:
        for s in (a, b):
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out


def build_return_matrix(symbols, tf_label):
    series = {}
    for sym in symbols:
        df = DataStore.load(sym, tf_label)
        if df is None or df.empty:
            continue
        ret = pd.Series(_gap_aware_returns(df), index=df.index)
        series[sym] = ret
    if not series:
        return pd.DataFrame()
    mat = pd.DataFrame(series)
    return mat.dropna(how="all")


def rolling_avg_pairwise_corr(ret_matrix: pd.DataFrame, window: int) -> pd.Series:
    """Rolling mean of the upper-triangle pairwise correlation matrix,
    at each bar, using the trailing `window` bars only (causal)."""
    cols = ret_matrix.columns
    n = len(cols)
    if n < 3:
        raise ValueError("Need at least 3 symbols for a meaningful pairwise-correlation index.")
    idx_pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]

    out = pd.Series(index=ret_matrix.index, dtype=float)
    values = ret_matrix.values
    for end in range(window, len(ret_matrix) + 1):
        window_vals = values[end - window:end]
        # Skip columns that are entirely NaN in this window (delisted/thin symbols)
        valid_cols = ~np.all(np.isnan(window_vals), axis=0)
        if valid_cols.sum() < 3:
            continue
        sub = window_vals[:, valid_cols]
        with np.errstate(invalid="ignore"):
            corr = pd.DataFrame(sub).corr().values
        iu = np.triu_indices_from(corr, k=1)
        vals = corr[iu]
        vals = vals[np.isfinite(vals)]
        if vals.size > 0:
            out.iloc[end - 1] = float(np.mean(vals))
    return out.dropna()


def main():
    p = argparse.ArgumentParser(description="CAMARF-native relational regime indicator (2026-07-14)")
    p.add_argument("--tf", default="1D")
    p.add_argument("--window", type=int, default=60)
    args = p.parse_args()

    symbols = _unique_symbols(_DEFAULT_PAIRS)
    print(f"Building return matrix for {len(symbols)} legs at {args.tf}: {symbols}")
    ret_matrix = build_return_matrix(symbols, args.tf)
    if ret_matrix.empty:
        print("No data loaded — nothing to compute.")
        return
    print(f"Return matrix: {ret_matrix.shape[0]} bars x {ret_matrix.shape[1]} symbols "
          f"({ret_matrix.index.min().date()} to {ret_matrix.index.max().date()})")

    index_series = rolling_avg_pairwise_corr(ret_matrix, args.window)
    print(f"\nRelational regime indicator: {len(index_series)} points, "
          f"mean={index_series.mean():.3f}, std={index_series.std():.3f}, "
          f"min={index_series.min():.3f}, max={index_series.max():.3f}")

    p95 = index_series.quantile(0.95)
    elevated = index_series[index_series >= p95]
    print(f"\nTop 5% (>= {p95:.3f}) elevated-correlation dates ({len(elevated)} bars):")
    # Report distinct episodes (consecutive elevated runs), not every bar
    elevated_dates = elevated.index
    episodes = []
    cur_start = elevated_dates[0]
    prev = elevated_dates[0]
    for d in elevated_dates[1:]:
        gap = (d - prev).days if args.tf in ("1D", "7D") else (d - prev).total_seconds() / 3600
        threshold = 5 if args.tf in ("1D", "7D") else 24
        if gap > threshold:
            episodes.append((cur_start, prev))
            cur_start = d
        prev = d
    episodes.append((cur_start, prev))
    for start, end in episodes[:20]:
        peak = index_series.loc[start:end].max()
        print(f"  {start.date()} to {end.date()}: peak={peak:.3f}")

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    safe_tf = DataStore._TF_SAFE.get(args.tf, args.tf.lower())
    out_path = os.path.join(out_dir, f"relational_regime_indicator_{safe_tf}.parquet")
    index_series.to_frame("avg_pairwise_corr").to_parquet(out_path)
    print(f"\nFull time series written to {out_path}")


if __name__ == "__main__":
    main()
