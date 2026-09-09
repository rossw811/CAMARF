"""
debug/_verify_diversification_basket_test.py -- synthetic ground-truth checks for
research/diversification_basket_test.py, BEFORE trusting it against real universe data.

Run: python debug/_verify_diversification_basket_test.py
(Fully synthetic/offline -- no real data or WRDS connection needed.)
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.diversification_basket_test import diversification_ratio, latest_state_symbols

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


print("Check 1: diversification_ratio -- a basket of PERFECTLY UNCORRELATED assets (independent "
      "noise) shows a real diversification benefit (ratio > 1), the textbook Markowitz result")
rng = np.random.default_rng(0)
n = 500
uncorrelated = pd.DataFrame({f"S{i}": rng.normal(0, 0.02, n) for i in range(10)})
r1 = diversification_ratio(uncorrelated)
check(f"uncorrelated basket diversification_ratio ({r1['diversification_ratio']:.3f}) is "
      f"materially > 1 (real benefit from combining independent noise)",
      r1["diversification_ratio"] > 2.0)
check(f"mean pairwise correlation ({r1['mean_pairwise_corr']:.3f}) is near zero, "
      f"matching the independent construction", abs(r1["mean_pairwise_corr"]) < 0.15)

print("Check 2: diversification_ratio -- a basket of PERFECTLY CORRELATED assets (identical "
      "series, scaled) shows NO diversification benefit (ratio ~= 1)")
base = rng.normal(0, 0.02, n)
correlated = pd.DataFrame({f"S{i}": base * (1 + i * 0.01) for i in range(10)})
r2 = diversification_ratio(correlated)
check(f"perfectly-correlated basket diversification_ratio ({r2['diversification_ratio']:.3f}) "
      f"is close to 1 (no real diversification benefit)", abs(r2["diversification_ratio"] - 1.0) < 0.15)
check(f"mean pairwise correlation ({r2['mean_pairwise_corr']:.3f}) is close to 1.0, matching "
      f"the perfectly-correlated construction", r2["mean_pairwise_corr"] > 0.95)

print("Check 3: diversification_ratio -- uncorrelated basket's ratio is materially HIGHER than "
      "correlated basket's ratio (the core comparison this whole test exists to make)")
check(f"uncorrelated ratio ({r1['diversification_ratio']:.3f}) > correlated ratio "
      f"({r2['diversification_ratio']:.3f})", r1["diversification_ratio"] > r2["diversification_ratio"])

print("Check 4: diversification_ratio -- fewer than 2 usable symbols (e.g. all-NaN columns "
      "dropped) returns NaN rather than a fabricated ratio")
mostly_nan = pd.DataFrame({"S1": [np.nan] * n, "S2": rng.normal(0, 0.02, n)})
r4 = diversification_ratio(mostly_nan)
check("only 1 usable symbol after dropping all-NaN columns -> NaN ratio, not a crash or "
      "fabricated value", np.isnan(r4["diversification_ratio"]) and r4["n_symbols_used"] == 1)

print("Check 5: latest_state_symbols -- correctly identifies each pair's MOST RECENT state, not "
      "an earlier one, when a pair has multiple transitions")
transitions = pd.DataFrame({
    "symbol_a": ["A", "A", "B", "C"],
    "symbol_b": ["X", "X", "Y", "Z"],
    "transition_date": pd.to_datetime(["2020-01-01", "2021-06-01", "2020-01-01", "2020-01-01"]),
    "new_state": ["coint", "not_coint", "coint", "not_coint"],  # A/X: coint THEN not_coint (latest wins)
})
result5 = latest_state_symbols(transitions)
check("A/X's LATEST state (not_coint, from the 2021 row) is what's used, not the earlier 2020 "
      "coint row -- A and X appear in the not_coint symbol pool", "A" in result5["not_coint"] and "X" in result5["not_coint"])
check("A/X does NOT also appear in the coint pool (only the latest state counts, not both)",
      "A" not in result5["coint"] and "X" not in result5["coint"])
check("B/Y (single coint transition, no later override) correctly appears in the coint pool",
      "B" in result5["coint"] and "Y" in result5["coint"])
check("C/Z (single not_coint transition) correctly appears in the not_coint pool",
      "C" in result5["not_coint"] and "Z" in result5["not_coint"])

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
