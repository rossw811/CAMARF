"""
CAMARF ccp_variants.py — three constrained extensions to idea #3's
basket-weight optimizer (Development.md Session 10, 2026-06-23
follow-up), compared against each other and the existing OLS baseline
via the same strict walk-forward protocol as predictability_optimizer.py.

(a) SHRINKAGE TOWARD OLS — blend the unconstrained predictability-
    optimal weight with the OLS weight: w(alpha) = alpha*w_pred +
    (1-alpha)*w_ols (sign-aligned, re-normalized). Directly targets the
    overfitting failure mode predictability_optimizer.py's WFO run
    found (out-of-sample advantage went negative) by limiting how far
    the optimizer can move from the stable baseline.

(b) SPARSITY — only meaningful once baskets exceed 2 legs. Uses this
    session's real confirmed trios (analysis.py, 1h, Johansen-confirmed).
    At n=3 legs, exhaustive enumeration over which 2-or-3 legs to use is
    EXACT and cheaper/more reliable than an L0-relaxation — CCP earns
    its keep at basket sizes where enumeration is combinatorially
    infeasible (n >> 3), not here. Documented honestly, not pretending
    this needed CCP at this scale.

(c) THE ACTUAL MOVING-BAND MECHANISM (Johansson, Schmelzer & Boyd,
    "Finding Moving-Band Statistical Arbitrages via Convex-Concave
    Optimization," arXiv:2402.08108, Optimization and Engineering, Oct
    2024 — verified via direct source lookup 2026-06-23 before
    implementing, not guessed at). Real mechanism, confirmed from the
    abstract: maximize portfolio VARIANCE subject to (i) the portfolio
    price staying within a band around a (possibly time-varying)
    midpoint and (ii) a leverage limit. Maximizing a convex quadratic
    (variance) is itself the non-convex part — solved via CCP: linearize
    the variance objective at each iterate (turning each subproblem into
    an LP), re-solve, repeat to convergence. This is NOT the same
    objective as predictability_optimizer.py's Box-Tiao ratio
    minimization — that was an honestly-disclosed, different, simpler
    formulation; this is the actual paper's mechanism. One disclosed
    simplification: the band midpoint here is a rolling moving average
    of the OLS-weighted spread (a defensible, simple choice), not
    necessarily whatever specific midpoint construction the paper uses —
    full paper detail beyond the abstract was not re-derived line by
    line.

All three run through the IDENTICAL strict-WFO harness as
predictability_optimizer.py (expanding folds, in-sample vs out-of-sample
gap as the overfitting diagnostic) for direct comparability.
"""
import argparse
import os

import cvxpy as cp
import numpy as np
import pandas as pd

from data import DataStore, _clean_close
from predictability_optimizer import (
    ols_weights, predictability_ratio, predictability_weights, _expanding_folds,
)

_TF_DIRS = ["1min", "2min", "3min", "5min", "15min", "30min", "1hr", "4hr", "7day"]
_DIR_TO_LABEL = {
    "1min": "1m", "2min": "2m", "3min": "3m", "5min": "5m", "15min": "15m",
    "30min": "30m", "1hr": "1h", "4hr": "4h", "7day": "7D",
}


# ---------------------------------------------------------------------------
# (a) Shrinkage toward OLS
# ---------------------------------------------------------------------------

def shrinkage_weights(X: np.ndarray, alpha: float) -> np.ndarray:
    """alpha=1 -> pure predictability-optimal; alpha=0 -> pure OLS."""
    w_pred = predictability_weights(X)
    w_ols = ols_weights(X)
    # Sign-align: eigenvectors have an arbitrary sign; pick the sign that
    # makes w_pred point the same direction as w_ols (else blending could
    # partially cancel rather than shrink).
    if np.dot(w_pred, w_ols) < 0:
        w_pred = -w_pred
    w = alpha * w_pred + (1 - alpha) * w_ols
    B = np.cov(X.T, ddof=1)
    scale = np.sqrt(w @ B @ w)
    return w / scale if scale > 0 else w


