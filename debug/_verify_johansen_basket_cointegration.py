"""
Synthetic verification for research/johansen_basket_cointegration.py's
johansen_rank() and build_third_leg_candidates() (2026-09-01).

Checks:
1. A basket of three INDEPENDENT random walks (no shared stochastic trend)
   must show Johansen rank 0 -- the null case, confirms the function isn't
   biased toward finding spurious cointegration.
2. A basket where two of the three series share a genuine common trend (the
   third is independent) must show rank >= 1 -- confirms real detection
   power on a known-true-positive case, at a sample size and noise level
   comparable to what a real ~250+ trading-day window would give.
3. build_third_leg_candidates(): confirms cross-sector pairs are excluded
   (no principled third-leg set), same-sector pairs get candidates capped at
   n_third_legs and sorted deterministically, and a pair's own symbols are
   never offered back as a third leg.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.johansen_basket_cointegration import johansen_rank, build_third_leg_candidates

print("Check 1: three independent random walks -> rank 0 (no spurious cointegration)")
rng = np.random.default_rng(0)
n_obs = 500
indep_walks = np.cumsum(rng.normal(0, 1, size=(n_obs, 3)), axis=0) + 100
rank_null = johansen_rank(indep_walks)
assert rank_null == 0, f"three independent random walks should show rank 0, got {rank_null}"
print(f"  PASS: independent-walks basket correctly shows rank 0")

print("\nCheck 2: two series share a common trend -> rank >= 1 (real detection power)")
rng2 = np.random.default_rng(1)
common_trend = np.cumsum(rng2.normal(0, 1, size=n_obs))
series_a = 100 + common_trend + rng2.normal(0, 0.3, size=n_obs)
series_b = 100 + common_trend + rng2.normal(0, 0.3, size=n_obs)
series_c = 100 + np.cumsum(rng2.normal(0, 1, size=n_obs))  # independent
cointegrated_basket = np.column_stack([series_a, series_b, series_c])
rank_real = johansen_rank(cointegrated_basket)
assert rank_real >= 1, f"a basket with a genuine shared trend should show rank>=1, got {rank_real}"
print(f"  PASS: basket with a genuine shared trend correctly shows rank={rank_real} >= 1")

print("\nCheck 3: build_third_leg_candidates()")
sector_map = {
    "A": "Utilities", "B": "Utilities", "C": "Utilities", "D": "Utilities", "E": "Utilities",
    "X": "Financials", "Y": "Energy",
}
universe_symbols = set(sector_map.keys())
confirmed = [("A", "B"), ("X", "Y")]  # A/B same-sector, X/Y cross-sector

triples = build_third_leg_candidates(confirmed, sector_map, universe_symbols, n_third_legs=2)
xy_triples = [t for t in triples if t[0] == "X" or t[1] == "X"]
assert len(xy_triples) == 0, "cross-sector pair X/Y must produce zero triples (no principled third leg)"
print("  PASS: cross-sector pair correctly excluded")

ab_triples = [t for t in triples if t[0] == "A" and t[1] == "B"]
assert len(ab_triples) == 2, f"A/B (same-sector, 3 other Utilities symbols) capped at n_third_legs=2, got {len(ab_triples)}"
third_legs = sorted(t[2] for t in ab_triples)
assert third_legs == ["C", "D"], f"expected the alphabetically-first 2 candidates [C, D], got {third_legs}"
assert "A" not in third_legs and "B" not in third_legs, "a pair's own symbols must never be offered as third legs"
print(f"  PASS: same-sector pair A/B correctly capped at 2 candidates, deterministic (C, D), "
      f"never offers back A or B")

print("\nALL CHECKS PASSED")
