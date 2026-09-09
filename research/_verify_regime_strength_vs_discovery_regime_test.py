"""
debug/_verify_regime_strength_vs_discovery_regime_test.py -- synthetic
checks for research/regime_strength_vs_discovery_regime_test.py, run BEFORE
trusting it against real segmentation/discovery data.
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.regime_strength_vs_discovery_regime_test import (
    strongest_span_per_pair, build_joined_table, chi_square_independence,
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


print("Check 1: strongest_span_per_pair -- picks the STRONGEST of multiple spans, not the "
      "first/last/average")
segments = pd.DataFrame([
    {"symbol_a": "A", "symbol_b": "B", "state": "coint", "strength": "weak"},
    {"symbol_a": "A", "symbol_b": "B", "state": "coint", "strength": "strong"},   # this one wins
    {"symbol_a": "A", "symbol_b": "B", "state": "coint", "strength": "moderate"},
    {"symbol_a": "C", "symbol_b": "D", "state": "coint", "strength": "moderate"},
    {"symbol_a": "E", "symbol_b": "F", "state": "not_coint", "strength": None},  # excluded entirely
])
result = strongest_span_per_pair(segments)
check("A/B correctly reduced to its STRONGEST span (strong, not weak or moderate)",
      result.set_index(["symbol_a", "symbol_b"]).loc[("A", "B"), "strength"] == "strong")
check("C/D (single span) keeps its own strength",
      result.set_index(["symbol_a", "symbol_b"]).loc[("C", "D"), "strength"] == "moderate")
check("E/F (no coint span at all) is correctly EXCLUDED, not included as NaN",
      ("E", "F") not in set(zip(result["symbol_a"], result["symbol_b"])))
check("exactly 2 pairs survive the reduction (A/B and C/D)", len(result) == 2)

print("Check 2: build_joined_table -- inner join drops pairs missing from EITHER source")
segments2 = pd.DataFrame([
    {"symbol_a": "A", "symbol_b": "B", "state": "coint", "strength": "strong"},
    {"symbol_a": "X", "symbol_b": "Y", "state": "coint", "strength": "weak"},  # no discovery-regime row
])
discovery2 = pd.DataFrame([
    {"symbol_a": "A", "symbol_b": "B", "first_regime": "crisis"},
    {"symbol_a": "P", "symbol_b": "Q", "first_regime": "calm"},  # no segment row
])
joined = build_joined_table(segments2, discovery2)
check("only A/B survives the inner join (present in both sources)", len(joined) == 1)
check("A/B's joined regime is 'crisis'", joined.iloc[0]["first_regime"] == "crisis")

print("Check 3: chi_square_independence -- a real, constructed dependency registers as "
      "significant")
dependent = pd.DataFrame({
    "first_regime": ["crisis"] * 30 + ["calm"] * 30,
    "strength": (["strong"] * 25 + ["weak"] * 5) + (["weak"] * 25 + ["strong"] * 5),
})
dep_result = chi_square_independence(dependent)
check("a real, strong constructed dependency between regime and strength IS significant "
      "(p < 0.05)", dep_result["p_value"] < 0.05)

print("Check 4: chi_square_independence -- independence (no real relationship) is NOT significant")
import numpy as np
rng = np.random.default_rng(0)
independent = pd.DataFrame({
    "first_regime": rng.choice(["crisis", "calm"], size=200),
    "strength": rng.choice(["strong", "moderate", "weak"], size=200),
})
indep_result = chi_square_independence(independent)
check("genuinely independent (random) regime/strength assignment is NOT significant (p > 0.05)",
      indep_result["p_value"] > 0.05)

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