# ---------------------------------------------------------------------------
# (b) Sparsity via exact enumeration (n=3 baskets)
# ---------------------------------------------------------------------------

def sparse_predictability_weights(X: np.ndarray, val_frac: float = 0.3) -> np.ndarray:
    """X: (T, 3). Selects which legs to use (full 3, or any 2-leg
    sub-basket) by an INTERNAL validation split, not raw in-sample fit —
    in-sample fit always favors more degrees of freedom by construction
    (the full 3-leg continuous optimum is a strictly larger feasible set
    than any 2-leg subset, since "drop a leg" is just one specific point
    within it), which would silently defeat the entire purpose of
    sparsity. Once a structure is selected via validation performance,
    final weights are refit on the FULL data X for that structure."""
    n = X.shape[1]
    assert n == 3, "this implementation is scoped to 3-leg baskets"
    split = int(len(X) * (1 - val_frac))
    X_fit = X[:split]
    X_val = X[split:] - X[:split].mean(axis=0)  # center val on FIT mean, no leakage

    structures = [[0, 1, 2], [1, 2], [0, 2], [0, 1]]
    best_score, best_structure = None, None
    for keep in structures:
        w_fit = predictability_weights(X_fit[:, keep])
        w_padded = np.zeros(n)
        w_padded[keep] = w_fit
        score = predictability_ratio(X_val, w_padded)
        if best_score is None or score < best_score:
            best_score, best_structure = score, keep

    w_final = predictability_weights(X[:, best_structure])
    w_padded = np.zeros(n)
    w_padded[best_structure] = w_final
    return w_padded


# ---------------------------------------------------------------------------
# (c) Moving-band mechanism (Johansson/Schmelzer/Boyd 2024), via CCP
# ---------------------------------------------------------------------------

