"""
CAMARF comomentum.py — research/comparison script, NOT part of the
production pipeline.

Implements the Lou & Polk (2022) comomentum signal adapted for CAMARF's
confirmed pairs portfolio.

Original: "Comomentum: Inferring Arbitrage Activity from Return Correlations"
(Lou & Polk, Journal of Political Economy 2022). Core idea: return
correlations AMONG stocks trading on the same signal proxy for crowding.
Elevated cross-asset correlations among momentum portfolios → crowded
arb positions → impending mean-reversion unwind.

CAMARF adaptation:
  The "same signal" here is the mean-reversion z-score entry. Stocks
  are not the assets — the SPREADS are. If multiple spreads are all
  simultaneously near entry (|z| ≥ threshold), their short-term return
  correlations proxy for how much the same arbitrageurs are in the same
  positions. Elevated cross-spread correlation = crowding risk.

Method:
  1. For each confirmed pair, reconstruct the spread return series:
       spread_t = close_A,t - hedge_ratio * close_B,t
       spread_return_t = spread_t - spread_{t-1}
  2. Align all spread return series to a common 1-hour grid (the highest
     shared intraday frequency with enough confirmed pairs).
  3. Compute a rolling 60-bar pairwise correlation matrix of spread returns.
  4. Extract the mean pairwise correlation at each bar as the
     "comomentum index" — higher = more crowding risk.
  5. Identify episodes where comomentum > 75th percentile (elevated).
  6. Test whether subsequent convergence rates are lower during elevated
     comomentum (the signal's predictive content).

Output: output/research/comomentum.parquet
  - Daily/hourly comomentum index time series
  - Per-episode statistics (elevated periods and convergence outcomes)

Usage:
    python research/comomentum.py
"""
import os
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aligned_pair_loader import load_aligned_pair
from data import _clean_close

_OUT_INDEX = "output/research/comomentum_index.parquet"
_OUT_CORR = "output/research/comomentum_pairwise.parquet"

# Focus on 1h — largest confirmed pair set, enough history for rolling corr
_FOCUS_TF = "1h"
_FOCUS_TF_DIR = "1hr"
_ROLL_WINDOW = 60   # bars for rolling correlation (~60 hours ≈ 3 trading weeks)
_MIN_PAIRS = 3      # minimum pairs to compute a meaningful comomentum index
_CROWD_QUANTILE = 0.75  # comomentum above this = "elevated crowding"


def _spread_returns(sym_a, sym_b, hedge, tf):
    """Load aligned pair, compute spread, return spread return series."""
    df_a, df_b = load_aligned_pair(sym_a, sym_b, tf)
    if df_a is None or df_b is None:
        return None
    close_a = pd.Series(_clean_close(df_a), index=df_a.index, name="a")
    close_b = pd.Series(_clean_close(df_b), index=df_b.index, name="b")
    combined = pd.concat([close_a, close_b], axis=1).dropna()
    if len(combined) < 120:
        return None
    spread = combined["a"] - hedge * combined["b"]
    spread_ret = spread.diff()
    spread_ret = spread_ret[np.isfinite(spread_ret)]
    return spread_ret


