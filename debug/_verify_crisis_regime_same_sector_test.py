"""
debug/_verify_crisis_regime_same_sector_test.py -- synthetic checks for
research/crisis_regime_same_sector_test.py, run BEFORE trusting it against
real GICS-tagged pair data.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.crisis_regime_same_sector_test import (
    tag_same_sector, crisis_vs_calm_reappearance_by_sector_match,
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


print("Check 1: tag_same_sector -- correctly labels same-sector, cross-sector, and "
      "untagged (unknown) pairs")
gics_tags = pd.DataFrame([
    {"symbol": "AAPL", "sector": "Information Technology"},
    {"symbol": "MSFT", "sector": "Information Technology"},
    {"symbol": "JPM", "sector": "Financials"},
])
pairs = pd.DataFrame([
    {"symbol_a": "AAPL", "symbol_b": "MSFT"},   # same sector
    {"symbol_a": "AAPL", "symbol_b": "JPM"},    # cross sector
    {"symbol_a": "AAPL", "symbol_b": "GVKEY123_01W"},  # untagged leg -- unknown
])
tagged = tag_same_sector(pairs, gics_tags)
check("AAPL/MSFT correctly tagged same_sector=True",
      tagged.iloc[0]["same_sector"] == True)
check("AAPL/JPM correctly tagged same_sector=False (cross-sector)",
      tagged.iloc[1]["same_sector"] == False)
check("AAPL/GVKEY123_01W (one leg untagged) is NaN, not silently coerced to False",
      pd.isna(tagged.iloc[2]["same_sector"]))

print("Check 2: crisis_vs_calm_reappearance_by_sector_match -- real, constructed gaps in "
      "BOTH subsets register as significant when n is adequate")
rng = np.random.default_rng(0)
n_per_group = 200
same_sector_pairs = pd.DataFrame({
    "same_sector": [True] * (2 * n_per_group),
    "first_regime": ["crisis"] * n_per_group + ["calm"] * n_per_group,
    "reappears_in_different_regime": (
        (rng.random(n_per_group) < 0.9).tolist() + (rng.random(n_per_group) < 0.5).tolist()
    ),
})
cross_sector_pairs = pd.DataFrame({
    "same_sector": [False] * (2 * n_per_group),
    "first_regime": ["crisis"] * n_per_group + ["calm"] * n_per_group,
    "reappears_in_different_regime": (
        (rng.random(n_per_group) < 0.9).tolist() + (rng.random(n_per_group) < 0.5).tolist()
    ),
})
combined = pd.concat([same_sector_pairs, cross_sector_pairs], ignore_index=True)
results = crisis_vs_calm_reappearance_by_sector_match(combined)
check("same_sector subset registers as significant (real constructed 0.9 vs 0.5 gap)",
      not results["same_sector"]["insufficient_n"] and results["same_sector"]["p_value"] < 0.05)
check("cross_sector subset registers as significant (real constructed 0.9 vs 0.5 gap)",
      not results["cross_sector"]["insufficient_n"] and results["cross_sector"]["p_value"] < 0.05)

print("Check 3: crisis_vs_calm_reappearance_by_sector_match -- insufficient n is flagged, "
      "not silently tested anyway")
thin = pd.DataFrame({
    "same_sector": [True] * 4 + [False] * 200,
    "first_regime": (["crisis"] * 2 + ["calm"] * 2) + ["crisis"] * 100 + ["calm"] * 100,
    "reappears_in_different_regime": [True, False, True, True] + [True] * 100 + [False] * 100,
})
thin_results = crisis_vs_calm_reappearance_by_sector_match(thin)
check("same_sector (only 4 rows) correctly flagged insufficient_n=True, not tested",
      thin_results["same_sector"]["insufficient_n"] is True)
check("cross_sector (200 rows) has enough n, insufficient_n=False",
      thin_results["cross_sector"]["insufficient_n"] is False)

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
