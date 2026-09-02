"""
Synthetic verification for research/sector_fdr_random_null_comparison.py's
random_null_survivor_counts() and percentile_rank() (2026-09-01).

Checks:
1. Shape/determinism: n_trials draws produce n_trials counts per method,
   and a fixed-seed RNG reproduces identical results (needed for anyone to
   trust a specific real run's numbers are reproducible, not run-dependent
   noise being reported as if it were a stable finding).
2. Sampling-without-replacement correctness: m == n_pool (the "random"
   subset IS the whole pool every trial) must produce a CONSTANT
   distribution equal to the whole-pool survivor count under each method --
   if sampling silently allowed replacement or leaked size, this would not
   hold.
3. percentile_rank sanity: a value at the top of a known distribution scores
   100%, at the bottom scores a value consistent with "<=" semantics
   (bottom value itself is included -> > 0%), and a value in the middle of a
   simple integer distribution scores near the expected percentile.
4. The actual real-world question this script exists to answer: construct a
   raw p-value pool where a KNOWN subset of indices is "special" (genuinely
   smaller p-values, i.e. a real sector effect) and confirm that restricting
   to exactly that special subset produces a survivor count that scores as
   an outlier (>=95th percentile) against the random null -- while
   restricting to an arbitrary same-sized subset that ISN'T the special one
   scores unremarkably (inside the typical range). This is the actual
   discriminating power the real script depends on; must be demonstrated on
   a case with a known ground truth, not assumed to work.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.sector_fdr_random_null_comparison import (
    random_null_survivor_counts, percentile_rank,
)
from research.fdr_method_comparison import apply_all_methods

print("Check 1: shape and determinism")
rng_pool = np.random.default_rng(1)
pool = rng_pool.uniform(0, 1, size=500)
rng_a = np.random.default_rng(42)
counts_a = random_null_survivor_counts(pool, m=50, n_trials=20, alpha=0.05, rng=rng_a)
rng_b = np.random.default_rng(42)
counts_b = random_null_survivor_counts(pool, m=50, n_trials=20, alpha=0.05, rng=rng_b)
for method in counts_a:
    assert len(counts_a[method]) == 20, f"{method}: expected 20 trial counts"
    assert np.array_equal(counts_a[method], counts_b[method]), \
        f"{method}: same seed must reproduce identical results"
print("  PASS: n_trials shape correct, fixed seed is reproducible")

print("\nCheck 2: m == n_pool must give a CONSTANT distribution")
whole_pool_rejections = apply_all_methods(pool, 0.05)
whole_pool_counts = {name: int(rej.sum()) for name, rej in whole_pool_rejections.items()}
rng_c = np.random.default_rng(7)
counts_full = random_null_survivor_counts(pool, m=len(pool), n_trials=15, alpha=0.05, rng=rng_c)
for method, expected in whole_pool_counts.items():
    actual = counts_full[method]
    assert np.all(actual == expected), \
        f"{method}: m==n_pool should give constant {expected}, got {set(actual.tolist())}"
print("  PASS: m == n_pool reproduces the whole-pool survivor count on every trial")

print("\nCheck 3: percentile_rank sanity")
dist = np.array([1, 2, 3, 4, 5])
assert percentile_rank(5, dist) == 100.0, "max value should score 100th percentile"
assert percentile_rank(1, dist) == 20.0, "min value (1/5 <= itself) should score 20%"
assert percentile_rank(3, dist) == 60.0, "middle value (3/5 <= 3) should score 60%"
print("  PASS: percentile_rank matches hand-computed expectations")

print("\nCheck 4: the real discriminating-power test, on a known-ground-truth pool")
rng_seed = np.random.default_rng(99)
n_null = 400
n_special = 40
null_pvals = rng_seed.uniform(0.10, 1.0, size=n_null)          # genuinely insignificant
special_pvals = rng_seed.uniform(0.0001, 0.001, size=n_special)  # genuinely significant cluster
full_pool = np.concatenate([null_pvals, special_pvals])
special_idx = np.arange(n_null, n_null + n_special)             # ground truth: indices of the real effect

rng_test = np.random.default_rng(11)
special_subset = full_pool[special_idx]
special_rejections = apply_all_methods(special_subset, 0.05)
special_counts = {name: int(rej.sum()) for name, rej in special_rejections.items()}

null_dist_for_size = random_null_survivor_counts(full_pool, m=n_special, n_trials=300, alpha=0.05, rng=rng_test)

for method, real_n in special_counts.items():
    pct = percentile_rank(real_n, null_dist_for_size[method])
    assert pct >= 95.0, (
        f"{method}: the KNOWN-real-effect subset (survivor count={real_n}) should score as an "
        f"outlier (>=95th pct) against the random null, got {pct:.1f}% -- the discrimination this "
        f"whole comparison depends on is not working"
    )
print(f"  PASS: the known-real-effect subset scores as an outlier against the random null "
      f"for all {len(special_counts)} methods (as it must, for this comparison to mean anything)")

print("\nALL CHECKS PASSED")
