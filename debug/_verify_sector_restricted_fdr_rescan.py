"""
Synthetic verification for research/sector_restricted_fdr_rescan.py's
restrict_to_same_sector() (2026-07-20). Constructs a small candidate-pair
DataFrame with known same-sector, cross-sector, and missing-tag rows, and
confirms the restriction keeps exactly the same-sector rows -- both symbols
present in the sector map AND matching -- dropping cross-sector pairs and
pairs where either symbol has no known tag (not silently treating "unknown"
as "same," which would be a real correctness bug: an unmapped pair could be
cross-sector and get wrongly included).

Also confirms the expected downstream property this whole rescan exists to
test: restricting m shrinks Bonferroni's per-test bar (alpha/m), so a pair
that fails Bonferroni at large m can newly survive at the smaller, restricted
m -- constructs an exact case where this happens, so the real run's "does
shrinking m recover any known pair" logic is trusted, not assumed.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.sector_restricted_fdr_rescan import restrict_to_same_sector
from research.fdr_method_comparison import apply_all_methods

df = pd.DataFrame({
    "symbol_a": ["A", "C", "E", "G", "I"],
    "symbol_b": ["B", "D", "F", "H", "J"],
    "pvalue":   [0.01, 0.02, 0.03, 0.04, 0.05],
})
sector_map = {
    "A": "Utilities", "B": "Utilities",      # same sector -> keep
    "C": "Financials", "D": "Energy",        # cross-sector -> drop
    "E": "Health Care", "F": "Health Care",  # same sector -> keep
    "G": "Materials",                        # H missing entirely -> drop
    # I, J both missing -> drop
}

restricted = restrict_to_same_sector(df, sector_map)
kept_pairs = set(zip(restricted["symbol_a"], restricted["symbol_b"]))
expected = {("A", "B"), ("E", "F")}

check1 = kept_pairs == expected
print(f"Check 1 (keeps only true same-sector, matched-tag pairs): "
      f"{'PASS' if check1 else 'FAIL'}  got={kept_pairs} expected={expected}")

# --- Check 2: shrinking m can newly pass a pair under fixed Bonferroni ---
# Construct m=1000 p-values where one target pair sits just above the full-m
# Bonferroni bar (alpha/1000) but comfortably below the restricted-m bar
# (alpha/20) once 980 of the 1000 are excluded as cross-sector.
alpha = 0.05
big_m = 1000
target_p = 0.0004  # between alpha/1000=5e-5 and alpha/20=2.5e-3
rest_pvals = np.full(big_m, 0.9)  # 999 non-significant fillers
rest_pvals[0] = target_p

full_rej = apply_all_methods(rest_pvals, alpha)
restricted_pvals = rest_pvals[:20]  # simulate the same-sector-only subset (m=20)
restricted_rej = apply_all_methods(restricted_pvals, alpha)

check2a = not full_rej["fixed_bonferroni"][0]   # fails at full m
check2b = restricted_rej["fixed_bonferroni"][0]  # passes at restricted m
print(f"\nCheck 2a (target pair fails Bonferroni at full m=1000): "
      f"{'PASS' if check2a else 'FAIL'}")
print(f"Check 2b (SAME pair passes Bonferroni at restricted m=20): "
      f"{'PASS' if check2b else 'FAIL'}")

ok = check1 and check2a and check2b
print("\nPASS" if ok else "\nFAIL")
sys.exit(0 if ok else 1)
