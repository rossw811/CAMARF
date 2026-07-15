"""
CAMARF research/regime_cluster_robustness_check.py — comparison/
diagnostic script, NOT part of the production pipeline (2026-07-14,
task #47).

Directly follows up on `research/hmm_gmm_regime_trade_features.py`'s
own finding (Development.md, 2026-07-13): 2 of 3 unsupervised methods
found a real, non-macro-regime pattern — entries clustering near market
open (hour≈9.5) show notably better realized performance — but the SAME
investigation's own expanding-window causal-stability check found this
pattern is NOT stable (oscillating agreement rates 43.1%/100.0%/50.2%/
100.0% across checkpoints). Flagged there as "an open, partially-
promising lead requiring a proper robustness check... before being
treated as a real finding" — this script is that check, using the two
specific approaches Ross's own note suggested: (1) does the pattern hold
on OOS-holdout trades, and (2) bootstrap resampling of the trade set.

Reuses `hmm_gmm_regime_trade_features.py`'s exact functions
(build_trade_features, fit_gmm, performance_by_state) directly, not
reimplemented, for methodological consistency with the original finding.

Method:
  1. Fit GMM on IS trades (trades_layer1.parquet) — same as the original
     finding. Identify the market-open cluster (highest mean_hour near
     9.5, best sharpe_like among states).
  2. HOLDOUT CHECK: apply the ALREADY-FITTED (IS-only) scaler+GMM to
     holdout trades' features (trades_layer1_holdout.parquet) — this
     tests whether the SAME discovered structure transfers to genuinely
     unseen trades, not whether refitting fresh on a much smaller
     holdout set "rediscovers" a coincidentally similar pattern.
  3. BOOTSTRAP CHECK: resample IS trades with replacement N times, refit
     GMM fresh on each draw, record whether a market-open-like cluster
     (mean_hour within +-1.5h of 9.5) is found AND whether it's the
     best- or near-best-performing cluster each time — measures whether
     the ORIGINAL finding is a robust feature of the data or an artifact
     of the specific single fit.

Usage:
    python research/regime_cluster_robustness_check.py --n-boot 200
"""
import argparse
import os
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from macro import build as macro_build
from hmm_gmm_regime_trade_features import (
    build_trade_features, fit_gmm, performance_by_state, _clean_feature_matrix, _FEATURE_COLS,
)

_IS_TRADES = "output/backtest/trades_layer1.parquet"
_HOLDOUT_TRADES = "output/backtest/trades_layer1_holdout.parquet"
_N_STATES = 3
_MARKET_OPEN_HOUR = 9.5
_MARKET_OPEN_TOLERANCE = 1.5


def _find_market_open_cluster(perf_df: pd.DataFrame):
    candidates = perf_df[(perf_df["mean_hour"] - _MARKET_OPEN_HOUR).abs() <= _MARKET_OPEN_TOLERANCE]
    if candidates.empty:
        return None
    return candidates.loc[candidates["mean_hour"].sub(_MARKET_OPEN_HOUR).abs().idxmin()]


def run_holdout_check(is_trades, holdout_trades, macro_df):
    print("=== Holdout check: apply IS-fitted GMM to unseen holdout trades ===\n")
    is_feat = build_trade_features(is_trades, macro_df)
    X_is, ok_is = _clean_feature_matrix(is_feat)
    from sklearn.preprocessing import StandardScaler
    from sklearn.mixture import GaussianMixture

    scaler = StandardScaler()
    Xs_is = scaler.fit_transform(X_is)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        gmm = GaussianMixture(n_components=_N_STATES, covariance_type="diag", random_state=42, n_init=5)
        states_is = gmm.fit_predict(Xs_is)

    perf_is = performance_by_state(is_feat, ok_is, states_is, "IS")
    open_cluster_is = _find_market_open_cluster(perf_is)
    if open_cluster_is is None:
        print("No market-open-like cluster found in IS fit — nothing to check on holdout.")
        return None
    print(f"IS market-open cluster: state={int(open_cluster_is['state'])}, "
          f"mean_hour={open_cluster_is['mean_hour']:.2f}, n_trades={int(open_cluster_is['n_trades'])}, "
          f"sharpe_like={open_cluster_is['sharpe_like']:.3f}")

    holdout_feat = build_trade_features(holdout_trades, macro_df)
    X_ho, ok_ho = _clean_feature_matrix(holdout_feat)
    if X_ho.shape[0] < 10:
        print(f"Holdout set too small ({X_ho.shape[0]} clean trades) for a meaningful check.")
        return None
    Xs_ho = scaler.transform(X_ho)  # SAME scaler fitted on IS, not refit
    states_ho = gmm.predict(Xs_ho)  # SAME GMM fitted on IS, not refit

    perf_ho = performance_by_state(holdout_feat, ok_ho, states_ho, "holdout_transferred")
    open_cluster_ho = perf_ho[perf_ho["state"] == int(open_cluster_is["state"])]
    if open_cluster_ho.empty:
        print("No holdout trades assigned to the IS market-open cluster.")
        return {"is_sharpe": open_cluster_is["sharpe_like"], "holdout_sharpe": None, "holdout_n": 0}

    row = open_cluster_ho.iloc[0]
    print(f"\nHoldout trades assigned to the SAME cluster: n={int(row['n_trades'])}, "
          f"sharpe_like={row['sharpe_like']:.3f} (vs. IS {open_cluster_is['sharpe_like']:.3f})")
    print(f"All holdout cluster performance:\n{perf_ho.to_string(index=False)}")
    return {"is_sharpe": float(open_cluster_is["sharpe_like"]), "holdout_sharpe": float(row["sharpe_like"]) if pd.notna(row["sharpe_like"]) else None,
            "holdout_n": int(row["n_trades"])}


