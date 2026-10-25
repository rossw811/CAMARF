"""johansen.py -- Johansen trace test with a RESTRICTED constant (Johansen's case 2: constant inside the cointegrating
relation, the specification for price levels without trend). Production's trio test since 2026-10-25 (Ross, "yes to
all", after the comparison arm: research/johansen_trio_arm_comparison.py).

Why not statsmodels: coint_johansen's det_order -1 (no deterministic term; production until 2026-10-25) has almost no
power once the cointegrating relation has an intercept, as log-price relations do (3.3% vs 100% on simulated trios),
and det_order 0 is the UNRESTRICTED constant with drift critical values, which over-rejects driftless random walks
(11.7% bivariate, 7.7% trios at a nominal 5%). debug/_verify_johansen_trio_restricted.py, ERRATA "Johansen trio
specification".

Critical values: simulated (seeded) per number of common trends m and series length T on JOHANSEN_T_GRID, linear in
1/T between grid points; production reads the committed table research/johansen_restricted_crit.csv (built by
research/build_johansen_restricted_crit.py) instead of simulating in every worker.
"""
import os
from functools import lru_cache

import numpy as np
import pandas as pd

JOHANSEN_CRIT_REPS = 4000
CRIT_TABLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "research", "johansen_restricted_crit.csv")
MAXEIG_TABLE = CRIT_TABLE.replace("_crit.csv", "_maxeig_crit.csv")   # max-eigenvalue statistic, same draws
_STAT = {"trace": lambda Y, k: johansen_trace_n(Y, k), "maxeig": lambda Y, k: johansen_maxeig_n(Y, k)}


def johansen_eigs_n(Y, k_ar_diff: int = None):
    """Eigenvalues lambda_1 >= .. >= lambda_n of an (T x n) level matrix and the effective T, RESTRICTED constant (constant
    inside the cointegrating relation -- Johansen's case 2, for price levels without trend; 2026-10-13: statsmodels'
    det_order=0 puts the constant outside with drift critical values and over-rejected 11-12% at a nominal 5% on
    driftless random walks at every T tried).
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
        # residuals by least squares, never the T x T projection matrix (2026-10-25: at T = 12,800 that matrix is
        # ~1.3 GB per call -- the critical-value build ran the Surface out of memory)
        R0 = Z0 - Z2 @ np.linalg.lstsq(Z2, Z0, rcond=None)[0]
        R1 = Z1 - Z2 @ np.linalg.lstsq(Z2, Z1, rcond=None)[0]
    else:
        R0, R1 = Z0, Z1
    S00, S01, S11 = R0.T @ R0 / T, R0.T @ R1 / T, R1.T @ R1 / T
    M = np.linalg.solve(S11, S01.T) @ np.linalg.solve(S00, S01)
    lam = np.sort(np.clip(np.real(np.linalg.eigvals(M)), 0, 1 - 1e-12))[::-1][:n]
    return lam, T


def johansen_trace_n(Y, k_ar_diff: int = None) -> np.ndarray:
    """Johansen trace statistics for ranks r = 0 .. n-1, restricted constant: trace(r) = -T * sum_{i > r} log(1 - lambda_i)
    (johansen_eigs_n)."""
    lam, T = johansen_eigs_n(Y, k_ar_diff)
    tail = np.cumsum(np.log(1 - lam)[::-1])[::-1]          # tail[r] = sum_{i >= r} log(1 - lambda_i)
    return -T * tail


def johansen_maxeig_n(Y, k_ar_diff: int = None) -> np.ndarray:
    """Max-eigenvalue statistics for ranks r = 0 .. n-1, restricted constant: maxeig(r) = -T * log(1 - lambda_{r+1}),
    H0 rank r against rank r + 1. Same eigenvalues as johansen_trace_n; null quantiles from MAXEIG_TABLE."""
    lam, T = johansen_eigs_n(Y, k_ar_diff)
    return -T * np.log(1 - lam)


# n-variate critical values and rank (DECISIONS_2026-10-21 #3). Under H0 rank = r the trace statistic's null depends on the m = n - r
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


def johansen_rank_restricted(Y, level: float = 0.05, k_ar_diff: int = None, crit=None, stat: str = "trace") -> dict:
    """Sequential test, restricted constant: the rank is the first r whose statistic (trace, or max-eigenvalue with
    stat="maxeig") does not exceed the critical value for n - r trends (n if every one does). Returns rank, the
    statistics (key "trace" for either) and critical values. `crit` must match `stat` (default: trace simulation)."""
    if crit is None and stat != "trace":
        raise ValueError("pass the max-eigenvalue critical values (crit_from_table(..., stat='maxeig'))")
    crit = crit or johansen_crit_n_interp
    tr = _STAT[stat](Y, k_ar_diff)
    n, T = len(tr), np.asarray(Y).shape[0]
    cv = np.array([crit(T, n - r, level, k_ar_diff) for r in range(n)])
    above = tr > cv
    rank = int(np.argmin(above)) if not above.all() else n
    return {"rank": rank, "trace": tr, "crit": cv}



@lru_cache(maxsize=2)
def _table(stat: str = "trace") -> pd.DataFrame:
    return pd.read_csv({"trace": CRIT_TABLE, "maxeig": MAXEIG_TABLE}[stat])


def crit_from_table(T: int, m: int, level: float = 0.05, k_ar_diff: int = None, stat: str = "trace") -> float:
    """Critical value from the committed table (trace, or max-eigenvalue with stat="maxeig"), linear in 1/T between
    grid points (nearest grid point outside it). Same response surface as johansen_crit_n_interp, without simulating."""
    t = _table(stat)
    g = t[(t["m"] == m) & np.isclose(t["level"], level)].sort_values("T")
    if g.empty:
        raise ValueError(f"no tabulated critical value for m={m}, level={level} ({stat} table)")
    Ts, cs = g["T"].to_numpy(float), g["crit"].to_numpy(float)
    if T <= Ts[0]:
        return float(cs[0])
    if T >= Ts[-1]:
        return float(cs[-1])
    return float(np.interp(1.0 / T, (1.0 / Ts)[::-1], cs[::-1]))


def johansen_test(Y, level: float = 0.05, k_ar_diff: int = None) -> dict:
    """Production entry point: rank (sequential trace), trace and critical value at rank 0, from the table."""
    r = johansen_rank_restricted(Y, level, k_ar_diff, crit=lambda T, m, lev, k: crit_from_table(T, m, lev, k))
    return {"rank": r["rank"], "trace0": float(r["trace"][0]), "crit0": float(r["crit"][0]),
            "trace": r["trace"], "crit": r["crit"]}
