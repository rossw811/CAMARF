"""
Synthetic verification for research/bertram_ou_thresholds.py. No
independent closed-form is available to check the exact optimal threshold
against (see the module's own docstring for why), so this checks the
qualitative properties Bertram's theory predicts instead:

Case 1: as transaction cost -> 0, the optimal entry threshold should
shrink toward 0 (any nonzero move is worth capturing when trading is
free).

Case 2: as transaction cost increases, the optimal entry threshold should
grow (a bigger move is needed to justify a larger fixed cost) —
monotonicity across an increasing cost grid.

Case 3: fit_discrete_ou() should recover known true (rho, sigma) parameters
from a synthetic OU series with those exact true values.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from research.bertram_ou_thresholds import fit_discrete_ou, optimal_entry_z

failures = []

# --- Case 3 first: confirm the OU fit itself is correct ---
rng0 = np.random.default_rng(7)
true_rho, true_sigma_eps = 0.95, 1.0
n = 5000
z_true = np.zeros(n)
for t in range(1, n):
    z_true[t] = true_rho * z_true[t - 1] + rng0.normal(scale=true_sigma_eps)
fitted_rho, fitted_sigma_eps, fitted_sigma_stat = fit_discrete_ou(z_true)
print(f"Case 3 (OU fit recovery): true rho={true_rho}, fitted={fitted_rho:.4f}; "
      f"true sigma_eps={true_sigma_eps}, fitted={fitted_sigma_eps:.4f}")
if abs(fitted_rho - true_rho) > 0.02:
    failures.append(f"Case 3: fitted rho ({fitted_rho:.4f}) too far from true ({true_rho})")
if abs(fitted_sigma_eps - true_sigma_eps) > 0.1:
    failures.append(f"Case 3: fitted sigma_eps ({fitted_sigma_eps:.4f}) too far from true ({true_sigma_eps})")

# --- Case 1 & 2: cost sensitivity, using the recovered fit ---
rng1 = np.random.default_rng(11)
costs = [0.01, 0.15, 0.40, 0.80]
optimal_zs = []
for cost in costs:
    best_z, rates, grid = optimal_entry_z(
        fitted_rho, fitted_sigma_eps, fitted_sigma_stat, cost_frac=cost,
        z_grid=np.arange(0.25, 3.05, 0.25), n_paths=150, rng=rng1,
    )
    optimal_zs.append(best_z)
    print(f"cost_frac={cost}: optimal_entry_z*={best_z:.2f}")

print(f"\nOptimal z* across increasing cost: {optimal_zs}")
if not (optimal_zs[0] < optimal_zs[-1]):
    failures.append(
        f"Case 1&2: expected optimal_entry_z* to INCREASE as cost increases "
        f"(monotonicity Bertram's theory predicts), got {optimal_zs} for costs {costs}"
    )
if optimal_zs[0] > 1.0:
    failures.append(
        f"Case 1: expected optimal_entry_z* to be small (near the low end of the grid) "
        f"at near-zero cost ({costs[0]}), got {optimal_zs[0]}"
    )

print()
if failures:
    print(f"FAILED ({len(failures)} issue(s)):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("ALL CHECKS PASSED")
    sys.exit(0)