def run_bootstrap_check(is_trades, macro_df, n_boot=200, seed=42):
    print(f"\n=== Bootstrap check: {n_boot} resamples of IS trades, refit fresh each time ===\n")
    rng = np.random.default_rng(seed)
    is_feat = build_trade_features(is_trades, macro_df)
    n = len(is_feat)

    found_count = 0
    best_or_near_best_count = 0
    for b in range(n_boot):
        idx = rng.integers(0, n, size=n)
        resampled = is_feat.iloc[idx].reset_index(drop=True)
        X, ok = _clean_feature_matrix(resampled)
        if X.shape[0] < 30:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                _, states, _ = fit_gmm(X, n_states=_N_STATES, seed=b)
            except Exception:
                continue
        perf = performance_by_state(resampled, ok, states, f"boot_{b}")
        open_cluster = _find_market_open_cluster(perf)
        if open_cluster is None:
            continue
        found_count += 1
        valid_sharpes = perf["sharpe_like"].dropna()
        if len(valid_sharpes) > 0 and pd.notna(open_cluster["sharpe_like"]):
            rank = (valid_sharpes >= open_cluster["sharpe_like"]).sum()  # 1 = best
            if rank <= 1:
                best_or_near_best_count += 1

    print(f"Market-open-like cluster found in {found_count}/{n_boot} bootstrap draws.")
    print(f"Of those, it was the BEST-performing cluster in {best_or_near_best_count}/{found_count} draws.")
    return {"n_boot": n_boot, "found_count": found_count, "best_count": best_or_near_best_count}


def main():
    p = argparse.ArgumentParser(description="Market-open regime-cluster robustness check (2026-07-14)")
    p.add_argument("--n-boot", type=int, default=200)
    args = p.parse_args()

    if not os.path.exists(_IS_TRADES):
        print(f"{_IS_TRADES} not found — cannot run.")
        return
    is_trades = pd.read_parquet(_IS_TRADES)
    macro_df = macro_build(force_refresh=False).data

    holdout_result = None
    if os.path.exists(_HOLDOUT_TRADES):
        holdout_trades = pd.read_parquet(_HOLDOUT_TRADES)
        holdout_result = run_holdout_check(is_trades, holdout_trades, macro_df)
    else:
        print(f"{_HOLDOUT_TRADES} not found — skipping holdout check.")

    boot_result = run_bootstrap_check(is_trades, macro_df, n_boot=args.n_boot)

    print(f"\n{'='*70}\nSUMMARY")
    if holdout_result:
        print(f"Holdout transfer: IS sharpe_like={holdout_result['is_sharpe']:.3f}, "
              f"holdout sharpe_like={holdout_result['holdout_sharpe']}, "
              f"holdout n={holdout_result['holdout_n']}")
    print(f"Bootstrap: cluster found in {boot_result['found_count']}/{boot_result['n_boot']} draws, "
          f"best-performing in {boot_result['best_count']}/{boot_result['found_count'] if boot_result['found_count'] else 1} of those.")

    out_dir = "output/research"
    os.makedirs(out_dir, exist_ok=True)
    summary = {**{"holdout_" + k: v for k, v in (holdout_result or {}).items()},
               **{"boot_" + k: v for k, v in boot_result.items()}}
    pd.DataFrame([summary]).to_parquet(os.path.join(out_dir, "regime_cluster_robustness_check.parquet"))
    print(f"\nResults written to {out_dir}/regime_cluster_robustness_check.parquet")


if __name__ == "__main__":
    main()
