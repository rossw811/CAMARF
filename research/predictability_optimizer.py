"""
CAMARF predictability_optimizer.py — comparison method, NOT part of the
production pipeline.

Idea #3 from Development.md's Session 10 academic backlog: directly
optimize basket weights for tradeable mean-reversion instead of testing
a hypothesis about a pre-chosen hedge ratio (OLS/TLS/Kalman), in the
spirit of the Johansson/Schmelzer/Boyd 2024 moving-band framework and
the broader convex mean-reverting-portfolio literature (Box & Tiao 1977
canonical decomposition; d'Aspremont 2011, "Identifying Small Mean-
Reverting Portfolios"). NOTE on scope honesty: this implements the
well-established general formulation of that literature (minimize the
lag-1 "predictability ratio" w'Aw / w'Bw, a Box-Tiao/Bewley canonical
analysis), not a verified line-for-line reproduction of one specific
2024 paper's exact algorithm — the moving-band paper's precise
formulation wasn't independently re-derived here.

For a 2-asset basket (a literal pair — this project's existing confirmed
pairs), minimizing this ratio under a variance-normalization constraint
has an EXACT closed-form solution via generalized eigendecomposition —
no convex-concave/iterative solver is needed at this basket size. CCP
becomes genuinely necessary once baskets grow beyond 2 assets with
added constraints (sparsity, sign/no-short, a time-varying moving
threshold) — flagged as the natural extension, out of scope for this
pairs-only build.

Comparison design (per the 2026-06-23 discussion with Ross — strict
walk-forward, not a single split, given the overfitting risk this class
of method carries by construction):
  - Expanding-window folds per pair (skip pairs without enough history
    for >=3 folds — short-history pairs can't support genuine WFO, and a
    1-fold "result" isn't really walk-forward).
  - Each fold: fit BOTH methods (existing OLS hedge ratio, identical
    formula to analysis.py's _eg_worker; predictability-optimized
    weights) on the in-sample window only.
  - Report the SAME predictability-ratio metric in-sample AND
    out-of-sample for both methods — the in-sample/out-of-sample GAP is
    the actual overfitting diagnostic, not the out-of-sample number
    alone. A full P&L backtest is deliberately NOT built here — that is
    backtest.py's job once it exists; this stays scoped to "does the
    optimized weight's edge survive walk-forward," not a trading
    simulation.

Read-only. Loads cached price data directly via DataStore.load.
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
import scipy.linalg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import DataStore, _clean_close

_TF_DIRS = [
    "1min", "2min", "3min", "5min", "15min", "30min", "1hr", "4hr",
    "7day", "1mo", "3mo", "6mo",
]
_DIR_TO_LABEL = {
    "1min": "1m", "2min": "2m", "3min": "3m", "5min": "5m", "15min": "15m",
    "30min": "30m", "1hr": "1h", "4hr": "4h", "7day": "7D", "1mo": "1M",
    "3mo": "3M", "6mo": "6M",
}
_MIN_FOLDS = 3


def predictability_ratio(X: np.ndarray, w: np.ndarray) -> float:
    """w'Aw / w'Bw for a given weight vector — lower = more predictable/
    mean-reverting. X: (T, n) DEMEANED log-price matrix."""
    B = np.cov(X.T, ddof=1)
    dX1, dX0 = X[1:], X[:-1]
    gamma1 = (dX1.T @ dX0) / (len(dX0) - 1)
    A = (gamma1 + gamma1.T) / 2
    num = float(w @ A @ w)
    den = float(w @ B @ w)
    return num / den if den > 0 else np.nan


def predictability_weights(X: np.ndarray) -> np.ndarray:
    """Closed-form generalized-eigenvalue solution (exact for n=2; see
    module docstring for why CCP isn't needed at this basket size).
    X: (T, n) DEMEANED log-price matrix. Returns w normalized so
    w'Bw = 1."""
    B = np.cov(X.T, ddof=1)
    dX1, dX0 = X[1:], X[:-1]
    gamma1 = (dX1.T @ dX0) / (len(dX0) - 1)
    A = (gamma1 + gamma1.T) / 2
    eigvals, eigvecs = scipy.linalg.eigh(A, B)
    w = eigvecs[:, 0]  # smallest generalized eigenvalue = most predictable
    scale = np.sqrt(w @ B @ w)
    return w / scale if scale > 0 else w


def ols_weights(X: np.ndarray) -> np.ndarray:
    """Existing method's hedge ratio, IDENTICAL formula to
    analysis.py's _eg_worker (cov(a,b)/var(b)), expressed as a basket
    weight vector (1, -hedge_ratio) so both methods produce a
    directly-comparable spread w'x_t."""
    a, b = X[:, 0], X[:, 1]
    var_b = np.dot(b, b)
    hr = np.dot(a, b) / var_b if var_b > 0 else np.nan
    w = np.array([1.0, -hr])
    B = np.cov(X.T, ddof=1)
    scale = np.sqrt(w @ B @ w)
    return w / scale if scale > 0 else w


def _expanding_folds(n: int, n_folds: int):
    """Yields (train_end, test_start, test_end) — expanding in-sample
    window, contiguous non-overlapping out-of-sample test windows."""
    fold_size = n // (n_folds + 1)
    if fold_size < 30:
        return
    for i in range(n_folds):
        train_end = fold_size * (i + 1)
        test_start = train_end
        test_end = min(n, train_end + fold_size)
        if test_end - test_start < 30:
            continue
        yield train_end, test_start, test_end


def run_comparison(sym_a, sym_b, tf_label, n_folds=4):
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
    n_ill_conditioned = 0
    for train_end, test_start, test_end in _expanding_folds(len(X), n_folds):
        X_train = X[:train_end]
        X_test = X[test_start:test_end]
        train_mean = X_train.mean(axis=0)
        X_train_c = X_train - train_mean
        X_test_c = X_test - train_mean  # center on TRAIN mean — no test leakage

        try:
            w_pred = predictability_weights(X_train_c)
        except np.linalg.LinAlgError:
            # Near-singular in-sample covariance — most likely a leg with
            # near-zero variance over this specific fold window (e.g. the
            # BUG-D49 thin-information-content pattern). Skip this fold
            # rather than crash the whole comparison; this is itself a
            # useful signal, not just an error to suppress.
            n_ill_conditioned += 1
            continue
        w_ols = ols_weights(X_train_c)

        in_sample_pred = predictability_ratio(X_train_c, w_pred)
        in_sample_ols = predictability_ratio(X_train_c, w_ols)
        out_sample_pred = predictability_ratio(X_test_c, w_pred)
        out_sample_ols = predictability_ratio(X_test_c, w_ols)

        fold_results.append({
            "n_train": len(X_train), "n_test": len(X_test),
            "is_pred": in_sample_pred, "is_ols": in_sample_ols,
            "oos_pred": out_sample_pred, "oos_ols": out_sample_ols,
        })

    if not fold_results:
        status = "skipped_ill_conditioned" if n_ill_conditioned else "skipped_no_valid_folds"
        return {"status": status, "n_obs": len(joined)}

    fr = pd.DataFrame(fold_results)
    return {
        "status": "ok",
        "n_obs": len(joined),
        "n_folds": len(fr),
        "n_ill_conditioned": n_ill_conditioned,
        "mean_is_pred": fr["is_pred"].mean(), "mean_is_ols": fr["is_ols"].mean(),
        "mean_oos_pred": fr["oos_pred"].mean(), "mean_oos_ols": fr["oos_ols"].mean(),
        "oos_pred_beats_ols_fold_frac": float((fr["oos_pred"] < fr["oos_ols"]).mean()),
        "folds": fr,
    }


def main():
    p = argparse.ArgumentParser(description="Predictability-optimized weights vs OLS, strict WFO (idea #3)")
    p.add_argument("--n-folds", type=int, default=4)
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
            result = run_comparison(sym_a, sym_b, tf_label, n_folds=args.n_folds)
            if result is None:
                print(f"SKIP {sym_a}/{sym_b}@{tf_label}: cache missing")
                continue
            if result["status"] != "ok":
                print(f"SKIP {sym_a}/{sym_b}@{tf_label}: {result['status']} "
                      f"(n_obs={result['n_obs']}, need >= {30*(args.n_folds+1)} "
                      f"for {args.n_folds} folds)")
                continue
            ic_note = f" [{result['n_ill_conditioned']} fold(s) skipped, ill-conditioned cov]" if result["n_ill_conditioned"] else ""
            print(f"OK    {sym_a}/{sym_b}@{tf_label} ({result['n_folds']} folds, "
                  f"n_obs={result['n_obs']}){ic_note}: "
                  f"IS pred_ratio={result['mean_is_pred']:.4f} vs ols={result['mean_is_ols']:.4f} | "
                  f"OOS pred_ratio={result['mean_oos_pred']:.4f} vs ols={result['mean_oos_ols']:.4f} | "
                  f"OOS pred wins {result['oos_pred_beats_ols_fold_frac']:.0%} of folds")
            rows.append({
                "tf": tf_label, "symbol_a": sym_a, "symbol_b": sym_b,
                "n_obs": result["n_obs"], "n_folds": result["n_folds"],
                "mean_is_pred": result["mean_is_pred"], "mean_is_ols": result["mean_is_ols"],
                "mean_oos_pred": result["mean_oos_pred"], "mean_oos_ols": result["mean_oos_ols"],
                "oos_pred_beats_ols_fold_frac": result["oos_pred_beats_ols_fold_frac"],
            })

    if not rows:
        print("\nNo pairs had enough history for walk-forward comparison "
              f"(need >= {30*(args.n_folds+1)} overlapping bars for "
              f"{args.n_folds} folds). Try --n-folds 3 for shorter-history "
              "pairs, or re-run once more intraday history accumulates.")
        return

    result_df = pd.DataFrame(rows)
    print(f"\n=== Summary across {len(result_df)} pairs with sufficient history ===")
    is_gap = result_df["mean_is_ols"] - result_df["mean_is_pred"]
    oos_gap = result_df["mean_oos_ols"] - result_df["mean_oos_pred"]
    print(f"Mean in-sample advantage (ols_ratio - pred_ratio, higher=pred wins more): "
          f"{is_gap.mean():.4f}")
    print(f"Mean out-of-sample advantage: {oos_gap.mean():.4f}")
    shrinks = is_gap.mean() > oos_gap.mean()
    if shrinks:
        note = "consistent with some overfitting, as expected for any method that directly optimizes the in-sample objective"
    else:
        note = "edge is NOT shrinking out-of-sample — check carefully before trusting this"
    direction = "LARGER" if shrinks else "NOT larger"
    print(f"Overfitting signature check: in-sample advantage is {direction} than "
          f"out-of-sample advantage ({note}).")
    win_frac = (result_df["mean_oos_pred"] < result_df["mean_oos_ols"]).mean()
    print(f"Fraction of pairs where predictability-optimized weights still beat OLS "
          f"out-of-sample on average: {win_frac:.0%}")

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "predictability_optimizer_wfo.parquet")
    result_df.to_parquet(out_path)
    print(f"\nFull results written to {out_path}")


if __name__ == "__main__":
    main()
