"""
CAMARF copula_pairs.py — comparison/diagnostic, NOT part of the production
pipeline.

Motivated by a 2026-06-24 discussion with Ross, prompted directly by
tail_dependence.py's existing finding (idea #8): CCL/NCLH @3m shows real,
reliability-screened tail-dependence asymmetry (lambda_U~0.5 vs
lambda_L~0.32 — stronger UPPER-tail co-movement than lower). OLS/EG are
linear, implicitly-Gaussian frameworks that cannot represent this
asymmetry at all. This script asks the natural next question: does a
copula that CAN represent asymmetric tail dependence actually fit this
pair's joint return distribution better than a Gaussian copula,
out-of-sample.

Framing correction caught while scoping this (recorded here, not
silently fixed): a standard Clayton copula has LOWER-tail dependence
only (built for "crash together" asymmetry) and NO upper-tail
dependence — the wrong shape for CCL/NCLH's already-measured
upper-tail-dominant pattern. The fix is the 180-degree-rotated
("survival") Clayton: the identical Clayton density/fit applied to
(1-u, 1-v) instead of (u, v), which flips the dependence into the upper
tail with no new family or dependency needed. Both orientations are fit
INDEPENDENTLY (not assumed equal via the theta(u,v)=theta(1-u,1-v)
Kendall's-tau invariance, even though that invariance does hold — see
debug/_verify_copula_pairs.py, which checks it explicitly rather than
the production code silently relying on it) and compared alongside
plain Gaussian, letting the out-of-sample fit decide which wins.

Scope, deliberately narrow per this project's existing comparison-arm
discipline (tail_dependence.py, eg_permutation_check.py): defaults to
the ONE pair tail_dependence.py actually flagged (CCL/NCLH @3m), not a
universe-wide build. This answers "does the data prefer a non-Gaussian
copula here, out of sample" — it does NOT build a trading signal
(Mispricing Index) or a backtest; that is an appropriately-scoped next
step if this comparison says it's worth pursuing further, same staged-
build discipline already used for the MIDAS feature (verify the
modeling machinery first, defer "does it help prediction" honestly
until it can actually be answered).

Method:
  1. Gap-aware log returns for both legs (data.py's _gap_aware_returns).
  2. Pseudo-observations: rank-transform each leg's returns to (0,1) via
     rank/(n+1) (standard convention, avoids exact 0/1).
  3. Fit three single-parameter copula families via strict expanding-
     window walk-forward (same _expanding_folds convention as
     predictability_optimizer.py/ccp_variants.py, n_folds default 4):
       - Gaussian: rho = Pearson correlation of the normal-score
         transform (norm.ppf(u), norm.ppf(v)) on the TRAIN fold.
       - Clayton (lower-tail): theta = 2*tau/(1-tau) from Kendall's tau
         on the TRAIN fold — closed-form moment estimator, no numerical
         optimizer, consistent with this project's preference for
         simple/robust estimators over iterative ones (see the CCP-
         variants trust-region experience, Development.md Session 10).
       - Rotated Clayton (upper-tail, "survival"): independently fit on
         (1-u, 1-v); density evaluated at (1-u, 1-v).
     Each fold's pseudo-observations are computed within that fold (no
     parametric marginal model exists to transfer — only the dependence
     parameter is being tested out-of-sample, same logic as the existing
     CCP-variants evaluation).
  4. Report mean OOS log-likelihood per family per fold and overall.

Read-only. Loads cached price data via aligned_pair_loader.load_aligned_pair
(fixed 2026-06-24 — raw DataStore.load() output has no gap_flag column,
so _gap_aware_returns silently skipped all gap masking including the
overnight/weekend-spanning return; see Development.md Session 11) —
never fetches.

Usage:
    python research/copula_pairs.py
    python research/copula_pairs.py --symbol-a CCL --symbol-b NCLH --tf 3m --n-folds 4
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import kendalltau, norm, rankdata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aligned_pair_loader import load_aligned_pair
from data import _gap_aware_returns


def pseudo_observations(x):
    """Rank-transform to (0,1) via rank/(n+1) — avoids exact 0/1, which
    would send norm.ppf to +/-inf and Clayton's log(u)/log(v) to -inf."""
    n = len(x)
    return rankdata(x) / (n + 1)


def fit_gaussian(u, v):
    x, y = norm.ppf(u), norm.ppf(v)
    rho = float(np.corrcoef(x, y)[0, 1])
    return float(np.clip(rho, -0.999, 0.999))


def loglik_gaussian(u, v, rho):
    x, y = norm.ppf(u), norm.ppf(v)
    return (
        -0.5 * np.log(1 - rho ** 2)
        - (rho ** 2 * (x ** 2 + y ** 2) - 2 * rho * x * y) / (2 * (1 - rho ** 2))
    )


def fit_clayton_theta(u, v):
    """Closed-form Kendall's-tau moment estimator, theta = 2*tau/(1-tau).
    Returns None if tau <= 0 — standard positive-theta Clayton cannot
    represent non-positive dependence, no point forcing a fit."""
    tau, _ = kendalltau(u, v)
    if tau is None or not np.isfinite(tau) or tau <= 0:
        return None
    tau = min(tau, 0.999)
    return 2 * tau / (1 - tau)


