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


def johansen_trace_n(Y, k_ar_diff: int = None) -> np.ndarray:
    """Johansen trace statistics for ranks r = 0 .. n-1 of an (T x n) level matrix, RESTRICTED constant (constant
    inside the cointegrating relation -- Johansen's case 2, for price levels without trend; 2026-10-13: statsmodels'
    det_order=0 puts the constant outside with drift critical values and over-rejected 11-12% at a nominal 5% on
    driftless random walks at every T tried). trace(r) = -T * sum_{i > r} log(1 - lambda_i).
    Reduced-rank regression: R0 = residual of dY_t, R1 = residual of [Y_{t-1}, 1], both on k lagged differences."""
    from config import Config
    k = Config.ANALYSIS.JOHANSEN_K_AR_DIFF if k_ar_diff is None else k_ar_diff
    Y = np.asarray(Y, dtype=float)
    Y = Y.reshape(-1, 1) if Y.ndim == 1 else Y
    n = Y.shape[1]
    dY = np.diff(Y, axis=0)
    T = len(dY) - k
    Z0 = dY[k:]
    Z1 = np.column_stack([Y[k:-1], np.ones(T)])
    if k > 0:
        Z2 = np.column_stack([dY[k - j:len(dY) - j] for j in range(1, k + 1)])
        P2 = Z2 @ np.linalg.pinv(Z2)
        R0, R1 = Z0 - P2 @ Z0, Z1 - P2 @ Z1
    else:
        R0, R1 = Z0, Z1
    S00, S01, S11 = R0.T @ R0 / T, R0.T @ R1 / T, R1.T @ R1 / T
    M = np.linalg.solve(S11, S01.T) @ np.linalg.solve(S00, S01)
    lam = np.sort(np.clip(np.real(np.linalg.eigvals(M)), 0, 1 - 1e-12))[::-1][:n]
    tail = np.cumsum(np.log(1 - lam)[::-1])[::-1]          # tail[r] = sum_{i >= r} log(1 - lambda_i)
    return -T * tail


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


# Trio (n-variate) arm, DECISIONS_2026-10-21 #3. Under H0 rank = r the trace statistic's null depends on the m = n - r
# common stochastic trends, so its critical value is the rank-0 quantile for m independent driftless random walks.
_CRIT_N_CACHE = {}
JOHANSEN_T_GRID = (100, 200, 400, 800, 1600, 3200, 6400, 12800)   # response surface in 1/T between grid points


def johansen_crit_n(T: int, m: int, level: float = 0.05, k_ar_diff: int = None, reps: int = JOHANSEN_CRIT_REPS) -> float:
    """(1 - level) quantile of the restricted-constant rank-0 trace statistic on m independent driftless random walks
    of length T, simulated with a fixed seed (derived, not copied from a table)."""
    key = (T, m, level, k_ar_diff, reps)
    if key not in _CRIT_N_CACHE:
        rng = np.random.default_rng(20261021 + m)
        st = [johansen_trace_n(np.cumsum(rng.normal(size=(T, m)), axis=0), k_ar_diff)[0] for _ in range(reps)]
        _CRIT_N_CACHE[key] = float(np.quantile(st, 1 - level))
    return _CRIT_N_CACHE[key]


def johansen_crit_n_interp(T: int, m: int, level: float = 0.05, k_ar_diff: int = None,
                           reps: int = JOHANSEN_CRIT_REPS) -> float:
    """johansen_crit_n at any T: linear in 1/T between the two bracketing JOHANSEN_T_GRID points (outside the grid,
    the nearest one), so a real-data run needs len(grid) simulations per m instead of one per window length."""
    g = JOHANSEN_T_GRID
    if T <= g[0] or T >= g[-1]:
        return johansen_crit_n(g[0] if T <= g[0] else g[-1], m, level, k_ar_diff, reps)
    hi = next(t for t in g if t >= T)
    lo = g[g.index(hi) - 1]
    if hi == T:
        return johansen_crit_n(T, m, level, k_ar_diff, reps)
    c_lo, c_hi = johansen_crit_n(lo, m, level, k_ar_diff, reps), johansen_crit_n(hi, m, level, k_ar_diff, reps)
    w = (1 / lo - 1 / T) / (1 / lo - 1 / hi)
    return float(c_lo + w * (c_hi - c_lo))


def johansen_rank_restricted(Y, level: float = 0.05, k_ar_diff: int = None, crit=None) -> dict:
    """Sequential trace test, restricted constant: the rank is the first r whose trace(r) does not exceed the
    critical value for n - r trends (n if every one does). Returns rank, trace statistics, critical values."""
    crit = crit or johansen_crit_n_interp
    tr = johansen_trace_n(Y, k_ar_diff)
    n, T = len(tr), np.asarray(Y).shape[0]
    cv = np.array([crit(T, n - r, level, k_ar_diff) for r in range(n)])
    above = tr > cv
    rank = int(np.argmin(above)) if not above.all() else n
    return {"rank": rank, "trace": tr, "crit": cv}