def moving_band_weights(
    X: np.ndarray, band_half_width_mult: float = 2.0, leverage_limit: float = 4.0,
    ma_window: int = 30, max_iter: int = 15, tol: float = 1e-6,
) -> np.ndarray:
    """
    Maximize Var(w'x_t) s.t. |w'x_t - m_t| <= band_half_width for all t
    and ||w||_1 <= leverage_limit, via the convex-concave procedure.

    m_t: rolling moving-average of the OLS-weighted reference spread
    (disclosed simplification — see module docstring).

    band_half_width is set RELATIVE to each pair's own OLS spread's
    in-sample std (band_half_width_mult * std), not a fixed absolute
    value — found while running this on real data: a fixed absolute
    band across pairs with wildly different natural spread scales left
    many pairs' optimal solution unable to move away from a (heavily
    downscaled, to fit the too-tight band) OLS direction at all, making
    the CCP result a rescaled OLS direction in disguise — which
    predictability_ratio() reports as IDENTICAL to OLS (it's
    scale-invariant), silently masking that no real optimization
    happened. Scaling the band to each pair's own spread std fixes this.
    """
    n = X.shape[1]
    w_ols = ols_weights(X)
    ref_spread = X @ w_ols
    band_half_width = band_half_width_mult * np.std(ref_spread)
    m = pd.Series(ref_spread).rolling(ma_window, min_periods=1).mean().values

    B = np.cov(X.T, ddof=1)
    # Feasible, modest starting point: OLS direction, scaled down until
    # the band constraint actually holds.
    w_k = w_ols.copy()
    for _ in range(50):
        spread = X @ w_k
        if np.max(np.abs(spread - m)) <= band_half_width:
            break
        w_k *= 0.7
    else:
        return w_ols  # could not find a feasible starting scale — fall back

    # Trust region: without one, each LP subproblem's optimum sits at a
    # VERTEX of the band/leverage polytope, and naive CCP can jump
    # straight to a vertex far from the current linearization point —
    # found directly on real data (SPY/VOO): the iteration jumped to
    # w=(4.0, ~0), i.e. abandon the hedge entirely and leverage a single
    # leg, which trivially has high variance and (apparently) still
    # satisfied the band/leverage constraints, while destroying the
    # entire point of a basket spread. The linear approximation of the
    # true quadratic objective is only accurate NEAR w_k — a trust
    # region keeps each step close enough that the approximation (and
    # the resulting basket) stays meaningful. Shrinks geometrically if a
    # step is rejected (true objective got worse, not better).
    trust_region = 0.5 * np.linalg.norm(w_k, ord=1) if np.linalg.norm(w_k, ord=1) > 0 else 1.0
    prev_obj = float(w_k @ B @ w_k)
    for _ in range(max_iter):
        w = cp.Variable(n)
        # Linearize variance w'Bw around w_k: w'Bw ~ 2*w_k'B*w - w_k'B*w_k
        linearized_var = 2 * (B @ w_k) @ w - float(w_k @ B @ w_k)
        constraints = [
            X @ w - m <= band_half_width,
            m - X @ w <= band_half_width,
            cp.norm1(w) <= leverage_limit,
            cp.norm_inf(w - w_k) <= trust_region,
        ]
        prob = cp.Problem(cp.Maximize(linearized_var), constraints)
        prob.solve(solver=cp.CLARABEL)
        if w.value is None:
            break
        w_candidate = np.asarray(w.value).flatten()
        true_obj = float(w_candidate @ B @ w_candidate)
        if true_obj < prev_obj:
            # Step made the TRUE objective worse — the linear
            # approximation broke down at this step size. Shrink the
            # trust region and retry from the same w_k, don't accept it.
            trust_region *= 0.5
            if trust_region < 1e-6:
                break
            continue
        w_k = w_candidate
        if abs(true_obj - prev_obj) < tol * max(abs(true_obj), 1e-8):
            prev_obj = true_obj
            break
        prev_obj = true_obj

    # Deliberately NOT rescaled to unit variance like the other methods'
    # weights — this method's scale is meaningful (set by the band
    # constraint itself; rescaling afterward would push the spread
    # outside the band that was just solved for). predictability_ratio()
    # is scale-invariant (w'Aw/w'Bw is unchanged under w -> c*w), so the
    # comparison metric used elsewhere in this module is unaffected by
    # returning the raw, constraint-respecting solution here.
    return w_k


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def _verify():
    rng = np.random.RandomState(1)
    failures = []

    # Shrinkage: alpha=1 should equal (sign-aligned) predictability_weights;
    # alpha=0 should equal ols_weights.
    n, t = 2, 500
    trend = np.cumsum(rng.randn(t) * 0.5)
    mr = np.zeros(t)
    for i in range(1, t):
        mr[i] = mr[i - 1] * 0.9 + rng.randn() * 0.3
    X2 = np.column_stack([trend + mr, trend])
    X2c = X2 - X2.mean(axis=0)

    w_a1 = shrinkage_weights(X2c, alpha=1.0)
    w_pred = predictability_weights(X2c)
    if np.dot(w_a1, w_pred) < 0:
        w_pred = -w_pred
    ok = np.allclose(w_a1, w_pred, atol=1e-6)
    print(f"{'OK' if ok else 'FAIL'}  shrinkage alpha=1.0 matches pure predictability weights")
    if not ok:
        failures.append("shrinkage_alpha1")

    w_a0 = shrinkage_weights(X2c, alpha=0.0)
    w_ols_ = ols_weights(X2c)
    ok = np.allclose(w_a0, w_ols_, atol=1e-6)
    print(f"{'OK' if ok else 'FAIL'}  shrinkage alpha=0.0 matches pure OLS weights")
    if not ok:
        failures.append("shrinkage_alpha0")

    # Sparsity: construct a 3-leg system where leg 3 is an IRRELEVANT
    # leg unrelated to trend/mr. Deliberately NOT pure i.i.d. noise —
    # found directly while debugging this test (see Development.md):
    # i.i.d. noise has lag-1 autocorrelation near zero, which means it
    # trivially MINIMIZES the predictability ratio on its own merits
    # (confirmed numerically: pure noise ratio ~= -0.018), spuriously
    # "winning" comparisons that have nothing to do with genuine
    # mean-reversion. A real methodological limitation of the Box-Tiao
    # ratio worth knowing, not just a test bug. Using a random-WALK
    # (persistent, ratio ~= 0.98) irrelevant leg instead avoids that
    # pathology and properly tests "does sparsity avoid overfitting to
    # an irrelevant leg's in-sample idiosyncrasies."
    #
    # The unconstrained 3-leg continuous optimum is a strictly LARGER
    # feasible set than any 2-leg subset (a sparse choice is just one
    # specific point within it), so full will ALWAYS look at least as
    # good IN-SAMPLE by construction — that's not what sparsity is for.
    # The actual claimed benefit is OUT-OF-SAMPLE robustness. Test that
    # property directly: fit both on a train split, evaluate both on a
    # held-out split.
    irrelevant_leg = np.cumsum(rng.randn(t) * 0.5)  # independent random walk
    X3 = np.column_stack([trend + mr, trend, irrelevant_leg])
    X3c_full = X3 - X3.mean(axis=0)
    split = t // 2
    X3_train, X3_test = X3c_full[:split], X3c_full[split:] - X3c_full[:split].mean(axis=0)

    w_sparse = sparse_predictability_weights(X3_train)
    w_full = predictability_weights(X3_train)
    r_sparse_oos = predictability_ratio(X3_test, w_sparse)
    r_full_oos = predictability_ratio(X3_test, w_full)
    dropped_noise_leg = w_sparse[2] == 0.0
    # A truly irrelevant leg shouldn't help OR hurt much out-of-sample
    # once the structure is correctly identified — comparable
    # performance (not necessarily strictly better) is the right bar
    # here; an exact "<=" is too sensitive to single-draw noise on a
    # leg with zero true relationship by construction.
    ok = dropped_noise_leg and r_sparse_oos <= r_full_oos + 0.02
    print(f"{'OK' if ok else 'FAIL'}  sparse selection drops the irrelevant leg "
          f"in-sample (w3={w_sparse[2]:.4f}) and generalizes comparably "
          f"out-of-sample (sparse_oos={r_sparse_oos:.4f} ~= full_oos={r_full_oos:.4f})")
    if not ok:
        failures.append("sparsity")

    # Moving band: verify the CCP solution actually satisfies the
    # constraints it was given.
    band_mult = 2.0
    w_mb = moving_band_weights(X2c, band_half_width_mult=band_mult, leverage_limit=4.0)
    w_ols_ref = ols_weights(X2c)
    ref_spread = X2c @ w_ols_ref
    band_half_width = band_mult * np.std(ref_spread)
    m = pd.Series(ref_spread).rolling(30, min_periods=1).mean().values
    spread_mb = X2c @ w_mb
    within_band = np.max(np.abs(spread_mb - m)) <= band_half_width + 1e-4
    within_leverage = np.sum(np.abs(w_mb)) <= 4.0 + 1e-4
    print(f"{'OK' if within_band else 'FAIL'}  moving-band solution respects the "
          f"band constraint (max deviation {np.max(np.abs(spread_mb - m)):.4f} <= "
          f"{band_half_width:.4f})")
    print(f"{'OK' if within_leverage else 'FAIL'}  moving-band solution respects "
          f"leverage limit (||w||_1={np.sum(np.abs(w_mb)):.4f} <= 4.0)")
    if not within_band:
        failures.append("moving_band_constraint")
    if not within_leverage:
        failures.append("moving_band_leverage")

    return failures


