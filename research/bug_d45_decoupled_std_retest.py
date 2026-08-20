"""
research/bug_d45_decoupled_std_retest.py -- Ross's direct request (2026-08-13):
"the bug d45 is a single case and should be retested." BUG-D45
(Development.md) found that decoupling the z-score's std window (shorter,
more vol-responsive: OU_WINDOW_HALFLIFE_MULT_VOL=2x half-life) from its mean
window (longer: OU_WINDOW_HALFLIFE_MULT_MEAN=8x half-life) made things WORSE
on ONE pair, CRWD/DDOG (frac|z|>10 jumped to 12.3%) -- reverted to a single
shared window for both. That constant (OU_WINDOW_HALFLIFE_MULT_VOL) no
longer exists anywhere in the codebase; reconstructed here at its
documented value (2.0) purely for this retest, not re-added to production
config.

This script retests the SAME comparison (decoupled short-std z-score vs.
the current production single-shared-window z-score) across EVERY real
cached confirmed pair, not just one -- does BUG-D45's finding generalize,
or was CRWD/DDOG (a brand-new, ~4.7-day-history pair at the time) an edge
case that doesn't represent the broader universe?

Metric: BUG-D45's own diagnostic (frac|z|>10) for both versions, per pair,
plus the mean/std of the decoupled version's z-score (BUG-D45 reported
mean=-1.50, std=7.13 for CRWD/DDOG's decoupled version, vs. the reverted
fix's mean=-0.28, std=1.59) -- same numbers this project's own bug report
already used to judge "worse."
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from config import Config

_RESULTS_GLOB = os.path.join("output", "results", "*", "spread_series_*.parquet")
_OUT_PATH = os.path.join("output", "research", "bug_d45_decoupled_std_retest.parquet")

_OU_WINDOW_HALFLIFE_MULT_VOL = 2.0  # BUG-D45's own documented "tried and reverted" value


def rolling_zscore_decoupled(spread: pd.Series, mean_window: int, std_window: int) -> pd.Series:
    """Reconstructs BUG-D45's reverted design exactly: SAME formula as
    SpreadModel.rolling_zscore, but mean and std computed over DIFFERENT
    windows instead of the current shared one."""
    mu = spread.rolling(mean_window, min_periods=max(2, mean_window // 2)).mean()
    sd = spread.rolling(std_window, min_periods=max(2, std_window // 2)).std(ddof=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return (spread - mu) / sd


def compare_pair(path: str) -> dict:
    df = pd.read_parquet(path)
    if "z_rolling" not in df.columns or "half_life_rolling" not in df.columns or "spread" not in df.columns:
        return None
    hl = df["half_life_rolling"].bfill().ffill()
    if hl.isna().all():
        return None

    cfg = Config.ANALYSIS
    mean_window = (hl * cfg.OU_WINDOW_HALFLIFE_MULT_MEAN).clip(
        lower=cfg.OU_WINDOW_MIN_BARS, upper=cfg.OU_LOOKBACK_DAYS
    )
    std_window_decoupled = (hl * _OU_WINDOW_HALFLIFE_MULT_VOL).clip(
        lower=cfg.OU_WINDOW_MIN_BARS, upper=cfg.OU_LOOKBACK_DAYS
    )
    # Same simplification as the EWMA comparison script -- a per-bar-varying
    # window would need a materially more involved implementation than
    # pandas.rolling supports; using each window's median as a representative
    # single value, disclosed not hidden.
    mean_w = int(mean_window.median())
    std_w = int(std_window_decoupled.median())
    if mean_w < 2 or std_w < 2:
        return None

    z_decoupled = rolling_zscore_decoupled(df["spread"], mean_w, std_w)
    z_current = df["z_rolling"]

    valid = np.isfinite(z_current) & np.isfinite(z_decoupled)
    if valid.sum() < 30:
        return None

    zc = z_current[valid]
    zd = z_decoupled[valid]
    return {
        "path": os.path.basename(path),
        "n_bars": int(valid.sum()),
        "mean_window": mean_w,
        "std_window_decoupled": std_w,
        "frac_extreme_current": float((zc.abs() > 10).mean()),
        "frac_extreme_decoupled": float((zd.abs() > 10).mean()),
        "mean_z_current": float(zc.mean()),
        "std_z_current": float(zc.std()),
        "mean_z_decoupled": float(zd.mean()),
        "std_z_decoupled": float(zd.std()),
        "decoupled_worse": bool((zd.abs() > 10).mean() > (zc.abs() > 10).mean()),
    }


def main():
    files = sorted(glob.glob(_RESULTS_GLOB))
    print(f"Found {len(files)} real cached spread_series files")
    rows = []
    for f in files:
        try:
            row = compare_pair(f)
        except Exception as e:
            print(f"  {f}: FAILED ({e})")
            continue
        if row:
            rows.append(row)

    if not rows:
        print("No valid comparisons produced.")
        return

    out_df = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(_OUT_PATH), exist_ok=True)
    out_df.to_parquet(_OUT_PATH, index=False)
    print(f"\n{len(out_df)} pairs retested. Saved -> {_OUT_PATH}\n")
    n_worse = int(out_df["decoupled_worse"].sum())
    n_same_or_better = len(out_df) - n_worse
    print(f"Decoupled version WORSE (more frac|z|>10) than current: {n_worse}/{len(out_df)} "
          f"({100*n_worse/len(out_df):.1f}%)")
    print(f"Decoupled version SAME or BETTER: {n_same_or_better}/{len(out_df)} "
          f"({100*n_same_or_better/len(out_df):.1f}%)")
    print(f"\nMean frac|z|>10 -- current: {out_df['frac_extreme_current'].mean():.5f}, "
          f"decoupled: {out_df['frac_extreme_decoupled'].mean():.5f}")
    print(f"Mean std_z -- current: {out_df['std_z_current'].mean():.3f}, "
          f"decoupled: {out_df['std_z_decoupled'].mean():.3f}")
    print(out_df.sort_values("frac_extreme_decoupled", ascending=False).head(10).to_string(index=False))


if __name__ == "__main__":
    main()
