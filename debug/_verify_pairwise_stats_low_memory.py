"""
debug/_verify_pairwise_stats_low_memory.py -- synthetic verification that
UniverseFilter._vectorized_pairwise_stats(low_memory=True) produces bit-exact
identical count/var_x/var_y/corr_raw to the default (low_memory=False) path,
for the real 2026-08-17 memory fix (k-BAHC OOM near-miss at N=17,324).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from analysis import UniverseFilter

checks = []


def check(name, cond):
    checks.append((name, cond))
    print(f"{'PASS' if cond else 'FAIL'}: {name}")


np.random.seed(42)
n, T = 60, 400
x = np.random.randn(n, T)
# Inject some NaN gaps and a couple of flat (zero-variance) rows for realism
x[5, :100] = np.nan
x[12, 200:250] = np.nan
x[20, :] = 5.0  # flat row, zero variance

full = UniverseFilter._vectorized_pairwise_stats(x, low_memory=False)
lowm = UniverseFilter._vectorized_pairwise_stats(x, low_memory=True)

count_f, mean_x_f, mean_y_f, var_x_f, var_y_f, cov_xy_f, corr_f, den_f = full
count_l, mean_x_l, mean_y_l, var_x_l, var_y_l, cov_xy_l, corr_l, den_l = lowm

check("count identical", np.array_equal(count_f, count_l))
check("var_x bit-exact", np.allclose(var_x_f, var_x_l, equal_nan=True, atol=0, rtol=0))
check("var_y bit-exact", np.allclose(var_y_f, var_y_l, equal_nan=True, atol=0, rtol=0))
check("corr_raw bit-exact", np.allclose(corr_f, corr_l, equal_nan=True, atol=0, rtol=0))
check("low_memory mean_x/mean_y/cov_xy/den are None", mean_x_l is None and mean_y_l is None and cov_xy_l is None and den_l is None)
check("tuple shapes match (8 elements both)", len(full) == 8 and len(lowm) == 8)

# End-to-end: _pairwise_corr (which now always uses low_memory=True internally) must match
# a reference computed via the old default (full) path applied identically.
corr_via_function = UniverseFilter._pairwise_corr(x)
corr_ref_from_full, den_valid_ref = UniverseFilter._fix_ambiguous_variance_cells(
    x, count_f, var_x_f, var_y_f, corr_f.copy(), min_overlap=30
)
corr_ref = np.where(den_valid_ref, corr_ref_from_full, np.nan)
corr_ref[count_f < 30] = np.nan
np.fill_diagonal(corr_ref, 1.0)
check("_pairwise_corr end-to-end matches reference built from the full path",
      np.allclose(corr_via_function, corr_ref, equal_nan=True, atol=0, rtol=0))

n_fail = sum(1 for _, c in checks if not c)
print(f"\n{len(checks) - n_fail}/{len(checks)} checks passed")
sys.exit(1 if n_fail else 0)
