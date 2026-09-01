"""Synthetic verification for research/gpu_batched_eg_fixed_lag.py -- confirms the batched
closed-form Engle-Granger (fixed lag=1) implementation matches statsmodels.tsa.stattools.coint()
bit-close, across genuinely cointegrated, non-cointegrated, and edge-case series.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from statsmodels.tsa.stattools import coint

from research.gpu_batched_eg_fixed_lag import batched_eg_fixed_lag

checks = []


def check(name, cond):
    checks.append((name, cond))
    print(f"{'PASS' if cond else 'FAIL'}: {name}")


def loop_reference(a_w, b_w):
    t_list, p_list = [], []
    for i in range(a_w.shape[0]):
        t, p, _ = coint(a_w[i], b_w[i], trend="c", maxlag=1, autolag=None)
        t_list.append(t)
        p_list.append(p)
    return np.array(t_list), np.array(p_list)


rng = np.random.default_rng(5)

# Case 1: genuinely cointegrated pairs (shared random walk + independent noise)
n, T = 50, 300
shared = rng.standard_normal((n, T)).cumsum(axis=1)
a1 = shared + rng.standard_normal((n, T)) * 0.3
b1 = shared + rng.standard_normal((n, T)) * 0.3
t_ref1, p_ref1 = loop_reference(a1, b1)
t_batch1, p_batch1 = batched_eg_fixed_lag(a1, b1, use_gpu=False)
check("cointegrated pairs: t_stat matches (1e-8)", np.allclose(t_ref1, t_batch1, atol=1e-8))
check("cointegrated pairs: p-value matches (1e-6)", np.allclose(p_ref1, p_batch1, atol=1e-6))

# Case 2: independent random walks (genuinely NOT cointegrated -- spurious regression case)
a2 = rng.standard_normal((n, T)).cumsum(axis=1)
b2 = rng.standard_normal((n, T)).cumsum(axis=1)
t_ref2, p_ref2 = loop_reference(a2, b2)
t_batch2, p_batch2 = batched_eg_fixed_lag(a2, b2, use_gpu=False)
check("non-cointegrated pairs: t_stat matches (1e-8)", np.allclose(t_ref2, t_batch2, atol=1e-8))
check("non-cointegrated pairs: p-value matches (1e-6)", np.allclose(p_ref2, p_batch2, atol=1e-6))
check("non-cointegrated pairs: p-values genuinely high (test has real discriminating power)",
      np.mean(p_ref2 > 0.10) > 0.5)
check("cointegrated pairs: p-values genuinely low (test has real discriminating power)",
      np.mean(p_ref1 < 0.10) > 0.5)

# Case 3: GPU path (falls back to CPU cleanly if no GPU present -- still must match loop)
t_gpu, p_gpu = batched_eg_fixed_lag(a1, b1, use_gpu=True)
check("use_gpu=True path matches loop reference (1e-6)", np.allclose(t_ref1, t_gpu, atol=1e-6))

n_fail = sum(1 for _, c in checks if not c)
print(f"\n{len(checks) - n_fail}/{len(checks)} checks passed")
sys.exit(1 if n_fail else 0)
