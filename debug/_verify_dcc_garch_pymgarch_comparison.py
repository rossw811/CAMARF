"""
Synthetic verification for research/dcc_garch_pymgarch_comparison.py's
make_synthetic_dcc_panel() and rmse_vs_target() (2026-09-01).

Checks:
1. The synthetic panel's OWN realized correlation actually matches its
   target schedule -- if the panel-generation math were wrong, both DCC
   methods could "agree" while both correctly detecting a WRONG ground
   truth, and nobody would notice. Checked directly via realized pairwise
   correlation in the baseline window vs. the crisis window, before either
   DCC method ever touches the data.
2. rmse_vs_target() is 0 for a perfect match and > 0 for a known
   mismatch (sanity check on the scoring function itself).
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.dcc_garch_pymgarch_comparison import make_synthetic_dcc_panel, rmse_vs_target

print("Check 1: synthetic panel's realized correlation matches its target schedule")
returns_df, true_rho = make_synthetic_dcc_panel(
    n_series=4, n_days=500, seed=0, crisis_start=250, crisis_end=350,
    baseline_rho=0.15, crisis_rho=0.75,
)
baseline_block = returns_df.iloc[:250]
crisis_block = returns_df.iloc[250:350]
baseline_realized = baseline_block.corr().to_numpy()
crisis_realized = crisis_block.corr().to_numpy()
iu = np.triu_indices(4, k=1)
baseline_avg = baseline_realized[iu].mean()
crisis_avg = crisis_realized[iu].mean()
print(f"  Baseline window realized avg pairwise corr: {baseline_avg:.3f} (target 0.15)")
print(f"  Crisis window realized avg pairwise corr:   {crisis_avg:.3f} (target 0.75)")
assert 0.05 < baseline_avg < 0.30, f"baseline realized corr {baseline_avg} not close to target 0.15"
assert 0.60 < crisis_avg < 0.90, f"crisis realized corr {crisis_avg} not close to target 0.75"
assert crisis_avg > baseline_avg + 0.3, "crisis window must be MUCH more correlated than baseline"
print("  PASS: synthetic panel's realized correlation genuinely follows its known schedule")

print("\nCheck 2: rmse_vs_target() sanity")
T, n = 100, 3
perfect = np.zeros((T, n, n))
target = np.full(T, 0.5)
for t in range(T):
    perfect[t] = np.array([[1.0, 0.5, 0.5], [0.5, 1.0, 0.5], [0.5, 0.5, 1.0]])
rmse_perfect = rmse_vs_target(perfect, target)
assert rmse_perfect < 1e-9, f"perfect match should give RMSE~0, got {rmse_perfect}"
print(f"  PASS: perfect match gives RMSE={rmse_perfect:.6f} (~0)")

wrong = np.zeros((T, n, n))
for t in range(T):
    wrong[t] = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
rmse_wrong = rmse_vs_target(wrong, target)
assert rmse_wrong > 0.4, f"a 0.0-vs-0.5 mismatch should give a large RMSE, got {rmse_wrong}"
print(f"  PASS: known mismatch (0.0 fitted vs 0.5 target) gives RMSE={rmse_wrong:.3f} (large, as expected)")

print("\nALL CHECKS PASSED")
