"""
CAMARF kalman_slope_intercept.py — comparison/diagnostic method, NOT part
of the production pipeline.

A real, previously-flagged divergence from Ernest Chan's reference Kalman-
filter pairs-trading implementation (Chan, *Algorithmic Trading*, 2013):
CAMARF's production `HedgeRatioEstimator.kalman()` (analysis.py) tracks a
SINGLE state — slope only, observation model `a_t = beta_t*b_t + v_t`,
literally forcing the regression through the origin — while Chan's own
formulation tracks TWO states, slope AND intercept, `a_t = beta_t*b_t +
alpha_t + v_t`.

This matters for a reason beyond "Chan does it differently": CAMARF's OWN
other two hedge-ratio estimators already effectively include an intercept.
`HedgeRatioEstimator.ols_rolling()` and `.tls()` both DEMEAN both series
before regressing/SVD-ing — mathematically equivalent to fitting an
intercept — confirmed directly by reading their source (both compute
`a = log_a[mask] - log_a[mask].mean()` before anything else). Only the
Kalman estimator omits it. This is an internal inconsistency across
CAMARF's own three hedge-ratio methods, not just a stylistic choice someone
else made differently.

Deliberately isolates ONE variable at a time, not two: this module keeps
CAMARF's OWN existing noise-calibration philosophy (Q, R estimated once
from a calibration window, then frozen — the no-lookahead discipline
already in production) for BOTH the origin-only and slope+intercept
filters, varying only whether the intercept state exists. Chan's own
separate convention (a fixed, never-data-derived `delta` hyperparameter
for process noise) is a second, independent axis of divergence, not
conflated with this comparison — flagged for a possible separate build,
not tested here.

Method: standard 2-state Kalman filter, state x_t=[beta_t, alpha_t]',
transition F=I (both a random walk), observation H_t=[b_t, 1] so that
y_t = H_t @ x_t + v_t. Calibrated on the same first `calib_bars` window
CAMARF's existing kalman() uses, via OLS WITH an intercept (not without)
so R reflects the residual variance under the correctly-specified model.

Read-only. Excludes DATA_GAP-flagged padding on both legs.

Usage:
    python research/kalman_slope_intercept.py
"""
import os
import sys

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # for aligned_pair_loader

from analysis import HedgeRatioEstimator

from aligned_pair_loader import (
    TF_DIRS as _TF_DIRS,
    DIR_TO_LABEL as _DIR_TO_LABEL,
    resolve_tf_results_dir as _resolve_tf_results_dir,
)


