"""Synthetic verification for EigenportfolioDecomposer._eigendecompose's use_gpu param,
added 2026-08-23 (second GPU target from the 2026-08-20 audit, closing it out alongside the
correlation core). Safe to run on any machine -- falls back to CPU with a warning if no GPU.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from analysis import EigenportfolioDecomposer

checks = []


def check(name, cond):
    checks.append((name, cond))
    print(f"{'PASS' if cond else 'FAIL'}: {name}")


rng = np.random.default_rng(11)
n, t_len = 200, 500
factors = rng.standard_normal((3, t_len))
loadings = rng.standard_normal((n, 3))
returns = loadings @ factors + rng.standard_normal((n, t_len)) * 0.3
corr = np.corrcoef(returns)
# realistic NaN entries (insufficient overlap), same shape _eigendecompose already handles
corr[5, 17] = corr[17, 5] = np.nan

eig_cpu, vec_cpu, lam_cpu, k_cpu = EigenportfolioDecomposer._eigendecompose(corr, t_len, use_gpu=False)
eig_gpu, vec_gpu, lam_gpu, k_gpu = EigenportfolioDecomposer._eigendecompose(corr, t_len, use_gpu=True)

check("eigenvalues match CPU vs GPU (1e-6)", np.allclose(eig_cpu, eig_gpu, atol=1e-6, rtol=1e-6))
check("lambda_plus (MP threshold) identical", abs(lam_cpu - lam_gpu) < 1e-9)
check("K (factor count) identical", k_cpu == k_gpu)
check("eigenvalues descending", np.all(np.diff(eig_cpu) <= 1e-9))
# Eigenvector SIGN can differ between backends (eigh has no sign convention) -- compare
# subspace via |v_cpu . v_gpu| ~ 1 per eigenvector, not raw equality.
dots = [abs(np.dot(vec_cpu[:, i], vec_gpu[:, i])) for i in range(vec_cpu.shape[1])]
check("eigenvectors span the same subspace (|dot|~1 per column)",
      all(d > 1 - 1e-4 for d in dots))

n_fail = sum(1 for _, c in checks if not c)
print(f"\n{len(checks) - n_fail}/{len(checks)} checks passed")
sys.exit(1 if n_fail else 0)
