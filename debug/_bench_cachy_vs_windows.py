"""Cross-machine benchmark: identical CAMARF-representative compute run on Windows and CachyOS.
Not a synthetic microbenchmark -- exercises the actual production functions
(chunked_pearson_matrix, _batched_eg_fixed_lag_tstat) at fixed, reproducible scale.
"""
import platform
import sys
import time

import numpy as np

sys.path.insert(0, ".")
from analysis import UniverseFilter, _batched_eg_fixed_lag_tstat

print(f"platform: {platform.platform()}")
print(f"machine: {platform.machine()}, processor: {platform.processor()}")
print(f"python: {sys.version.split()[0]}")

# --- Benchmark 1: correlation matrix (production scale, N=1660, matches CAMARF's real universe) ---
rng = np.random.default_rng(42)
n, t_len = 1660, 1000
returns = rng.standard_normal((n, t_len)).astype(np.float64)
mask = rng.random((n, t_len)) < 0.02
returns[mask] = np.nan

t0 = time.time()
corr = UniverseFilter.chunked_pearson_matrix(returns, batch_size=1500)
dt_corr = time.time() - t0
print(f"\n[1] chunked_pearson_matrix, N={n}: {dt_corr:.3f}s (mean_corr={np.nanmean(corr):.4f})")

# --- Benchmark 2: batched EG fixed-lag (production-representative rolling-window scale) ---
n_windows, window_len = 20000, 252
a_w = rng.standard_normal((n_windows, window_len)).cumsum(axis=1)
b_w = a_w + rng.standard_normal((n_windows, window_len)) * 0.5

t0 = time.time()
t_stats = _batched_eg_fixed_lag_tstat(a_w, b_w)
dt_eg = time.time() - t0
print(f"[2] batched EG fixed-lag, n_windows={n_windows}: {dt_eg:.3f}s "
      f"(mean_t_stat={np.nanmean(t_stats):.3f})")

# --- Benchmark 3: raw BLAS throughput (isolates emulation/architecture effects from algorithm) ---
a = rng.standard_normal((2000, 2000))
b = rng.standard_normal((2000, 2000))
t0 = time.time()
for _ in range(5):
    c = a @ b
dt_blas = time.time() - t0
print(f"[3] raw BLAS matmul (2000x2000, x5): {dt_blas:.3f}s")

print(f"\nTOTAL: {dt_corr + dt_eg + dt_blas:.3f}s")
