"""
Synthetic ground truth for research/factor_residuals.py. 400 stocks, 3 planted factors; stocks 0-39 have an OU
idiosyncratic component (half-life 5 bars), the rest random-walk idiosyncratic prices.
Thresholds are derived, not guessed (first draft, N=60, used guessed ones and failed 3/5 -- Development.md 2026-11-11):
  1. Marchenko-Pastur count finds the 3 factors (every 252-bar window)
  2. PCA factor returns span the true factors: R^2_j >= theory - 0.02, theory = 1 - s2_idio / (sum_i beta_ij^2 s2_f)
  3. WITHOUT factor removal (k=0) the planted reversion is buried (OU median half-life >= 2x the PCA one); WITH PCA
     residuals it is recovered (median within [0.7, 1.6] x true 5) and random-walk stocks read >= 3x slower
     (a 252-bar AR(1) fit to a random walk reads ~20 bars, Dickey-Fuller bias -- not infinity)
  4. s-score tracks the true standardized OU deviation: corr > 0.7, and > raw (k=0) corr + 0.2.
     Reproduces a first-draft bug: common() added back each stock's full in-window mean, de-meaning the residuals
     (cumsum forced to 0 at the window end), corr 0.607 -> 0.828 after the fix. Larger N helps modestly (the
     projection leaks ~k/N of other stocks' noise into each residual): after the fix N=60 0.751, N=400 0.828.
  5. point-in-time: changing returns after bar t leaves every score dated <= t unchanged
Run: python debug/_verify_factor_residuals.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
import pandas as pd

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def make(rng, T=1500, N=400, n_ou=40, hl=5.0):
    F = rng.normal(0, 0.01, (T, 3))
    B = np.column_stack([rng.normal(1, 0.3, N), rng.normal(0, 0.5, N), rng.normal(0, 0.5, N)])
    b = 0.5 ** (1 / hl)
    X = np.zeros((T + 1, n_ou))
    for t in range(1, T + 1):
        X[t] = b * X[t - 1] + rng.normal(0, 0.01, n_ou)
    eps = np.column_stack([np.diff(X, axis=0), rng.normal(0, 0.01, (T, N - n_ou))])
    R = pd.DataFrame(F @ B.T + eps, index=pd.bdate_range("2015-01-01", periods=T), columns=[f"S{i}" for i in range(N)])
    sig_eq = 0.01 / np.sqrt(1 - b * b)
    return R, F, B, X[1:], sig_eq


def main():
    from research.factor_residuals import PCAModel, mp_factor_count, rolling_sscores
    rng = np.random.default_rng(20261111)
    R, F, B, X, sig_eq = make(rng)
    N_OU = 40
    A = R.to_numpy()
    ks = [mp_factor_count(A[t - 251: t + 1]) for t in range(251, len(A), 63)]
    check("1 MP finds 3 factors", set(ks) == {3}, f"counts={sorted(set(ks))}")

    m = PCAModel().fit(A)
    Fh = ((A - m.mu) / m.sd) @ m.V
    r2 = [1 - np.var(F[:, j] - Fh @ np.linalg.lstsq(Fh, F[:, j], rcond=None)[0]) / np.var(F[:, j]) for j in range(3)]
    theory = [1 - 1e-4 / ((B[:, j] ** 2).sum() * 1e-4) for j in range(3)]
    check("2 factor span", all(r >= th - 0.02 for r, th in zip(r2, theory)),
          f"R2={np.round(r2, 3)} theory={np.round(theory, 3)}")

    s0 = rolling_sscores(R, lambda: PCAModel(k=0))
    s3 = rolling_sscores(R, lambda: PCAModel())
    ou = lambda s: s["symbol"].str[1:].astype(int) < N_OU
    hl0 = s0.loc[ou(s0), "half_life"].fillna(np.inf).median()
    hl3 = s3.loc[ou(s3), "half_life"].fillna(np.inf).median()
    hlrw = s3.loc[~ou(s3), "half_life"].fillna(np.inf).median()
    check("3 factor removal reveals reversion", hl0 >= 2 * hl3 and 3.5 <= hl3 <= 8 and hlrw >= 3 * hl3,
          f"OU median hl: raw={hl0:.1f} pca={hl3:.1f}; RW median hl pca={hlrw:.1f} (true OU 5)")

    def track(sc):
        d = sc[ou(sc)]
        true = X[R.index.get_indexer(d["date"]), d["symbol"].str[1:].astype(int)] / sig_eq
        ok = np.isfinite(d["s"].to_numpy())
        return np.corrcoef(d["s"].to_numpy()[ok], true[ok])[0, 1], int(ok.sum())
    (c, n), (c0, _) = track(s3), track(s0)
    check("4 s-score tracks true deviation", c > 0.7 and c > c0 + 0.2, f"corr pca={c:.3f} raw={c0:.3f} n={n}")

    t_cut = 251 + 21 * 20
    R2 = R.copy()
    R2.iloc[t_cut + 1:] = rng.normal(0, 0.05, R2.iloc[t_cut + 1:].shape)
    a = s3[s3["date"] <= R.index[t_cut]].reset_index(drop=True)
    b = rolling_sscores(R2, lambda: PCAModel())
    b = b[b["date"] <= R.index[t_cut]].reset_index(drop=True)
    check("5 point-in-time", len(a) > 0 and a.equals(b), f"rows<=t: {len(a)}")

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
