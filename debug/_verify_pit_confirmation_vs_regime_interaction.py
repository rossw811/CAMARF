"""Synthetic proof for research/pit_confirmation_vs_regime_interaction.py --
confirms the pair-orientation-agnostic join and the two-proportion test
math against known synthetic cases before trusting the real result."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from pit_confirmation_vs_regime_interaction import build_joined_table, two_proportion_test

n_checks = 0
n_passed = 0


def check(name, cond):
    global n_checks, n_passed
    n_checks += 1
    status = "PASS" if cond else "FAIL"
    if cond:
        n_passed += 1
    print(f"[{status}] {name}")


regime_df = pd.DataFrame([
    {"symbol_a": "A", "symbol_b": "B", "first_regime": "crisis", "confirmed": True},
    {"symbol_a": "C", "symbol_b": "D", "first_regime": "crisis", "confirmed": False},
    {"symbol_a": "E", "symbol_b": "F", "first_regime": "calm", "confirmed": False},
    {"symbol_a": "G", "symbol_b": "H", "first_regime": "calm", "confirmed": False},
])
# PIT confirms A/B (same order) and F/E (REVERSED order vs regime_df's E/F).
pit_df = pd.DataFrame([
    {"symbol_a": "A", "symbol_b": "B"},
    {"symbol_a": "F", "symbol_b": "E"},
])

joined = build_joined_table(regime_df, pit_df)
print(joined)

# --- 1. Same-order pair (A/B) correctly matched ---
check("same-order pair (A/B) matched as pit_confirmed",
      bool(joined.loc[(joined.symbol_a == "A") & (joined.symbol_b == "B"), "pit_confirmed"].iloc[0]))

# --- 2. Reversed-order pair (E/F vs PIT's F/E) STILL matched -- orientation-agnostic join ---
check("reversed-order pair (E/F vs PIT's F/E) matched despite order flip",
      bool(joined.loc[(joined.symbol_a == "E") & (joined.symbol_b == "F"), "pit_confirmed"].iloc[0]))

# --- 3. Non-matching pair (C/D) correctly NOT matched ---
check("non-matching pair (C/D) correctly not flagged pit_confirmed",
      not bool(joined.loc[(joined.symbol_a == "C") & (joined.symbol_b == "D"), "pit_confirmed"].iloc[0]))
check("non-matching pair (G/H) correctly not flagged pit_confirmed",
      not bool(joined.loc[(joined.symbol_a == "G") & (joined.symbol_b == "H"), "pit_confirmed"].iloc[0]))

# --- 4. two_proportion_test: known case with an obvious, large effect ---
big_df = pd.DataFrame({
    "group": ["x"] * 100 + ["y"] * 100,
    "pit_confirmed": [True] * 80 + [False] * 20 + [True] * 20 + [False] * 80,
})
r = two_proportion_test(big_df, "group", "x", "y")
print(r)
check("two_proportion_test recovers the correct proportions (0.8 vs 0.2)",
      np.isclose(r["p_a"], 0.8) and np.isclose(r["p_b"], 0.2))
check("two_proportion_test finds a hugely significant difference (p < 1e-10) for an 0.8 vs 0.2 split",
      r["p_value"] < 1e-10)

# --- 5. two_proportion_test: identical proportions -> p-value near 1 (no effect) ---
null_df = pd.DataFrame({
    "group": ["x"] * 100 + ["y"] * 100,
    "pit_confirmed": ([True] * 30 + [False] * 70) * 2,
})
r_null = two_proportion_test(null_df, "group", "x", "y")
check("two_proportion_test on IDENTICAL proportions gives z=0, p=1 (no false-positive effect)",
      np.isclose(r_null["z"], 0.0, atol=1e-9) and np.isclose(r_null["p_value"], 1.0, atol=1e-9))

# --- 6. two_proportion_test: empty group handled without crashing ---
empty_df = pd.DataFrame({"group": ["x"] * 10, "pit_confirmed": [True] * 5 + [False] * 5})
r_empty = two_proportion_test(empty_df, "group", "x", "nonexistent_group")
check("empty comparison group returns NaN p-value without crashing",
      r_empty["p_value"] != r_empty["p_value"])  # NaN != NaN

print(f"\n{n_passed}/{n_checks} checks passed")
sys.exit(0 if n_passed == n_checks else 1)