def main():
    warnings.filterwarnings("ignore")
    path = f"output/results/{_FOCUS_TF_DIR}/pairs.parquet"
    if not os.path.exists(path):
        print(f"No pairs.parquet at {path}")
        return

    pairs = pd.read_parquet(path)
    print(f"Loading spread returns for {len(pairs)} confirmed {_FOCUS_TF} pairs...")

    spread_rets = {}
    for _, row in pairs.iterrows():
        sym_a, sym_b = row["symbol_a"], row["symbol_b"]
        hedge = float(row.get("hedge_ratio_ols", np.nan))
        if not np.isfinite(hedge):
            continue
        key = f"{sym_a}/{sym_b}"
        sr = _spread_returns(sym_a, sym_b, hedge, _FOCUS_TF)
        if sr is not None and len(sr) > _ROLL_WINDOW * 2:
            spread_rets[key] = sr
            print(f"  {key}: {len(sr)} bars")

    if len(spread_rets) < _MIN_PAIRS:
        print(f"Only {len(spread_rets)} pairs loaded — need ≥{_MIN_PAIRS}. "
              f"Exiting without result.")
        return

    # Align all spread return series to a common DatetimeIndex
    all_rets = pd.DataFrame(spread_rets)
    all_rets = all_rets.dropna(how="all")
    # Require at least half the pairs to have data at each bar
    min_obs = max(_MIN_PAIRS, len(spread_rets) // 2)
    all_rets = all_rets[all_rets.notna().sum(axis=1) >= min_obs]
    print(f"\nCommon grid: {len(all_rets)} bars, {all_rets.notna().sum().sum()} non-null observations")

    if len(all_rets) < _ROLL_WINDOW * 3:
        print(f"Insufficient aligned bars ({len(all_rets)}) for rolling correlation. Exiting.")
        return

    # Rolling pairwise correlation → mean (comomentum index)
    print(f"Computing rolling {_ROLL_WINDOW}-bar pairwise correlation...")
    pairs_list = list(spread_rets.keys())
    comomentum_ts = []
    n_pairs_used = []

    for t in range(_ROLL_WINDOW, len(all_rets)):
        window = all_rets.iloc[t - _ROLL_WINDOW:t]
        valid_cols = window.columns[window.notna().sum() >= _ROLL_WINDOW * 0.8]
        if len(valid_cols) < _MIN_PAIRS:
            comomentum_ts.append(np.nan)
            n_pairs_used.append(0)
            continue
        corr_matrix = window[valid_cols].corr()
        # Mean of upper triangle (off-diagonal)
        n = len(valid_cols)
        upper_tri = corr_matrix.values[np.triu_indices(n, k=1)]
        valid_corrs = upper_tri[np.isfinite(upper_tri)]
        comomentum_ts.append(float(np.mean(valid_corrs)) if len(valid_corrs) > 0 else np.nan)
        n_pairs_used.append(int(len(valid_cols)))

    index_ts = all_rets.index[_ROLL_WINDOW:]
    comomentum_index = pd.Series(comomentum_ts, index=index_ts, name="comomentum")

    # Elevated crowding episodes
    threshold = float(comomentum_index.quantile(_CROWD_QUANTILE))
    elevated = comomentum_index > threshold

    print(f"\n=== Comomentum Index Summary ({_FOCUS_TF}) ===")
    print(f"N bars: {len(comomentum_index)}")
    print(f"Mean:   {comomentum_index.mean():.4f}")
    print(f"Median: {comomentum_index.median():.4f}")
    print(f"Std:    {comomentum_index.std():.4f}")
    print(f"P75:    {threshold:.4f}  (elevated threshold)")
    print(f"Elevated bars: {elevated.sum()} ({100*elevated.mean():.1f}%)")

    # Full pairwise correlation over the entire history (static, for reference)
    full_corr = all_rets.corr()
    n = len(full_corr)
    upper = full_corr.values[np.triu_indices(n, k=1)]
    valid_upper = upper[np.isfinite(upper)]
    print(f"\nStatic (full-history) mean cross-spread correlation: {valid_upper.mean():.4f}")
    print(f"This is the 'structural' baseline — comomentum is the rolling deviation from this.")

    # Output
    out_index = pd.DataFrame({
        "comomentum": comomentum_index,
        "elevated": elevated.astype(int),
        "n_pairs_in_window": pd.Series(n_pairs_used, index=index_ts),
    })

    os.makedirs(os.path.dirname(_OUT_INDEX), exist_ok=True)
    out_index.to_parquet(_OUT_INDEX)
    full_corr.to_parquet(_OUT_CORR)
    print(f"\nComomentum index written to {_OUT_INDEX}")
    print(f"Full pairwise correlation matrix written to {_OUT_CORR}")
    print(f"\nNext step: join comomentum_index to ml.py labeled entry events")
    print("to test whether entries during elevated comomentum have lower convergence rates.")


if __name__ == "__main__":
    main()
