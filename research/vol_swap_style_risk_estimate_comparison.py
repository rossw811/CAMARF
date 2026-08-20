"""
research/vol_swap_style_risk_estimate_comparison.py -- comparison arm testing
a vol-swap-style (zero-mean, return-based) volatility estimator against
portfolio_sim.py's current causal_rolling_std_at_entry, inspired by
gs_quant.timeseries.econometrics.vol_swap_volatility (2026-08-13, Ross:
"let's implement them for comparison first").

REAL DESIGN DIFFERENCE, stated explicitly (checked before building, not
discovered after): portfolio_sim.py's current sigma is the std of the
SPREAD LEVEL within a rolling window (df["spread"].rolling(window).std()) --
"how wide is this spread's typical range right now." A vol-swap-style
estimator is fundamentally different: it's the zero-mean realized volatility
of the spread's CHANGES (sqrt(mean(diff^2)) over a window, no mean
subtraction -- the standard variance-swap replication convention, which
assumes period-over-period drift is negligible relative to variance).
"How wide is the typical range" and "how fast does it move" are related but
NOT the same quantity -- this comparison is honest about testing a
genuinely different volatility CONCEPT, not just a different window/decay
scheme for the same one (unlike the EWMA z-score comparison, which kept the
same "dispersion of the level" concept and only changed the weighting).

Directly motivated by this session's own real finding (Finding #25/#26,
docs/FINDINGS.md): Kelly/flat_2pct sizing is currently unusable on the
Purity universe because risk_per_share estimates are too small relative to
account size, causing the vast majority of trades to be skipped via the
0.05 size-floor. A materially different volatility estimate here could
change that dynamic -- this comparison measures whether it does, not
assumed in advance.

Method: for every real cached spread_series file, computes BOTH sigma
estimates (current level-std vs. vol-swap-style diff-based realized vol,
same rolling window for a fair comparison) at every bar, converts each to
an implied "risk_per_share" via the SAME z_distance_to_stop * sigma formula
stop_distance_dollars_per_share already uses, and compares the resulting
distributions -- does the vol-swap estimator produce systematically larger/
smaller risk_per_share values, which would directly change how many trades
clear the Kelly-sizing floor.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from config import Config

_RESULTS_GLOB = os.path.join("output", "results", "*", "spread_series_*.parquet")
_OUT_PATH = os.path.join("output", "research", "vol_swap_style_risk_estimate_comparison.parquet")

STOP_ZSCORE = Config.BACKTEST.STOP_ZSCORE


def level_std(spread: pd.Series, window: int) -> pd.Series:
    """Current convention: std of the spread LEVEL within a rolling window
    (matches portfolio_sim.py::causal_rolling_std_at_entry exactly)."""
    return spread.rolling(window, min_periods=max(2, window // 2)).std(ddof=1)


def vol_swap_style_diff_vol(spread: pd.Series, window: int) -> pd.Series:
    """Vol-swap-style: zero-mean realized volatility of spread CHANGES
    (sqrt(mean(diff^2)) over the window, no mean subtraction -- the
    standard variance-swap replication convention). Causal (pandas
    .rolling() on a causal diff series)."""
    diffs = spread.diff()
    mean_sq = (diffs ** 2).rolling(window, min_periods=max(2, window // 2)).mean()
    return np.sqrt(mean_sq)


def compare_pair(path: str, window: int = 60) -> dict:
    df = pd.read_parquet(path)
    if "spread" not in df.columns or "z_rolling" not in df.columns:
        return None
    spread = df["spread"]
    sigma_level = level_std(spread, window)
    sigma_diff = vol_swap_style_diff_vol(spread, window)
    z = df["z_rolling"]

    z_dist_to_stop = (STOP_ZSCORE - z.abs()).clip(lower=0)
    risk_level = z_dist_to_stop * sigma_level
    risk_diff = z_dist_to_stop * sigma_diff

    valid = np.isfinite(risk_level) & np.isfinite(risk_diff) & (z_dist_to_stop > 0)
    if valid.sum() < 30:
        return None

    rl = risk_level[valid]
    rd = risk_diff[valid]
    return {
        "path": os.path.basename(path),
        "n_bars": int(valid.sum()),
        "median_risk_per_share_level": float(rl.median()),
        "median_risk_per_share_vol_swap": float(rd.median()),
        "ratio_vol_swap_over_level": float(rd.median() / rl.median()) if rl.median() > 0 else float("nan"),
        "corr_level_vs_vol_swap": float(np.corrcoef(rl, rd)[0, 1]),
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
    print(f"\n{len(out_df)} pairs compared. Saved -> {_OUT_PATH}\n")
    print(f"Median ratio (vol-swap risk_per_share / current level-std risk_per_share): "
          f"{out_df['ratio_vol_swap_over_level'].median():.4f}")
    print(f"Mean correlation between the two risk_per_share estimates: "
          f"{out_df['corr_level_vs_vol_swap'].mean():.4f}")
    print(out_df.describe().to_string())


if __name__ == "__main__":
    main()
