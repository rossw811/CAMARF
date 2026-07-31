"""
CAMARF follower_direction_validation.py — research/comparison script, NOT
part of the production pipeline.

Tests whether lead-lag structure identified by lead_lag_scan.py translates
into statistically significant directional predictability on the follower leg.

Hypothesis: if asset A leads asset B by best_lag bars, then A's N-bar
return should positively predict B's N-bar forward return. Tested via a
genuine non-overlapping walk-forward split (fit beta on a TRAIN window,
realize a fresh, independent beta on the immediately-following, disjoint
TEST window the fit never saw), reporting a one-sample t-test on the
realized OOS betas across all non-overlapping window pairs.

REDESIGNED 2026-07-20 (Grand Sweep Tier 2.4, confirmed real statistical
validity bug). The original version fit an EXPANDING-window OLS beta at
EVERY bar from min_periods=60 to n (labeling each step "OOS" despite it
being an ordinary in-sample regression t-stat on that step's own fitting
data), then pooled all those beta estimates' standard deviation into a
standard-error-of-the-mean (std/sqrt(n_oos)) as if they were n_oos
INDEPENDENT samples. They are not: consecutive expanding-window betas
differ by one additional data point out of what can be thousands, so they
are extremely serially correlated near-duplicates. Treating them as
independent shrinks the SEM toward zero as n_oos grows even though the
true independent information content does not, manufacturing artificially
significant t-stats for almost any pair with even a weak real beta — a
result that could not be trusted regardless of the BH-FDR correction
applied afterward, since BH-FDR corrects across pairs, not within an
already-invalid per-pair p-value.

Fix: research/comparison_arm_scaffold.py's walk_forward_windows() (built
earlier this same session for exactly this "the fitting step and the
scoring step must never share data" problem, task #22) partitions the
series into genuinely disjoint, non-overlapping (train, test) window
pairs. Beta is fit fresh on EACH window independently (both train and
test get their own OLS beta) and only the TEST-window beta is used for
inference — since each test window shares no rows with any other, a
one-sample t-test across the resulting per-window OOS betas is now a
statistically valid quantity, unlike the prior per-bar pseudo-OOS series.

Method:
  For each pair in lead_lag_scan.parquet where best_lag > 0 and
  flagged_lag_worth_checking=True:
    1. Load aligned price data via load_aligned_pair.
    2. Compute leader return over best_lag bars: r_A(t) = log(A_t / A_{t-lag})
    3. Compute follower forward return: r_B(t) = log(B_{t+lag} / B_t)
    4. Split into non-overlapping (train, test) windows via
       comparison_arm_scaffold.walk_forward_windows.
    5. Per window pair: fit beta_train on train (diagnostic only, not used
       for inference), fit beta_test fresh on test (the actual OOS
       observation used for inference).
    6. Aggregate: one-sample t-test of the per-window beta_test values vs 0
       across ALL non-overlapping window pairs.
  BH-FDR applied across all pairs on the resulting (now valid) p-value.

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
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from aligned_pair_loader import load_aligned_pair
from data import _gap_aware_returns
from comparison_arm_scaffold import walk_forward_windows

_OUT = "output/research/follower_direction_validation.parquet"
_LEAD_LAG_SRC = "output/research/lead_lag_scan.parquet"
_MIN_WF_WINDOWS = 8  # minimum non-overlapping walk-forward window PAIRS to report a result
_TRAIN_WINDOW = 252  # bars per train window
_TEST_WINDOW = 60    # bars per (disjoint, following) test window


def _log_returns(df, lag=1):
    """Gap-masked log returns at a given lag using production convention."""
    r = _gap_aware_returns(df)
    if lag == 1:
        return r
    # For lag>1 sum consecutive 1-bar log returns — additive for log returns
    return r.rolling(lag, min_periods=lag).sum()


def _ols_beta(xi, yi):
    """OLS beta = cov(x,y) / var(x), demeaned, no intercept. Returns NaN if
    insufficient finite data or near-zero x variance."""
    mask = np.isfinite(xi) & np.isfinite(yi)
    if mask.sum() < 20:
        return np.nan
    xi_m, yi_m = xi[mask], yi[mask]
    vx = np.var(xi_m, ddof=1)
    if vx < 1e-12:
        return np.nan
    return float(np.cov(xi_m, yi_m, ddof=1)[0, 1] / vx)


def _walk_forward_betas(x, y, train_window=_TRAIN_WINDOW, test_window=_TEST_WINDOW):
    """Genuine non-overlapping walk-forward test: for each disjoint
    (train, test) window pair, fit beta independently on each half. Returns
    (train_betas, test_betas) arrays, one entry per window pair that
    produced a finite beta on both halves. Only test_betas are used for
    inference (train_betas are diagnostic/reported only)."""
    df = pd.DataFrame({"x": x, "y": y})
    train_betas, test_betas = [], []
    for train, test in walk_forward_windows(df, train_window, test_window):
        bt = _ols_beta(train["x"].values, train["y"].values)
        bs = _ols_beta(test["x"].values, test["y"].values)
        if np.isfinite(bt) and np.isfinite(bs):
            train_betas.append(bt)
            test_betas.append(bs)
    return np.array(train_betas), np.array(test_betas)


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

        if len(combined) < _TRAIN_WINDOW + _TEST_WINDOW * _MIN_WF_WINDOWS:
            print(f"SKIP {sym_a}/{sym_b}@{tf}: insufficient bars ({len(combined)})")
            continue

        x, y = combined["x"].values, combined["y"].values
        train_betas, test_betas = _walk_forward_betas(x, y)

        if len(test_betas) < _MIN_WF_WINDOWS:
            print(f"SKIP {sym_a}/{sym_b}@{tf}: too few walk-forward window pairs ({len(test_betas)})")
            continue

        mean_test_beta = float(np.mean(test_betas))
        frac_positive_beta = float(np.mean(test_betas > 0))
        n_wf = len(test_betas)
        # Genuine one-sample t-test: each test_betas[i] comes from a disjoint,
        # non-overlapping window that shares no rows with any other window in
        # the array, so treating them as independent samples here is valid
        # (unlike the pre-fix version's per-bar expanding-window pseudo-OOS
        # series, which was NOT independent — see module docstring).
        agg_t, agg_p = stats.ttest_1samp(test_betas, popmean=0.0)
        agg_t, agg_p = float(agg_t), float(agg_p)

        directional = "predictive" if (mean_test_beta > 0 and frac_positive_beta > 0.55) else "no_signal"
        print(f"{'PRED' if directional == 'predictive' else 'flat':4s}  {sym_a}->{sym_b}@{tf}  "
              f"lag={lag}  beta={mean_test_beta:.4f}  frac_pos={frac_positive_beta:.2f}  "
              f"agg_t={agg_t:.2f}  p={agg_p:.4f}  n_wf_windows={n_wf}")

        rows.append({
            "tf": tf, "leader": sym_a, "follower": sym_b,
            "best_lag": lag, "corr_lift": corr_lift,
            "mean_oos_beta": mean_test_beta,
            "mean_train_beta": float(np.mean(train_betas)),
            "frac_positive_beta": frac_positive_beta,
            "agg_tstat": agg_t,
            "agg_pvalue_raw": agg_p,
            "n_wf_windows": n_wf,
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
