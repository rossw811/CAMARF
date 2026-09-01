"""
research/gpu_batched_eg_fixed_lag.py -- benchmark/comparison-arm script, NOT the production
implementation (that lives in analysis.py::_batched_eg_fixed_lag_tstat, wired into
_rolling_coint_worker and expanding_coint_fraction, 2026-08-23). This script exists to answer
one question: does GPU help this specific operation? Real answer, benchmarked on CachyOS's RTX
4080 (docs/HANDOFF.md): NO -- plain CPU numpy batching alone gives 94.9x over the old statsmodels
loop at 20,000 windows, and GPU is actually SLOWER than CPU at every scale tested (0.6x at 20k
windows) because this closed-form 2-variable regression is overhead/memory-bound, not FLOP-bound
like the correlation-matrix core (analysis.py::_vectorized_pairwise_stats) where GPU genuinely
helps. That's why the production wiring in analysis.py has NO use_gpu parameter at all -- it
would just be dead weight for this operation.

Kept as a standing comparison-arm script (not deleted) so the "did we check GPU for this" question
has a verifiable, re-runnable answer rather than just a claim in a doc.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from statsmodels.tsa.stattools import coint, mackinnonp

import gpu_backend
from analysis import _batched_eg_fixed_lag_tstat  # the real, production CPU implementation


def batched_eg_fixed_lag_tstat_gpu_variant(a_windows: np.ndarray, b_windows: np.ndarray, use_gpu: bool = False) -> np.ndarray:
    """GPU-capable fork of the same math, for benchmarking only -- see module docstring for why
    this is NOT what production actually uses."""
    xp = gpu_backend.get_array_module(use_gpu)
    a = xp.asarray(a_windows, dtype=xp.float64)
    b = xp.asarray(b_windows, dtype=xp.float64)

    mean_a = a.mean(axis=1, keepdims=True)
    mean_b = b.mean(axis=1, keepdims=True)
    cov_ab = ((a - mean_a) * (b - mean_b)).sum(axis=1, keepdims=True)
    var_b = ((b - mean_b) ** 2).sum(axis=1, keepdims=True)
    beta1 = cov_ab / var_b
    alpha1 = mean_a - beta1 * mean_b
    resid = a - alpha1 - beta1 * b

    dy = resid[:, 1:] - resid[:, :-1]
    y_lag1 = resid[:, :-2]
    dy_lag1 = dy[:, :-1]
    dy_t = dy[:, 1:]

    Sxx1 = (y_lag1 * y_lag1).sum(axis=1)
    Sxx2 = (dy_lag1 * dy_lag1).sum(axis=1)
    Sx1x2 = (y_lag1 * dy_lag1).sum(axis=1)
    Sx1y = (y_lag1 * dy_t).sum(axis=1)
    Sx2y = (dy_lag1 * dy_t).sum(axis=1)

    det = Sxx1 * Sxx2 - Sx1x2 ** 2
    beta2 = (Sx1y * Sxx2 - Sx2y * Sx1x2) / det
    gamma = (Sxx1 * Sx2y - Sx1x2 * Sx1y) / det

    fitted = beta2[:, None] * y_lag1 + gamma[:, None] * dy_lag1
    resid2 = dy_t - fitted
    ssr = (resid2 * resid2).sum(axis=1)
    n_obs = y_lag1.shape[1]
    dof = n_obs - 2
    sigma2 = ssr / dof
    se_beta2 = xp.sqrt(sigma2 * Sxx2 / det)
    t_stat = beta2 / se_beta2

    return gpu_backend.to_numpy(t_stat)


def batched_eg_fixed_lag(a_windows: np.ndarray, b_windows: np.ndarray, use_gpu: bool = False):
    """Full (t_stat, pvalue) result, GPU-capable variant, for benchmarking."""
    t_stats = batched_eg_fixed_lag_tstat_gpu_variant(a_windows, b_windows, use_gpu=use_gpu)
    pvalues = np.array([mackinnonp(float(t), regression="c", N=2) for t in t_stats])
    return t_stats, pvalues


if __name__ == "__main__":
    rng = np.random.default_rng(3)
    n_windows, window_len = 2000, 252
    a_w = rng.standard_normal((n_windows, window_len)).cumsum(axis=1)
    b_w = a_w + rng.standard_normal((n_windows, window_len)) * 0.5

    t0 = time.time()
    t_prod = _batched_eg_fixed_lag_tstat(a_w, b_w)  # the REAL production function
    dt_prod = time.time() - t0

    t0 = time.time()
    t_gpu = batched_eg_fixed_lag_tstat_gpu_variant(a_w, b_w, use_gpu=True)
    dt_gpu = time.time() - t0

    t0 = time.time()
    t_loop = []
    for i in range(n_windows):
        t, p, _ = coint(a_w[i], b_w[i], trend="c", maxlag=1, autolag=None)
        t_loop.append(t)
    dt_loop = time.time() - t0
    t_loop = np.array(t_loop)

    print(f"n_windows={n_windows}, window_len={window_len}")
    print(f"statsmodels loop:              {dt_loop:.3f}s")
    print(f"production (CPU batched):      {dt_prod:.3f}s  -> {dt_loop/dt_prod:.1f}x vs loop")
    print(f"GPU variant ({'GPU' if gpu_backend.gpu_available() else 'CPU fallback'}):{' ' * 12}{dt_gpu:.3f}s  -> "
          f"{dt_loop/dt_gpu:.1f}x vs loop, {dt_prod/dt_gpu:.2f}x vs production-CPU")
    print(f"t_stat max abs diff (loop vs production): {np.max(np.abs(t_loop - t_prod)):.2e}")
    print(f"t_stat max abs diff (production vs GPU):  {np.max(np.abs(t_prod - t_gpu)):.2e}")
