"""
debug/_verify_crisis_regime_cluster_bootstrap_test.py -- synthetic checks for
research/crisis_regime_cluster_bootstrap_test.py, run BEFORE trusting it
against the real episode/pairs data.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.crisis_regime_cluster_bootstrap_test import cluster_bootstrap_confirmation_rate

passed = 0
failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}")
        failed += 1


print("Check 1: uniform episodes (all identical rate) -- bootstrap should center tightly on "
      "that rate with a narrow CI")
sizes = np.array([1000] * 10)
confirms = np.array([20] * 10)  # exactly 2% in every episode
rates = cluster_bootstrap_confirmation_rate(sizes, confirms, n_boot=5000, rng=np.random.default_rng(1))
check("bootstrap mean rate is close to the true uniform rate (0.02)",
      abs(rates.mean() - 0.02) < 0.002)
check("bootstrap CI is narrow when every episode has the identical rate (low std)",
      rates.std() < 0.005)

print("Check 2: one dominant episode (matches the real pattern) -- bootstrap should show wide "
      "variance, since resampling can miss the dominant episode entirely")
sizes2 = np.array([4084, 962, 2253, 153, 143, 220, 2329, 497, 86, 314, 673, 1])
confirms2 = np.array([20, 0, 7, 0, 0, 0, 1, 0, 0, 0, 0, 1])  # matches real data
rates2 = cluster_bootstrap_confirmation_rate(sizes2, confirms2, n_boot=5000, rng=np.random.default_rng(2))
check("bootstrap mean rate is close to the observed pooled rate (29/11715 ~= 0.00248)",
      abs(rates2.mean() - 29 / 11715) < 0.001)
check("bootstrap distribution has REAL spread (std > 0), reflecting only 12 independent units "
      "-- a naive pair-level test would show near-zero spread at this n",
      rates2.std() > 0.0005)
check("bootstrap CI lower bound can reach zero (some resamples miss both dominant episodes "
      "entirely) -- direct evidence the pooled p-value overstates confidence",
      np.percentile(rates2, 2.5) < 0.0005)

print("Check 3: reproducibility with a fixed seed")
r_a = cluster_bootstrap_confirmation_rate(sizes2, confirms2, n_boot=2000, rng=np.random.default_rng(9))
r_b = cluster_bootstrap_confirmation_rate(sizes2, confirms2, n_boot=2000, rng=np.random.default_rng(9))
check("identical seed produces identical bootstrap draws (deterministic, not flaky)",
      np.array_equal(r_a, r_b))

print("Check 4: a single episode (n=1) -- bootstrap should always resample that same episode, "
      "rate is degenerate (always the true rate, zero variance)")
sizes3 = np.array([500])
confirms3 = np.array([10])
rates3 = cluster_bootstrap_confirmation_rate(sizes3, confirms3, n_boot=1000, rng=np.random.default_rng(3))
check("single-episode case: bootstrap rate is degenerate at the true rate (0.02), zero variance",
      np.allclose(rates3, 0.02))

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