# ---------------------------------------------------------------------------
# Real-data comparison: pairs (OLS / predictability / shrinkage / moving-band)
# ---------------------------------------------------------------------------

def run_pair_comparison(sym_a, sym_b, tf_label, n_folds=4, alpha=0.5):
    df_a = DataStore.load(sym_a, tf_label)
    df_b = DataStore.load(sym_b, tf_label)
    if df_a is None or df_b is None:
        return None
    log_a = np.log(_clean_close(df_a))
    log_b = np.log(_clean_close(df_b))
    joined = pd.DataFrame({"a": log_a}, index=df_a.index).join(
        pd.DataFrame({"b": log_b}, index=df_b.index), how="inner"
    ).dropna()
    if len(joined) < 30 * (n_folds + 1):
        return {"status": "skipped_insufficient_history", "n_obs": len(joined)}

    X = joined.values
    fold_results = []
    for train_end, test_start, test_end in _expanding_folds(len(X), n_folds):
        X_train = X[:train_end]
        X_test = X[test_start:test_end]
        train_mean = X_train.mean(axis=0)
        X_train_c = X_train - train_mean
        X_test_c = X_test - train_mean
        try:
            w_ols = ols_weights(X_train_c)
            w_pred = predictability_weights(X_train_c)
            w_shrink = shrinkage_weights(X_train_c, alpha=alpha)
            w_mb = moving_band_weights(X_train_c)
        except np.linalg.LinAlgError:
            continue
        fold_results.append({
            "oos_ols": predictability_ratio(X_test_c, w_ols),
            "oos_pred": predictability_ratio(X_test_c, w_pred),
            "oos_shrink": predictability_ratio(X_test_c, w_shrink),
            "oos_mb": predictability_ratio(X_test_c, w_mb),
        })
    if not fold_results:
        return {"status": "skipped_ill_conditioned", "n_obs": len(joined)}
    fr = pd.DataFrame(fold_results)
    return {"status": "ok", "n_obs": len(joined), "n_folds": len(fr), **fr.mean().to_dict()}


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--n-folds", type=int, default=4)
    p.add_argument("--alpha", type=float, default=0.5)
    args = p.parse_args()

    rows = []
    for tf_dir in _TF_DIRS:
        path = f"output/results/{tf_dir}/pairs.parquet"
        if not os.path.exists(path):
            continue
        tf_label = _DIR_TO_LABEL[tf_dir]
        df = pd.read_parquet(path)
        for _, row in df.iterrows():
            sym_a, sym_b = row["symbol_a"], row["symbol_b"]
            result = run_pair_comparison(sym_a, sym_b, tf_label, args.n_folds, args.alpha)
            if result is None or result["status"] != "ok":
                continue
            print(f"{sym_a}/{sym_b}@{tf_label} (n={result['n_obs']}, {result['n_folds']} folds): "
                  f"OOS ratio  ols={result['oos_ols']:.4f}  pred={result['oos_pred']:.4f}  "
                  f"shrink(a={args.alpha})={result['oos_shrink']:.4f}  moving_band={result['oos_mb']:.4f}")
            rows.append({"tf": tf_label, "symbol_a": sym_a, "symbol_b": sym_b, **result})

    if not rows:
        print("No pairs with sufficient history.")
        return
    rdf = pd.DataFrame(rows)
    print(f"\n=== Mean OOS predictability ratio across {len(rdf)} pairs (lower = better) ===")
    for col, name in [("oos_ols", "OLS (baseline)"), ("oos_pred", "Unconstrained predictability"),
                       ("oos_shrink", f"Shrinkage (alpha={args.alpha})"), ("oos_mb", "Moving-band (CCP)")]:
        print(f"  {name:32s}: {rdf[col].mean():.4f}  (wins {((rdf[col]==rdf[['oos_ols','oos_pred','oos_shrink','oos_mb']].min(axis=1)).mean()):.0%} of pairs)")

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    rdf.to_parquet(os.path.join(out_dir, "ccp_variants_comparison.parquet"))
    print(f"\nFull results: {out_dir}/ccp_variants_comparison.parquet")


if __name__ == "__main__":
    failures = _verify()
    if failures:
        print(f"\nFAILED: {failures}")
        import sys
        sys.exit(1)
    print("\nAll synthetic checks passed.\n")
    main()
