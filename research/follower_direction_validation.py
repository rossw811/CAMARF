"""
CAMARF follower_direction_validation.py — research/comparison script, NOT
part of the production pipeline.

Tests whether lead-lag structure identified by lead_lag_scan.py translates
into statistically significant directional predictability on the follower leg.

Hypothesis: if asset A leads asset B by best_lag bars, then A's N-bar
return should positively predict B's N-bar forward return. Tested via
rolling OLS (expanding window, 60-bar minimum), reporting the slope
coefficient and its out-of-sample t-statistic under BH-FDR correction.

Method:
  For each pair in lead_lag_scan.parquet where best_lag > 0 and
  flagged_lag_worth_checking=True:
    1. Load aligned price data via load_aligned_pair.
    2. Compute leader return over best_lag bars: r_A(t) = log(A_t / A_{t-lag})
    3. Compute follower forward return: r_B(t) = log(B_{t+lag} / B_t)
    4. Rolling OLS (expanding, min_periods=60): r_B ~ beta * r_A + eps
    5. Out-of-sample: record beta estimate and t-stat at each step.
    6. Aggregate: mean OOS beta, fraction of OOS steps where beta > 0,
       pooled t-statistic on OOS betas.
  BH-FDR applied across all pairs on the pooled t-test p-value.

For completeness, also includes pairs with best_lag == 0 where
flagged_lag_worth_checking=True — these test lag-0 co-movement direction
(same-bar correlation as a baseline). They are expected to be positive
but not predictive in a trading sense.

Usage:
    python research/follower_direction_validation.py
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aligned_pair_loader import load_aligned_pair
from data import _gap_aware_returns

_OUT = "output/research/follower_direction_validation.parquet"
_LEAD_LAG_SRC = "output/research/lead_lag_scan.parquet"
_MIN_OOS_PERIODS = 30  # minimum rolling OOS steps to report a result


def _log_returns(df, lag=1):
    """Gap-masked log returns at a given lag using production convention."""
    r = _gap_aware_returns(df)
    if lag == 1:
        return r
    # For lag>1 sum consecutive 1-bar log returns — additive for log returns
    return r.rolling(lag, min_periods=lag).sum()


def _rolling_ols_oos(x, y, min_periods=60):
    """
    Expanding-window OOS OLS of y ~ beta*x (demeaned, no intercept).
    At each step t >= min_periods, fit on [0:t] and record beta, se, t-stat.
    Returns arrays (betas, tstats) of length max(0, n - min_periods).
    """
    n = len(x)
    betas, tstats = [], []
    for t in range(min_periods, n):
        xi, yi = x[:t], y[:t]
        mask = np.isfinite(xi) & np.isfinite(yi)
        if mask.sum() < min_periods:
            betas.append(np.nan)
            tstats.append(np.nan)
            continue
        xi_m, yi_m = xi[mask], yi[mask]
        # OLS beta = cov(x,y) / var(x)
        vx = np.var(xi_m, ddof=1)
        if vx < 1e-12:
            betas.append(np.nan)
            tstats.append(np.nan)
            continue
        beta = np.cov(xi_m, yi_m, ddof=1)[0, 1] / vx
        resid = yi_m - beta * xi_m
        s2 = np.sum(resid ** 2) / (len(xi_m) - 1)
        se = np.sqrt(s2 / (len(xi_m) * vx))
        t_stat = beta / se if se > 1e-12 else np.nan
        betas.append(beta)
        tstats.append(t_stat)
    return np.array(betas), np.array(tstats)


def main():
    if not os.path.exists(_LEAD_LAG_SRC):
        print(f"lead_lag_scan.parquet not found at {_LEAD_LAG_SRC} — run lead_lag_scan.py first")
        return

    ll = pd.read_parquet(_LEAD_LAG_SRC)
    # Only process pairs with meaningful lead-lag flagged or positive best_lag
    candidates = ll[ll["flagged_lag_worth_checking"] | (ll["best_lag"] > 0)].copy()
    print(f"Testing {len(candidates)} lead-lag candidate pairs from lead_lag_scan.parquet")

    rows = []
    for _, row in candidates.iterrows():
        tf = row["tf"]
        sym_a, sym_b = row["symbol_a"], row["symbol_b"]
        lag = int(row["best_lag"])
        corr_lift = float(row["corr_lift"])

        df_a, df_b = load_aligned_pair(sym_a, sym_b, tf)
        if df_a is None or df_b is None:
            print(f"SKIP {sym_a}/{sym_b}@{tf}: cache missing")
            continue

        # Leader is symbol_a (as defined by lead_lag_scan: sym_a leads sym_b)
        r_leader = _log_returns(df_a, lag=max(lag, 1))
        r_follower_fwd = _log_returns(df_b, lag=max(lag, 1)).shift(-max(lag, 1))

        # Align on common index
        combined = pd.DataFrame({
            "x": r_leader, "y": r_follower_fwd
        }, index=df_a.index).reindex(
            df_a.index.intersection(df_b.index)
        ).dropna()

        if len(combined) < _MIN_OOS_PERIODS + 60:
            print(f"SKIP {sym_a}/{sym_b}@{tf}: insufficient bars ({len(combined)})")
            continue

        x, y = combined["x"].values, combined["y"].values
        betas, tstats = _rolling_ols_oos(x, y, min_periods=60)

        valid_mask = np.isfinite(betas)
        if valid_mask.sum() < _MIN_OOS_PERIODS:
            print(f"SKIP {sym_a}/{sym_b}@{tf}: too few OOS periods ({valid_mask.sum()})")
            continue

        betas_v = betas[valid_mask]
        tstats_v = tstats[valid_mask]

        mean_beta = float(np.nanmean(betas_v))
        frac_positive_beta = float(np.mean(betas_v > 0))
        # Pooled t-test: mean OOS beta vs 0 using standard error of the mean
        n_oos = len(betas_v)
        pooled_t = float(np.nanmean(tstats_v))  # mean OOS t-stat
        pooled_se = float(np.nanstd(betas_v, ddof=1) / np.sqrt(n_oos))
        agg_t = float(mean_beta / pooled_se) if pooled_se > 1e-12 else np.nan
        # Two-sided p from aggregate t-statistic
        agg_p = float(2 * stats.t.sf(abs(agg_t), df=n_oos - 1)) if np.isfinite(agg_t) else np.nan

        directional = "predictive" if (mean_beta > 0 and frac_positive_beta > 0.55) else "no_signal"
        print(f"{'PRED' if directional == 'predictive' else 'flat':4s}  {sym_a}->{sym_b}@{tf}  "
              f"lag={lag}  beta={mean_beta:.4f}  frac_pos={frac_positive_beta:.2f}  "
              f"agg_t={agg_t:.2f}  p={agg_p:.4f}  n_oos={n_oos}")

        rows.append({
            "tf": tf, "leader": sym_a, "follower": sym_b,
            "best_lag": lag, "corr_lift": corr_lift,
            "mean_oos_beta": mean_beta,
            "frac_positive_beta": frac_positive_beta,
            "mean_oos_tstat": float(np.nanmean(tstats_v)),
            "agg_tstat": agg_t,
            "agg_pvalue_raw": agg_p,
            "n_oos_periods": n_oos,
            "directional_flag": directional,
        })

    if not rows:
        print("No results produced.")
        return

    out = pd.DataFrame(rows)

    # BH-FDR correction across all pairs on the aggregate p-value
    valid_p = out["agg_pvalue_raw"].notna()
    if valid_p.sum() > 1:
        reject, p_adj, _, _ = multipletests(
            out.loc[valid_p, "agg_pvalue_raw"].values, method="fdr_bh"
        )
        out.loc[valid_p, "agg_pvalue_bh_adjusted"] = p_adj
        out.loc[valid_p, "significant_bh"] = reject
    else:
        out["agg_pvalue_bh_adjusted"] = out["agg_pvalue_raw"]
        out["significant_bh"] = out["agg_pvalue_raw"] < 0.05

    n_sig = int(out["significant_bh"].sum()) if "significant_bh" in out.columns else 0
    n_pred = int((out["directional_flag"] == "predictive").sum())
    print(f"\n{n_pred}/{len(out)} pairs show positive directional bias; "
          f"{n_sig}/{len(out)} significant after BH-FDR")
    print(f"\n{out[['tf','leader','follower','best_lag','mean_oos_beta','frac_positive_beta','agg_tstat','significant_bh']].to_string()}")

    os.makedirs(os.path.dirname(_OUT), exist_ok=True)
    out.to_parquet(_OUT, index=False)
    print(f"\nResults written to {_OUT}")


if __name__ == "__main__":
    main()
