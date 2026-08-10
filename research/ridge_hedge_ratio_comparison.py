"""
research/ridge_hedge_ratio_comparison.py -- comparison arm, NOT part of the
production pipeline.

Ross's question: does ridge (L2-regularized) regression improve hedge-ratio
estimation over the existing production methods (analysis.py::
HedgeRatioEstimator -- OLS, TLS, Kalman)? Motivated directly by this
session's intraday work: shorter, noisier rolling windows (756-1512 bars at
1h, vs. 252 at daily) are exactly the regime where an unregularized OLS
slope is most sensitive to a handful of noisy observations, and ridge's
whole point is trading a little bias for less variance in exactly that
regime.

RIDGE HERE IS THE NATURAL REGULARIZED EXTENSION OF THE EXISTING OLS
ESTIMATOR, not a new estimator built from scratch: `ridge_rolling` below is
a byte-for-byte structural copy of `HedgeRatioEstimator.ols_rolling`
(analysis.py:2086-2131) -- same rolling window, same causal
no-lookahead convention (bar t only ever uses log_a[t-window+1:t+1]) --
with one line changed: the OLS normal equation's denominator
`var(B)` becomes `var(B) + lambda`. In the univariate (single-regressor)
case, ridge regression reduces to exactly this: beta_ridge =
cov(A,B) / (var(B) + lambda), a direct, well-known closed-form shrinkage
of the OLS beta toward zero.

LAMBDA IS A RELATIVE, NOT ABSOLUTE, PENALTY -- a real design choice, stated
here rather than silently assumed. `var(B)` differs by orders of magnitude
across pairs (a $500 stock's log-price variance vs. a $20 stock's), so a
single fixed absolute lambda would regularize different pairs by wildly
different effective strengths. Instead, lambda is expressed as a FRACTION
of that same window's own var(B) (`lambda = k * var(B)`), so `k` has a
consistent, comparable meaning across every pair and window -- directly
following this project's "test an actual grid, don't guess a hardcoded
value" discipline (the same one behind Step 1/Finding #22's window-sizing
test and Finding #23's duration/degree test) rather than picking one k.

EVALUATION: for each confirmed pair, at each k in the grid, compute the
resulting spread's stationarity (ADF p-value, statsmodels.tsa.stattools.
adfuller, same convention research/adf_confirmatory_tier.py already
established and cross-checked against PO) using the SAME real spread OLS
already produces vs. ridge's shrunk version. A LOWER ADF p-value at a given
k, relative to k=0 (pure OLS), is evidence ridge produces a more stationary
-- and so more mean-reversion-tradeable -- spread on that pair/window.

Synthetic verification FIRST: debug/_verify_ridge_hedge_ratio_comparison.py
-- run that before trusting this script's real-data output.

Usage:
    python research/ridge_hedge_ratio_comparison.py
    python research/ridge_hedge_ratio_comparison.py --tf 1h
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import _clean_close
from research.aligned_pair_loader import load_aligned_pair

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_ROOT, "output", "research")
_RESULTS_DIR = os.path.join(_ROOT, "output", "results")

_K_GRID = [0.0, 0.01, 0.05, 0.10, 0.25, 0.50]  # k=0.0 IS plain OLS -- the baseline row, not a
                                                # separate special case, so every k is scored by
                                                # the exact same code path.
_DEFAULT_WINDOW = 252


def ridge_rolling(log_a: np.ndarray, log_b: np.ndarray, window: int, k: float):
    """Structural copy of HedgeRatioEstimator.ols_rolling (analysis.py:2086),
    with var(B) replaced by var(B) + k*var(B) = var(B)*(1+k) in the
    denominator -- ridge shrinkage expressed as a fraction of that same
    window's own var(B), not an absolute lambda (see module docstring).
    k=0.0 reduces exactly to ols_rolling's own output -- verified directly
    in debug/_verify_ridge_hedge_ratio_comparison.py, not just claimed.
    Returns (rolling_series, full_sample_point_estimate), same shape as
    ols_rolling."""
    n = log_a.size
    out = np.full(n, np.nan, dtype=float)
    if n < window:
        mask = np.isfinite(log_a) & np.isfinite(log_b)
        if np.sum(mask) < 10:
            return out, np.nan
        a = log_a[mask] - np.nanmean(log_a[mask])
        b = log_b[mask] - np.nanmean(log_b[mask])
        var_b = np.dot(b, b)
        beta_full = float(np.dot(a, b) / (var_b * (1.0 + k))) if var_b > 0 else np.nan
        return out, beta_full

    for t in range(window - 1, n):
        a_w = log_a[t - window + 1 : t + 1]
        b_w = log_b[t - window + 1 : t + 1]
        mask = np.isfinite(a_w) & np.isfinite(b_w)
        if np.sum(mask) < window // 2:
            continue
        a = a_w[mask] - a_w[mask].mean()
        b = b_w[mask] - b_w[mask].mean()
        var_b = np.dot(b, b)
        if var_b > 0:
            out[t] = np.dot(a, b) / (var_b * (1.0 + k))

    mask = np.isfinite(log_a) & np.isfinite(log_b)
    a = log_a[mask] - log_a[mask].mean()
    b = log_b[mask] - log_b[mask].mean()
    var_b = np.dot(b, b)
    beta_full = float(np.dot(a, b) / (var_b * (1.0 + k))) if var_b > 0 else np.nan

    return out, beta_full


def spread_adf_pvalue(log_a: np.ndarray, log_b: np.ndarray, beta: float) -> float:
    """ADF p-value on the spread log_a - beta*log_b, same convention as
    research/adf_confirmatory_tier.py -- AIC lag selection, gap-masked
    finite values only."""
    mask = np.isfinite(log_a) & np.isfinite(log_b)
    if mask.sum() < 30 or not np.isfinite(beta):
        return np.nan
    spread = log_a[mask] - beta * log_b[mask]
    try:
        _t, pval, *_ = adfuller(spread, autolag="AIC")
        return float(pval)
    except Exception:
        return np.nan


def evaluate_pair(sym_a: str, sym_b: str, tf_label: str, window: int = _DEFAULT_WINDOW):
    """Returns a list of dicts, one per k in _K_GRID, with the resulting
    ADF p-value using that k's full-sample ridge/OLS point estimate."""
    df_a, df_b = load_aligned_pair(sym_a, sym_b, tf_label)
    if df_a is None or df_b is None:
        return []
    # load_aligned_pair -> DataAligner.align_universe with its default
    # drop_data_gap_rows=False -- correct for the main pipeline's cross-
    # SYMBOL dense-matrix construction, but does NOT guarantee df_a/df_b
    # come back the same length for a single-pair consumer like this one
    # (confirmed directly: IQV/Q@1D came back as 252 vs 161 rows, IQV
    # having a shorter cached history -- "recently listed", already noted
    # elsewhere in this project). research/coint_frac_window_grid.py's own
    # build_pair_data has the same requirement and handles it with an
    # explicit inner join before treating the two series as parallel
    # arrays -- mirrored here rather than assuming equal length.
    joined = pd.concat(
        [pd.Series(_clean_close(df_a), index=df_a.index),
         pd.Series(_clean_close(df_b), index=df_b.index)],
        axis=1, join="inner"
    )
    close_a, close_b = joined.iloc[:, 0].to_numpy(), joined.iloc[:, 1].to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        log_a, log_b = np.log(close_a), np.log(close_b)

    rows = []
    for k in _K_GRID:
        _series, beta = ridge_rolling(log_a, log_b, window, k)
        adf_p = spread_adf_pvalue(log_a, log_b, beta)
        rows.append({
            "symbol_a": sym_a, "symbol_b": sym_b, "tf_label": tf_label,
            "k": k, "hedge_ratio": beta, "adf_pvalue": adf_p,
        })
    return rows