def kalman_slope_intercept(log_a, log_b, calib_bars=252):
    """
    Returns (beta_series, alpha_series, mean_beta, mean_alpha) — the direct
    2-state analog of HedgeRatioEstimator.kalman()'s (beta_series, mean_beta).
    """
    n = log_a.size
    beta = np.full(n, np.nan)
    alpha = np.full(n, np.nan)
    if n < calib_bars + 10:
        return beta, alpha, np.nan, np.nan

    log_a_calib = log_a[:calib_bars]
    log_b_calib = log_b[:calib_bars]
    mask = np.isfinite(log_a_calib) & np.isfinite(log_b_calib)
    if np.sum(mask) < 30:
        return beta, alpha, np.nan, np.nan

    a0 = log_a_calib[mask]
    b0 = log_b_calib[mask]
    # OLS WITH intercept for calibration (unlike production kalman(), which
    # calibrates beta0 via a through-the-origin regression) — this is the
    # correctly-specified calibration for the model actually being run here.
    X0 = np.column_stack([np.ones_like(b0), b0])
    coef, _r, _rk, _sv = np.linalg.lstsq(X0, a0, rcond=None)
    alpha0, beta0 = float(coef[0]), float(coef[1])
    residuals = a0 - alpha0 - beta0 * b0
    R = float(np.var(residuals))
    if R <= 0:
        R = 1e-8
    Q = np.diag([max(R * 1e-5, 1e-10), max(R * 1e-5, 1e-10)])  # [q_beta, q_alpha]

    x_prev = np.array([beta0, alpha0])
    P_prev = np.eye(2)
    for t in range(n):
        if not (np.isfinite(log_a[t]) and np.isfinite(log_b[t])):
            beta[t], alpha[t] = x_prev
            continue
        x_pred = x_prev
        P_pred = P_prev + Q
        H = np.array([log_b[t], 1.0])
        S = H @ P_pred @ H + R
        if S <= 0 or not np.isfinite(S):
            beta[t], alpha[t] = x_pred
            P_prev, x_prev = P_pred, x_pred
            continue
        K = P_pred @ H / S
        y_t = log_a[t]
        x_t = x_pred + K * (y_t - H @ x_pred)
        P_t = (np.eye(2) - np.outer(K, H)) @ P_pred
        beta[t], alpha[t] = x_t
        x_prev, P_prev = x_t, P_t

    warmup = min(calib_bars // 2, n // 4)
    mean_beta = float(np.nanmean(beta[warmup:])) if n > warmup else float(np.nanmean(beta))
    mean_alpha = float(np.nanmean(alpha[warmup:])) if n > warmup else float(np.nanmean(alpha))
    return beta, alpha, mean_beta, mean_alpha


def _adf_pvalue(spread):
    spread = spread[np.isfinite(spread)]
    if spread.size < 30:
        return np.nan
    try:
        return float(adfuller(spread, autolag="aic")[1])
    except Exception:
        return np.nan


def main():
    rows = []
    for tf_dir in _TF_DIRS:
        results_dir, is_stale = _resolve_tf_results_dir(tf_dir)
        pairs_path = os.path.join(results_dir, "pairs.parquet")
        if not os.path.exists(pairs_path):
            continue
        if is_stale:
            print(f"NOTE {tf_dir}: using archived {results_dir}")
        tf_label = _DIR_TO_LABEL[tf_dir]
        pairs_df = pd.read_parquet(pairs_path)
        for _, row in pairs_df.iterrows():
            sym_a, sym_b = row["symbol_a"], row["symbol_b"]
            series_path = os.path.join(results_dir, f"spread_series_{sym_a}_{sym_b}.parquet")
            if not os.path.exists(series_path):
                continue
            # BUG FIX (found by code review, 2026-07-05): this previously
            # reloaded raw log-prices via bare DataStore.load() and masked
            # only np.isfinite — data.py's raw per-symbol cache is
            # unconditionally forward-filled at fetch time with NO gap_flag
            # column at all, so that mask cannot catch already-padded bars.
            # This is the identical calendar-padding failure mode already
            # caught and fixed in threshold_cointegration.py/
            # variance_ratio_test.py earlier this same session — missed here
            # on the first pass. Fixed by using aligned_pair_loader (the
            # project's own existing shared utility for exactly this) to get
            # both legs through the same DataAligner path production uses,
            # WITH a real gap_flag column, then masking DATA_GAP on both legs
            # before computing anything — spread_series's own gap_flag_a/b
            # columns (read below) are reused directly as the mask source
            # rather than recomputed, since they already reflect this exact
            # pair/timeframe's real alignment.
            df = pd.read_parquet(series_path)
            real_mask = (df["gap_flag_a"] != 4) & (df["gap_flag_b"] != 4)
            df = df.loc[real_mask]

            from aligned_pair_loader import load_aligned_pair
            df_a, df_b = load_aligned_pair(sym_a, sym_b, tf_label)
            if df_a is None or df_b is None:
                continue
            gap_flag_a = df_a.get("gap_flag")
            gap_flag_b = df_b.get("gap_flag")
            if gap_flag_a is not None and gap_flag_b is not None:
                real_bars = (gap_flag_a.to_numpy() != 4) & (gap_flag_b.to_numpy() != 4)
            else:
                real_bars = np.ones(len(df_a), dtype=bool)
            log_a_full = np.log(df_a["close"].to_numpy(dtype=float))
            log_b_full = np.log(df_b["close"].to_numpy(dtype=float))
            finite = np.isfinite(log_a_full) & np.isfinite(log_b_full) & real_bars
            log_a, log_b = log_a_full[finite], log_b_full[finite]
            if log_a.size < 300:
                continue

            beta_origin, _mean_beta_origin = HedgeRatioEstimator.kalman(log_a, log_b)
            beta_si, alpha_si, mean_beta_si, mean_alpha_si = kalman_slope_intercept(log_a, log_b)

            spread_origin = log_a - beta_origin * log_b
            spread_si = log_a - beta_si * log_b - alpha_si

            p_origin = _adf_pvalue(spread_origin)
            p_si = _adf_pvalue(spread_si)
            row_out = {
                "symbol_a": sym_a, "symbol_b": sym_b, "tf_label": tf_label,
                "mean_alpha": mean_alpha_si, "std_spread_origin": float(np.nanstd(spread_origin)),
                "std_spread_si": float(np.nanstd(spread_si)),
                "adf_p_origin": p_origin, "adf_p_si": p_si,
            }
            rows.append(row_out)
            print(f"{sym_a}/{sym_b}@{tf_label}: mean_alpha={mean_alpha_si:.4f} "
                  f"std(spread) origin={row_out['std_spread_origin']:.4f} "
                  f"vs slope+intercept={row_out['std_spread_si']:.4f} "
                  f"ADF-p origin={p_origin:.4f} vs si={p_si:.4f}")

    out_df = pd.DataFrame(rows)
    os.makedirs("output/research", exist_ok=True)
    out_df.to_parquet("output/research/kalman_slope_intercept.parquet")
    if len(out_df):
        n_alpha_material = int((out_df["mean_alpha"].abs() > 0.05).sum())
        n_si_better_adf = int((out_df["adf_p_si"] < out_df["adf_p_origin"]).sum())
        print(f"\nWrote output/research/kalman_slope_intercept.parquet: {len(out_df)} pairs, "
              f"{n_alpha_material}/{len(out_df)} with |mean_alpha|>0.05 (material intercept), "
              f"{n_si_better_adf}/{len(out_df)} pairs where slope+intercept gives a lower "
              f"(more stationary) ADF p-value than origin-only")


if __name__ == "__main__":
    main()
