"""
research/factor_residuals.py -- factor-residual mean reversion (Avellaneda & Lee 2010), the standard benchmark against
pair-by-pair Engle-Granger (Ross 2026-11-11: "add tests for ... PCA, auto encoders, vaes").

Each stock's return = common part (explained by a factor model) + idiosyncratic residual. The cumulated residual X_t
is fitted as an OU process (AR(1) on X); the s-score (X_T - m) / sigma_eq says how far the stock sits from its
equilibrium against the market factors. Trading the s-score is the A-L strategy.

The factor model is pluggable through one interface -- `fit(R_window)` then `common(R)` -> the common part of R:
  * PCAModel: projection of standardized returns on the top-k correlation eigenvectors. This is the optimal LINEAR
    autoencoder; research/factor_autoencoders.py supplies nonlinear (AE) and probabilistic (VAE) models with the same
    interface, so the comparison isolates the factor model with the trading rule held fixed.
  * k is not hardcoded: the number of correlation eigenvalues above the Marchenko-Pastur edge (1 + sqrt(N/T))^2.
Point-in-time: rolling_sscores fits the model and the OU on the window ENDING at each decision bar only.
Differences from A-L, disclosed: projection instead of regression on eigenportfolio returns (equivalent up to the
standardization), and no drift term in the s-score.
Verify: debug/_verify_factor_residuals.py
"""
import numpy as np
import pandas as pd

TRADING_DAYS = 252


def mp_factor_count(R: np.ndarray) -> int:
    """Eigenvalues of the correlation matrix above the Marchenko-Pastur upper edge (1 + sqrt(N/T))^2."""
    T, N = R.shape
    Z = (R - R.mean(0)) / R.std(0, ddof=1)
    ev = np.linalg.eigvalsh(Z.T @ Z / (T - 1))
    return int((ev > (1 + np.sqrt(N / T)) ** 2).sum())


class PCAModel:
    """Linear autoencoder: encode = V_k^T z, decode = V_k code, in standardized-return space."""

    def __init__(self, k=None):
        self.k = k

    def fit(self, R: np.ndarray):
        self.mu, self.sd = R.mean(0), R.std(0, ddof=1)
        Z = (R - self.mu) / self.sd
        k = self.k if self.k is not None else max(mp_factor_count(R), 1)
        ev, V = np.linalg.eigh(Z.T @ Z / (len(Z) - 1))
        self.V = V[:, np.argsort(ev)[::-1][:k]]
        self.k_used = k
        return self

    def common(self, R: np.ndarray) -> np.ndarray:
        # Project the UNCENTERED scaled returns: only the factor-driven part of each mean is removed, the stock's own
        # drift stays in its residual. Adding back the full in-window mean (first draft) de-meaned every residual, so
        # its cumulative sum ended at exactly 0 and carried a ramp (X_t - X_t0) / T per bar -- the s-score then
        # measured ~(X_t + X_t0) / 2 (corr 0.61 with the true deviation; debug/_verify_factor_residuals.py check 4).
        return ((R / self.sd) @ self.V @ self.V.T) * self.sd


def ou_sscore(eps: np.ndarray) -> pd.DataFrame:
    """Per column of residual returns: X = cumsum(eps); AR(1) X_{t+1} = a + b X_t; kappa = -ln(b) * 252,
    half_life = -ln 2 / ln b (bars), m = a / (1 - b), sigma_eq = sqrt(var(zeta) / (1 - b^2)), s = (X_T - m) / sigma_eq.
    NaN when b is not in (0, 1)."""
    X = np.cumsum(eps, axis=0)
    x0, x1 = X[:-1], X[1:]
    n = len(x0)
    xm, ym = x0.mean(0), x1.mean(0)
    b = ((x0 - xm) * (x1 - ym)).sum(0) / ((x0 - xm) ** 2).sum(0)
    a = ym - b * xm
    zeta = x1 - (a + b * x0)
    var_z = (zeta ** 2).sum(0) / (n - 2)
    ok = (b > 0) & (b < 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        bb = np.where(ok, b, np.nan)
        m = a / (1 - bb)
        sig = np.sqrt(var_z / (1 - bb ** 2))
        return pd.DataFrame({"b": b, "kappa": -np.log(bb) * TRADING_DAYS, "half_life": -np.log(2) / np.log(bb),
                             "m": m, "sigma_eq": sig, "s": (X[-1] - m) / sig})


def rolling_sscores(R: pd.DataFrame, model_factory, window: int = 252, step: int = 21) -> pd.DataFrame:
    """At every `step`-th bar t (from window-1), fit model_factory() on R[t-window+1 : t+1] -- only data up to t --
    and score the in-window residuals. Columns with any NaN in the window are skipped for that window."""
    rows = []
    A = R.to_numpy(float)
    for t in range(window - 1, len(R), step):
        W = A[t - window + 1: t + 1]
        cols = np.nonzero(np.isfinite(W).all(0))[0]
        if cols.size < 3:
            continue
        Wc = W[:, cols]
        model = model_factory().fit(Wc)
        sc = ou_sscore(Wc - model.common(Wc))
        sc.insert(0, "symbol", R.columns[cols])
        sc.insert(0, "date", R.index[t])
        sc["k_factors"] = getattr(model, "k_used", np.nan)
        rows.append(sc)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
