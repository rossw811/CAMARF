"""
debug/_verify_crisis_regime_concentration_significance_test.py -- synthetic
checks for research/crisis_regime_concentration_significance_test.py, run
BEFORE trusting it against the real episode-clustering data.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.crisis_regime_concentration_significance_test import (
    top2_share_binomial_test, max2_share_monte_carlo,
)

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


print("Check 1: top2_share_binomial_test -- a null-consistent scenario (confirmations "
      "proportional to pair size) should NOT be significant")
# 4 episodes, sizes proportional exactly to confirmations -- top-2 share of pairs
# should equal top-2 share of confirmations, p-value should be large (not surprising).
sizes = np.array([1000, 3000, 500, 5500])  # shares: 0.10, 0.30, 0.05, 0.55
confirms = np.array([2, 6, 1, 11])         # exactly proportional, n=20 total
result = top2_share_binomial_test(sizes, confirms)
check("top-2 (episodes 1,3 by size -- the two largest) pair share is 0.85 (0.30+0.55)",
      abs(result["top2_pair_share"] - 0.85) < 1e-9)
check("expected-under-null confirmations for top-2 matches observed closely (proportional "
      "construction), p-value NOT small (not surprising)",
      result["p_value"] > 0.10)

print("Check 2: top2_share_binomial_test -- a genuinely concentrated scenario (matching the "
      "real pattern: 2 small-share episodes capturing almost all confirmations) IS significant")
sizes2 = np.array([4084, 962, 2253, 153, 143, 220, 2329, 497, 86, 314, 673, 1])
confirms2 = np.array([20, 0, 7, 0, 0, 0, 1, 0, 0, 0, 0, 1])  # matches the real data exactly
result2 = top2_share_binomial_test(sizes2, confirms2)
check("real-data-shaped scenario: top-2 confirmed count is 27 (episodes 0 and 1)",
      result2["top2_confirmed"] == 27)
check("real-data-shaped scenario registers as statistically significant (p < 0.05) -- "
      "27 confirmations concentrated in episodes covering only ~35% of pairs is surprising",
      result2["p_value"] < 0.05)

print("Check 3: max2_share_monte_carlo -- observed share equal to the null mean is NOT significant")
rng = np.random.default_rng(42)
sizes3 = np.array([100, 100, 100, 100, 100])  # equal-sized episodes
# Simulate what a "typical" draw looks like first to get a realistic non-extreme observed value.
probs3 = sizes3 / sizes3.sum()
typical_draw = rng.multinomial(50, probs3)
typical_max2_share = np.sort(typical_draw)[-2:].sum() / 50
result3 = max2_share_monte_carlo(sizes3, 50, typical_max2_share, n_sim=20_000, rng=rng)
check("a typical (non-extreme) draw's max-2 share does NOT register as significant (p > 0.05)",
      result3["p_value"] > 0.05)

print("Check 4: max2_share_monte_carlo -- a maximally extreme observed share (all confirmations "
      "in just 2 episodes) IS significant")
result4 = max2_share_monte_carlo(sizes3, 50, 1.0, n_sim=20_000, rng=np.random.default_rng(1))
check("max-2 share of 1.0 (100% concentration) registers as significant (p < 0.05) against "
      "5 equal-sized episodes",
      result4["p_value"] < 0.05)

print("Check 5: max2_share_monte_carlo -- reproducibility with a fixed seed")
r_a = max2_share_monte_carlo(sizes2, 29, 27 / 29, n_sim=10_000, rng=np.random.default_rng(7))
r_b = max2_share_monte_carlo(sizes2, 29, 27 / 29, n_sim=10_000, rng=np.random.default_rng(7))
check("identical seed produces identical p-value (deterministic, not flaky)",
      r_a["p_value"] == r_b["p_value"])

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
