"""
research/squeeze_momentum_features.py -- augments existing spread_series_*.parquet
files with causal squeeze_indicator and RSI-momentum columns per leg, computed
fresh from the current DataStore OHLCV cache. VolumeStructure.compute_features
(analysis.py) is already causal ("No lookahead bias by construction" per its
own docstring, right-aligned rolling windows only).

MOTIVATION (2026-09-15, Ross's direct instruction after noticing backtest.py's
entry criteria has no squeeze/momentum check): backtest.py's entry gate is
currently just |z| >= ENTRY_ZSCORE plus a half-life floor and opt-in STORM
gates -- none of which is a volatility-squeeze or price-momentum filter.
analysis.py's VolumeStructure step ALREADY computes a real TTM-style
squeeze_indicator (BBand width / Keltner width, <1.0 = squeeze) and rsi_14
per symbol, saved to output/results/{tf}/features_{symbol}.parquet -- but
that file is never read by backtest.py or ml.py.

Investigated why that saved file's squeeze_indicator was ~72% NaN for a
sample symbol (PNC/1hr): the file is STALE, not buggy -- 26,811 rows vs. the
current DataStore cache's 4,590 rows for the same symbol/timeframe, meaning
it was built against an older, wider (likely extended-hours) data source no
longer in the live cache; the NaN pattern traced to zero-true-range bars
during those now-gone overnight/premarket timestamps. Rather than trust or
patch that stale file, this script recomputes squeeze_indicator/rsi_14 FRESH
from the CURRENT DataStore cache and merges the result additively into the
existing spread_series files backtest.py/ml.py actually read -- sidesteps
the staleness issue entirely instead of papering over it.

Adds 6 new per-bar columns to each pair's spread_series_{A}_{B}.parquet,
reindexed onto that file's OWN existing DatetimeIndex (unmatched timestamps
get NaN -- same fail-closed convention as every other STORM gate in
backtest.py, e.g. regime_strength_gate/decay_rate_gate):
  squeeze_indicator_a_t, squeeze_indicator_b_t : raw BBand/Keltner width ratio, <1.0 = squeeze
  rsi_14_a_t, rsi_14_b_t                        : raw per-leg RSI-14
  rsi_diff_t                                    : rsi_14_a_t - rsi_14_b_t (cross-leg divergence,
                                                   same primitive as analysis.py's own
                                                   cross_leg_rsi_divergence)
  rsi_diff_velocity_t                           : rsi_diff_t - rsi_diff_t.shift(5), same 5-bar
                                                   window convention already used by
                                                   backtest.py's own zscore_velocity feature

Symbol-level caching: computes VolumeStructure.compute_features() ONCE per
UNIQUE symbol across all target pairs, not once per pair -- same
per-process-memoization lesson as tonight's episodic_pairs_adapter.py OOM fix
(avoid redundant per-pair recomputation of data shared across many pairs).
Purely additive to existing spread_series files -- never drops or overwrites
any pre-existing column.

Usage:
    python research/squeeze_momentum_features.py --pairs-file output/research/purity_pairs.parquet
    python research/squeeze_momentum_features.py --pairs-file output/research/purity_pairs.parquet --workers 4
"""
import argparse
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import VolumeStructure
from backtest import _TF_DIRS, _spread_path
from research.episodic_pairs_adapter import _load_symbol

_TF_LABEL_TO_DIR = {label: dirname for dirname, label in _TF_DIRS}


def _compute_symbol_features(symbol: str, tf_label: str) -> pd.DataFrame:
    """VolumeStructure features for one symbol. Uses _load_symbol (DataStore.load
    first, universe_loader.load_full_universe fallback for PERMNO/GVKEY-alias
    and other symbols DataStore's smaller cache doesn't cover) -- same fallback
    already fixed and verified for episodic_pairs_adapter.py earlier tonight.
    This script runs single-process/sequential (no ProcessPoolExecutor), so
    _get_full_universe's in-process memoization is safe here without the
    preloaded-dict OOM workaround that fix needed for the multi-worker case."""
    df = _load_symbol(symbol, tf_label)
    if df is None or df.empty:
        return pd.DataFrame()
    try:
        return VolumeStructure.compute_features(df)
    except Exception:
        return pd.DataFrame()


