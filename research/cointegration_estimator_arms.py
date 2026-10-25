"""
research/cointegration_estimator_arms.py -- endogeneity arm (a) (Ross 2026-10-13: comparison first, main pathway only
if the comparison supports it).

The cointegrating regression log A = a + b log B + u has an endogenous regressor (the prices are jointly determined;
u is serially correlated and correlated with the shocks to B). OLS is superconsistent for b but carries a
second-order bias in finite samples and its t-statistics are not valid; EG built on it also depends on which leg is
the regressand. Comparison estimators:
  dols_beta   -- dynamic OLS (Stock & Watson 1993): add leads and lags of dB; DOLS_LEADS_LAGS each side
  fmols_beta  -- fully modified OLS (Phillips & Hansen 1990): Bartlett-kernel long-run covariances, Newey-West (1994)
                 automatic bandwidth floor(4 (T/100)^(2/9))
  johansen_*  -- Johansen (1991) trace test for rank 0 vs >= 1, symmetric in leg order, RESTRICTED constant (inside
                 the cointegrating relation, as for price levels), lag order JOHANSEN_K_AR_DIFF as production;
                 critical values simulated under the null (johansen_crit), not tabulated
The real-data comparison on the rebuilt pools (hedge ratios and confirmation agreement EG vs Johansen) runs after the
2026-10-12 re-run chain. Test: debug/_verify_cointegration_estimator_arms.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DOLS_LEADS_LAGS = 2       # Stock-Watson leads/lags of the differenced regressor (small, fixed; see registry)


def ols_beta(y, x) -> float:
    X = np.column_stack([np.ones(len(x)), x])
    return float(np.linalg.lstsq(X, y, rcond=None)[0][1])


def dols_beta(y, x, k: int = DOLS_LEADS_LAGS) -> float:
    y, x = np.asarray(y, float), np.asarray(x, float)
    dx = np.diff(x)                       # dx[t-1] = x[t] - x[t-1]
    T = len(x)
    rows = range(k + 1, T - k)
    cols = [np.ones(len(rows)), x[k + 1:T - k]]
    for j in range(-k, k + 1):
        cols.append(np.array([dx[t - 1 + j] for t in rows]))
    X = np.column_stack(cols)
    return float(np.linalg.lstsq(X, y[k + 1:T - k], rcond=None)[0][1])


def _bartlett_lrcov(a, b, L):
    T = len(a)
    s = a @ b / T
    for l in range(1, L + 1):
        w = 1 - l / (L + 1)
        s += w * (a[l:] @ b[:-l] + a[:-l] @ b[l:]) / T
    return s


def fmols_beta(y, x) -> float:
    y, x = np.asarray(y, float), np.asarray(x, float)
    X = np.column_stack([np.ones(len(x)), x])
    b0 = np.linalg.lstsq(X, y, rcond=None)[0]
    u = (y - X @ b0)[1:]
    v = np.diff(x)
    u, v = u - u.mean(), v - v.mean()
    T = len(v)
    L = int(np.floor(4 * (T / 100) ** (2 / 9)))
    Ovv, Ouv = _bartlett_lrcov(v, v, L), _bartlett_lrcov(u, v, L)
    # one-sided long-run covariance Delta_vu = sum_{l>=0} E[v_t u_{t+l}] (Bartlett-weighted)
    Dvu = v @ u / T + sum((1 - l / (L + 1)) * (v[:-l] @ u[l:]) / T for l in range(1, L + 1))
    Dvv = v @ v / T + sum((1 - l / (L + 1)) * (v[:-l] @ v[l:]) / T for l in range(1, L + 1))
    ystar = y[1:] - (Ouv / Ovv) * v
    Xs = X[1:]
    XtX = Xs.T @ Xs
    corr = np.array([0.0, T * (Dvu - (Ouv / Ovv) * Dvv)])
    b = np.linalg.solve(XtX, Xs.T @ ystar - corr)
    return float(b[1])


def johansen_trace(y, x, k_ar_diff: int = None) -> float:
    """Bivariate rank-0 trace statistic, restricted constant (johansen_trace_n on [y, x])."""
    return float(johansen_trace_n(np.column_stack([y, x]), k_ar_diff)[0])


_CRIT_CACHE = {}
JOHANSEN_CRIT_REPS = 4000     # simulation draws for the null distribution (seeded; see registry)


def johansen_crit(T: int, level: float = 0.05, k_ar_diff: int = None, reps: int = JOHANSEN_CRIT_REPS) -> float:
    """(1 - level) quantile of the restricted-constant trace statistic under the null (two independent driftless
    random walks of length T), simulated with a fixed seed -- derived, not copied from a table."""
    key = (T, level, k_ar_diff, reps)
    if key not in _CRIT_CACHE:
        rng = np.random.default_rng(20261013)
        st = [johansen_trace(*np.cumsum(rng.normal(size=(T, 2)), axis=0).T, k_ar_diff=k_ar_diff) for _ in range(reps)]
        _CRIT_CACHE[key] = float(np.quantile(st, 1 - level))
    return _CRIT_CACHE[key]


def johansen_rejects(y, x, level: float = 0.05, k_ar_diff: int = None) -> bool:
    return johansen_trace(y, x, k_ar_diff) > johansen_crit(len(y), level, k_ar_diff)


# n-variate restricted-constant Johansen: moved to the core module johansen.py (production trio test, Ross 2026-10-25
# "yes to all"); re-exported here so the comparison arm and its tests keep their names.
from johansen import (JOHANSEN_T_GRID, johansen_crit_n, johansen_crit_n_interp,  # noqa: E402,F401
                      johansen_rank_restricted, johansen_trace_n)