def load_confirmed_pairs(tf_label: str):
    tf_dir_map = {
        "1m": "1min", "2m": "2min", "3m": "3min", "5m": "5min", "15m": "15min",
        "30m": "30min", "1h": "1hr", "4h": "4hr", "1D": "1day", "7D": "7day",
        "1M": "1mo", "3M": "3mo", "6M": "6mo",
    }
    path = os.path.join(_RESULTS_DIR, tf_dir_map.get(tf_label, tf_label), "pairs.parquet")
    if not os.path.exists(path):
        return []
    df = pd.read_parquet(path)
    return list(zip(df["symbol_a"], df["symbol_b"]))


def main():
    p = argparse.ArgumentParser(description="Ridge vs OLS/TLS/Kalman hedge-ratio comparison")
    p.add_argument("--tf", nargs="+", default=["1D", "3m", "4h"],
                    help="Test across all 3 current confirmed pairs' own timeframes by default.")
    args = p.parse_args()

    all_rows = []
    for tf_label in args.tf:
        pairs = load_confirmed_pairs(tf_label)
        print(f"[{tf_label}] {len(pairs)} confirmed pairs")
        for sym_a, sym_b in pairs:
            rows = evaluate_pair(sym_a, sym_b, tf_label)
            all_rows.extend(rows)
            for r in rows:
                print(f"  {sym_a}/{sym_b}@{tf_label} k={r['k']:.2f}: "
                      f"hedge_ratio={r['hedge_ratio']} adf_p={r['adf_pvalue']}")

    if not all_rows:
        print("No confirmed pairs found to evaluate.")
        return pd.DataFrame()

    result_df = pd.DataFrame(all_rows)
    baseline = result_df[result_df["k"] == 0.0].set_index(["symbol_a", "symbol_b", "tf_label"])["adf_pvalue"]
    result_df["baseline_adf_pvalue"] = result_df.apply(
        lambda r: baseline.get((r["symbol_a"], r["symbol_b"], r["tf_label"]), np.nan), axis=1
    )
    result_df["adf_pvalue_improved_vs_ols"] = result_df["adf_pvalue"] < result_df["baseline_adf_pvalue"]

    print(f"\n{'='*70}\nSUMMARY -- fraction of (pair, k) rows with LOWER ADF p-value than plain OLS (k=0)\n{'='*70}")
    for k in _K_GRID:
        sub = result_df[result_df["k"] == k]
        n_improved = sub["adf_pvalue_improved_vs_ols"].sum()
        print(f"  k={k:.2f}: {n_improved}/{len(sub)} pairs improved vs. OLS")

    os.makedirs(_OUT_DIR, exist_ok=True)
    out_path = os.path.join(_OUT_DIR, "ridge_hedge_ratio_comparison.parquet")
    result_df.to_parquet(out_path)
    print(f"\nWrote {out_path}")
    return result_df


if __name__ == "__main__":
    main()