def loglik_clayton(u, v, theta):
    return (
        np.log(1 + theta)
        - (theta + 1) * (np.log(u) + np.log(v))
        - (1.0 / theta + 2) * np.log(np.power(u, -theta) + np.power(v, -theta) - 1)
    )


def _expanding_folds(n, n_folds):
    """Mirrors predictability_optimizer.py's fold convention exactly
    (Development.md Session 10, idea #3) — expanding in-sample window,
    fixed-size out-of-sample test fold."""
    fold_size = n // (n_folds + 1)
    if fold_size < 30:
        return
    for i in range(n_folds):
        train_end = fold_size * (i + 1)
        test_start = train_end
        test_end = min(n, train_end + fold_size)
        yield train_end, test_start, test_end


def run_comparison(symbol_a, symbol_b, tf_label, n_folds=4):
    df_a, df_b = load_aligned_pair(symbol_a, symbol_b, tf_label)
    if df_a is None or df_b is None:
        return {"status": "missing_cache"}

    ret_a = pd.Series(_gap_aware_returns(df_a), index=df_a.index)
    ret_b = pd.Series(_gap_aware_returns(df_b), index=df_b.index)
    joined = pd.concat([ret_a, ret_b], axis=1, join="inner").dropna()
    n = len(joined)
    if n < 30 * (n_folds + 1):
        return {"status": "insufficient_data", "n_obs": n, "need": 30 * (n_folds + 1)}

    a_vals = joined.iloc[:, 0].values
    b_vals = joined.iloc[:, 1].values

    fold_rows = []
    for train_end, test_start, test_end in _expanding_folds(n, n_folds):
        train_a, train_b = a_vals[:train_end], b_vals[:train_end]
        test_a, test_b = a_vals[test_start:test_end], b_vals[test_start:test_end]
        if len(test_a) < 10:
            continue

        u_train, v_train = pseudo_observations(train_a), pseudo_observations(train_b)
        u_test, v_test = pseudo_observations(test_a), pseudo_observations(test_b)

        rho = fit_gaussian(u_train, v_train)
        ll_gauss = float(np.mean(loglik_gaussian(u_test, v_test, rho)))

        theta = fit_clayton_theta(u_train, v_train)
        ll_clayton = float(np.mean(loglik_clayton(u_test, v_test, theta))) if theta is not None else None

        theta_rot = fit_clayton_theta(1 - u_train, 1 - v_train)
        ll_rot_clayton = (
            float(np.mean(loglik_clayton(1 - u_test, 1 - v_test, theta_rot)))
            if theta_rot is not None else None
        )

        fold_rows.append({
            "train_end": train_end, "test_start": test_start, "test_end": test_end,
            "n_test": len(test_a), "rho_gaussian": rho,
            "theta_clayton": theta, "theta_rotated_clayton": theta_rot,
            "oos_loglik_gaussian": ll_gauss,
            "oos_loglik_clayton": ll_clayton,
            "oos_loglik_rotated_clayton": ll_rot_clayton,
        })

    if not fold_rows:
        return {"status": "no_valid_folds"}

    fr = pd.DataFrame(fold_rows)
    families = ["gaussian", "clayton", "rotated_clayton"]
    means = {f: fr[f"oos_loglik_{f}"].mean() for f in families}
    best = max((f for f in families if pd.notna(means[f])), key=lambda f: means[f])
    return {
        "status": "ok", "n_obs": n, "n_folds": len(fr),
        "mean_oos_loglik": means, "best_family": best, "folds": fr,
    }


def main():
    p = argparse.ArgumentParser(
        description="Gaussian vs Clayton vs rotated-Clayton copula fit comparison"
    )
    p.add_argument("--symbol-a", default="CCL")
    p.add_argument("--symbol-b", default="NCLH")
    p.add_argument("--tf", default="3m")
    p.add_argument("--n-folds", type=int, default=4)
    args = p.parse_args()

    result = run_comparison(args.symbol_a, args.symbol_b, args.tf, n_folds=args.n_folds)
    if result["status"] != "ok":
        print(f"{args.symbol_a}/{args.symbol_b}@{args.tf}: {result['status']} ({result})")
        return

    print(f"{args.symbol_a}/{args.symbol_b}@{args.tf}: n_obs={result['n_obs']} n_folds={result['n_folds']}")
    print(result["folds"][[
        "train_end", "test_start", "test_end", "n_test",
        "rho_gaussian", "theta_clayton", "theta_rotated_clayton",
        "oos_loglik_gaussian", "oos_loglik_clayton", "oos_loglik_rotated_clayton",
    ]].to_string(index=False))

    print("\nMean OOS log-likelihood per observation (higher = better fit):")
    for f, v in result["mean_oos_loglik"].items():
        marker = "  <-- best" if f == result["best_family"] else ""
        print(f"  {f:18s}: {v}{marker}")

    print(f"\nGATE RESULT: out-of-sample, the {result['best_family']} copula fits "
          f"this pair's joint return distribution best. This is a model-fit "
          f"comparison only — it does not build or evaluate a trading signal; "
          f"that is an appropriately-scoped next step if this result is "
          f"corroborated (e.g. re-run with more history as it accumulates), "
          f"not assumed from this alone.")

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "copula_comparison.parquet")
    result["folds"].to_parquet(out_path)
    print(f"\nFold-level results written to {out_path}")


if __name__ == "__main__":
    main()