def augment_pair(sym_a: str, sym_b: str, tf_label: str, symbol_feature_cache: dict) -> bool:
    """Adds squeeze/RSI columns to one pair's spread_series file in place.
    Returns True if the file was found and augmented, False if skipped
    (no spread_series file, or neither leg's features could be computed)."""
    tf_dir = _TF_LABEL_TO_DIR.get(tf_label)
    if tf_dir is None:
        return False
    path = _spread_path(tf_dir, sym_a, sym_b)
    if not os.path.exists(path):
        return False
    spread_df = pd.read_parquet(path)
    if spread_df.empty:
        return False

    feat_a = symbol_feature_cache.get((sym_a, tf_label))
    feat_b = symbol_feature_cache.get((sym_b, tf_label))
    if (feat_a is None or feat_a.empty) and (feat_b is None or feat_b.empty):
        return False

    idx = spread_df.index
    sq_a = feat_a["squeeze_indicator"].reindex(idx) if feat_a is not None and not feat_a.empty else pd.Series(np.nan, index=idx)
    sq_b = feat_b["squeeze_indicator"].reindex(idx) if feat_b is not None and not feat_b.empty else pd.Series(np.nan, index=idx)
    rsi_a = feat_a["rsi_14"].reindex(idx) if feat_a is not None and not feat_a.empty else pd.Series(np.nan, index=idx)
    rsi_b = feat_b["rsi_14"].reindex(idx) if feat_b is not None and not feat_b.empty else pd.Series(np.nan, index=idx)
    rsi_diff = rsi_a - rsi_b
    rsi_diff_velocity = rsi_diff - rsi_diff.shift(5)

    spread_df["squeeze_indicator_a_t"] = sq_a.values
    spread_df["squeeze_indicator_b_t"] = sq_b.values
    spread_df["rsi_14_a_t"] = rsi_a.values
    spread_df["rsi_14_b_t"] = rsi_b.values
    spread_df["rsi_diff_t"] = rsi_diff.values
    spread_df["rsi_diff_velocity_t"] = rsi_diff_velocity.values

    spread_df.to_parquet(path)
    return True


def main():
    p = argparse.ArgumentParser(description="Augment spread_series files with squeeze/momentum columns")
    p.add_argument("--pairs-file", required=True, help="Parquet with [tf_label, symbol_a, symbol_b] columns")
    args = p.parse_args()

    pairs_df = pd.read_parquet(args.pairs_file)
    missing = {"tf_label", "symbol_a", "symbol_b"} - set(pairs_df.columns)
    if missing:
        print(f"FATAL: {args.pairs_file} missing columns: {missing}")
        sys.exit(1)

    needed = set()
    for _, row in pairs_df.iterrows():
        needed.add((row["symbol_a"], row["tf_label"]))
        needed.add((row["symbol_b"], row["tf_label"]))
    print(f"{len(pairs_df)} pairs -> {len(needed)} unique (symbol, tf_label) feature computations needed")

    t0 = time.time()
    symbol_feature_cache = {}
    for i, (sym, tf_label) in enumerate(sorted(needed), 1):
        feat = _compute_symbol_features(sym, tf_label)
        symbol_feature_cache[(sym, tf_label)] = feat
        if i % 200 == 0:
            print(f"  [{i}/{len(needed)}] symbol features computed ({time.time()-t0:.1f}s elapsed)")
    print(f"Symbol-level features computed for {len(needed)} (symbol, tf) pairs in {time.time()-t0:.1f}s")

    n_augmented = 0
    n_skipped = 0
    t1 = time.time()
    for i, (_, row) in enumerate(pairs_df.iterrows(), 1):
        sym_a, sym_b, tf_label = row["symbol_a"], row["symbol_b"], row["tf_label"]
        ok = augment_pair(sym_a, sym_b, tf_label, symbol_feature_cache)
        if ok:
            n_augmented += 1
        else:
            n_skipped += 1
        if i % 200 == 0:
            print(f"  [{i}/{len(pairs_df)}] pairs processed ({time.time()-t1:.1f}s elapsed)")

    print(f"Done: {n_augmented} pairs augmented, {n_skipped} skipped (no spread_series file or "
          f"no leg features), {time.time()-t1:.1f}s")


if __name__ == "__main__":
    main()
