"""
_measure_bug_d61_cutoff_gap.py — BUG-D61 follow-up instrumentation (2026-07-12)

Measures whether distance.py's single global calendar-date `formation_end`
(sampled from just the first 3 confirmed pairs' spread files, per-TF) lands
on the same calendar date as each individual confirmed pair's own bar-count
holdout cutoff (backtest.py's `holdout_only` logic: cutoff on the
NaN/warm-up-filtered df, not the raw spread file).

This does NOT reimplement backtest.py's cutoff logic — it imports and reuses
BacktestEngine's exact filtering (dropna on z_rolling/spread, then
z_rolling != 0) before taking the same `int(len(df) * (1 - HOLDOUT_PCT))`
cutoff, so the measured date is the literal date BacktestEngine would use for
holdout_only=True on this pair.

Usage: python debug/_measure_bug_d61_cutoff_gap.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from config import Config

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RESULTS_DIR = os.path.join(_ROOT, "output", "results")
_STATS_DIR = os.path.join(_ROOT, "output", "stats")

HOLDOUT_PCT = Config.BACKTEST.HOLDOUT_PCT
_FORMATION_FRAC = 1.0 - 0.20  # distance.py's current constant


def per_pair_cutoff_date(symbol_a: str, symbol_b: str, tf_dir: str):
    """Reproduces backtest.py BacktestEngine.run()'s holdout_only cutoff exactly."""
    spread_path = os.path.join(
        _RESULTS_DIR, tf_dir, f"spread_series_{symbol_a}_{symbol_b}.parquet"
    )
    if not os.path.exists(spread_path):
        return None
    spread_df = pd.read_parquet(spread_path)
    df = spread_df.dropna(subset=["z_rolling", "spread"]).copy()
    df = df[df["z_rolling"] != 0.0]
    if len(df) < 60:
        return None
    cutoff = int(len(df) * (1 - HOLDOUT_PCT))
    if cutoff >= len(df):
        return None
    return pd.Timestamp(df.index[cutoff])


def distance_global_formation_end(tf_pairs: pd.DataFrame, tf_dir: str) -> pd.Timestamp:
    """Reproduces distance.py main()'s formation_end computation exactly (head(3) sample)."""
    sample_spreads = []
    for _, row in tf_pairs.head(3).iterrows():
        sp = os.path.join(
            _RESULTS_DIR, tf_dir,
            f"spread_series_{row['symbol_a']}_{row['symbol_b']}.parquet",
        )
        if os.path.exists(sp):
            sample_spreads.append(pd.read_parquet(sp))
    all_idx = pd.concat([s.index.to_frame() for s in sample_spreads], ignore_index=True)
    all_idx = pd.to_datetime(all_idx.iloc[:, 0])
    full_start = all_idx.min()
    full_end = all_idx.max()
    return full_start + (full_end - full_start) * _FORMATION_FRAC


def distance_all_pairs_formation_end(tf_pairs: pd.DataFrame, tf_dir: str) -> pd.Timestamp:
    """Same computation, but sampling ALL confirmed pairs' spread files, not just the first 3."""
    all_spreads = []
    for _, row in tf_pairs.iterrows():
        sp = os.path.join(
            _RESULTS_DIR, tf_dir,
            f"spread_series_{row['symbol_a']}_{row['symbol_b']}.parquet",
        )
        if os.path.exists(sp):
            all_spreads.append(pd.read_parquet(sp))
    if not all_spreads:
        return None
    all_idx = pd.concat([s.index.to_frame() for s in all_spreads], ignore_index=True)
    all_idx = pd.to_datetime(all_idx.iloc[:, 0])
    full_start = all_idx.min()
    full_end = all_idx.max()
    return full_start + (full_end - full_start) * _FORMATION_FRAC


def main():
    tiers_path = os.path.join(_STATS_DIR, "cointegration_tiers.parquet")
    tiers = pd.read_parquet(tiers_path)
    print(f"Loaded {len(tiers)} confirmed pairs total across all timeframes")

    for tf_label, tf_dir in [("1h", "1hr")]:
        tf_pairs = tiers[tiers["tf_label"] == tf_label].copy()
        if len(tf_pairs) == 0:
            print(f"No confirmed pairs for {tf_label}")
            continue

        head3_formation_end = distance_global_formation_end(tf_pairs, tf_dir)
        all_formation_end = distance_all_pairs_formation_end(tf_pairs, tf_dir)
        print(f"\n=== {tf_label}: {len(tf_pairs)} confirmed pairs ===")
        print(f"distance.py's CURRENT global formation_end (head(3) sample): {head3_formation_end.date()}")
        print(f"formation_end if sampled from ALL {len(tf_pairs)} pairs instead: {all_formation_end.date()}")
        print(f"head(3)-vs-all sampling gap: {abs((head3_formation_end - all_formation_end).days)} days")

        gaps = []
        rows = []
        for _, row in tf_pairs.iterrows():
            a, b = row["symbol_a"], row["symbol_b"]
            pair_cutoff = per_pair_cutoff_date(a, b, tf_dir)
            if pair_cutoff is None:
                print(f"  {a}/{b}: no spread file or too few bars — skipped")
                continue
            gap_days = (pair_cutoff - head3_formation_end).days
            gaps.append(gap_days)
            rows.append((a, b, pair_cutoff.date(), gap_days))

        print(f"\n{len(rows)}/{len(tf_pairs)} pairs measured.")
        print(f"{'pair':<28} {'own_cutoff_date':<16} {'gap_vs_global_days':>18}")
        for a, b, d, g in sorted(rows, key=lambda r: -abs(r[3])):
            print(f"{a+'/'+b:<28} {str(d):<16} {g:>18d}")

        gaps_abs = [abs(g) for g in gaps]
        print(f"\nGAP SUMMARY (per-pair own cutoff date vs. distance.py's current global formation_end):")
        print(f"  max abs gap:    {max(gaps_abs)} days")
        print(f"  median abs gap: {sorted(gaps_abs)[len(gaps_abs)//2]} days")
        print(f"  mean abs gap:   {sum(gaps_abs)/len(gaps_abs):.1f} days")
        n_material = sum(1 for g in gaps_abs if g > 14)
        print(f"  pairs with >14 day gap: {n_material}/{len(gaps_abs)}")


if __name__ == "__main__":
    main()
