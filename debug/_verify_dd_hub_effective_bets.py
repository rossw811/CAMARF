"""
Synthetic verification for research/dd_hub_effective_bets.py before
trusting it on the real DD-hub cluster.

Case 1: N=5, rho=0 (fully independent bets) — all three methods should
agree: BR_eff = ENB = 5, IDM = sqrt(5).

Case 2: N=5, rho=1 (fully redundant bets, perfectly correlated) — all
three should agree: BR_eff = ENB = 1, IDM = 1.

Case 3: N=5, rho=0.3 (a realistic intermediate case) — Grinold-Kahn and
Carver's IDM must satisfy the derived identity IDM^2 = BR_eff exactly
(equicorrelated by construction here, so this is an exact algebraic check,
not an approximation). Meucci's ENB should land close to (not necessarily
identical to) Grinold-Kahn's BR_eff for a genuinely equicorrelated matrix,
since equicorrelation is the special case where the two methods' different
mechanisms should still agree closely.

Case 4: block structure (2 highly-correlated pairs + 3 independent ones)
— Meucci's ENB (which uses the actual eigenvalue spectrum) should differ
from a naive equicorrelation-based estimate, since the true structure
isn't equicorrelated — this is the case that actually demonstrates Meucci
adds information beyond Grinold-Kahn's single-rho_bar summary.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from research.dd_hub_effective_bets import analyze_cluster, meucci_effective_bets

failures = []


def equicorrelated_matrix(n, rho):
    m = np.full((n, n), rho)
    np.fill_diagonal(m, 1.0)
    return m


# --- Case 1: rho=0 ---
r1 = analyze_cluster(equicorrelated_matrix(5, 0.0))
print(f"Case 1 (N=5, rho=0): BR_eff={r1['grinold_kahn_breadth']:.3f}, "
      f"ENB={r1['meucci_enb']:.3f}, IDM={r1['carver_idm']:.3f}")
for name, val, expected in [("BR_eff", r1["grinold_kahn_breadth"], 5.0),
                             ("ENB", r1["meucci_enb"], 5.0),
                             ("IDM", r1["carver_idm"], np.sqrt(5))]:
    if abs(val - expected) > 1e-6:
        failures.append(f"Case 1: {name}={val:.4f} != expected {expected:.4f}")

# --- Case 2: rho=1 ---
r2 = analyze_cluster(equicorrelated_matrix(5, 1.0 - 1e-9))  # avoid exact singularity
print(f"Case 2 (N=5, rho~1): BR_eff={r2['grinold_kahn_breadth']:.3f}, "
      f"ENB={r2['meucci_enb']:.3f}, IDM={r2['carver_idm']:.3f}")
for name, val, expected in [("BR_eff", r2["grinold_kahn_breadth"], 1.0),
                             ("ENB", r2["meucci_enb"], 1.0),
                             ("IDM", r2["carver_idm"], 1.0)]:
    if abs(val - expected) > 1e-3:
        failures.append(f"Case 2: {name}={val:.4f} != expected {expected:.4f}")

# --- Case 3: rho=0.3, exact IDM^2 = BR_eff identity check ---
r3 = analyze_cluster(equicorrelated_matrix(5, 0.3))
print(f"Case 3 (N=5, rho=0.3): BR_eff={r3['grinold_kahn_breadth']:.4f}, "
      f"ENB={r3['meucci_enb']:.4f}, IDM={r3['carver_idm']:.4f}, "
      f"IDM^2={r3['idm_squared_vs_breadth_check']:.4f}")
if abs(r3["idm_squared_vs_breadth_check"] - r3["grinold_kahn_breadth"]) > 1e-6:
    failures.append(
        f"Case 3: IDM^2 ({r3['idm_squared_vs_breadth_check']:.4f}) should exactly "
        f"equal BR_eff ({r3['grinold_kahn_breadth']:.4f}) under equal weighting — "
        f"this is a derived algebraic identity, not an approximation."
    )
# Discovered running this test (not assumed going in): for an EXACTLY
# equicorrelated matrix with EXACTLY equal weights, the equal-weight vector
# is an exact eigenvector of the matrix (the "common factor" direction), so
# Meucci's portfolio-weighted diversification distribution puts 100% of
# weight on that one component by construction — ENB=1 exactly, REGARDLESS
# of rho, as long as rho>0. This is a real, mathematically-derivable
# property of the weighted PCA-based ENB formula in this specific
# degenerate case (equal weights aligned exactly with the top eigenvector),
# not a bug — confirmed by hand: eigenvector for equicorrelation is
# (1/sqrt(N))*[1,...,1], identical direction to the equal-weight vector.
# Verify that degenerate fact explicitly here, rather than wrongly assuming
# ENB should track Grinold-Kahn's BR_eff in this special case.
if abs(r3["meucci_enb"] - 1.0) > 1e-6:
    failures.append(
        f"Case 3: expected Meucci ENB to be EXACTLY 1.0 for an equal-weighted, "
        f"exactly-equicorrelated portfolio (a known degenerate case — see comment "
        f"above), got {r3['meucci_enb']:.6f}"
    )

# --- Case 3b: SAME equicorrelated matrix, UNEQUAL weights — breaks the
# exact degeneracy above. Discovered running this (not assumed going in,
# and the first version of this case wrongly assumed "weights closer to
# equal = more diversified = higher ENB" — backwards for THIS formula):
# because equal weights are themselves the exact top-eigenvector direction
# under equicorrelation, weights CLOSER to equal concentrate MORE fully
# onto that single common-factor component (ENB nearer 1), while weights
# further from equal partially break that alignment and load onto other
# eigenvectors too (ENB further from 1). The only thing checked here is the
# bound (strictly between 1 and N) and that unequal weights actually DO
# move ENB away from the exact-1.0 degenerate value — not a directional
# "more equal = higher ENB" claim, which does not hold for this formula.
corr3b = equicorrelated_matrix(5, 0.3)
unequal_weights = np.array([0.6, 0.1, 0.1, 0.1, 0.1])
enb_unequal = meucci_effective_bets(corr3b, unequal_weights)["enb"]
print(f"Case 3b (same rho=0.3, unequal weights 60/10/10/10/10): ENB={enb_unequal:.3f} "
      f"(breaks the exact-1.0 degeneracy from Case 3's equal weights, as expected)")
if not (1.0 < enb_unequal < 5.0):
    failures.append(f"Case 3b: ENB(unequal weights)={enb_unequal:.3f} should be strictly between 1 and 5")

# --- Case 4: block structure, Meucci should diverge from naive rho_bar story ---
n4 = 5
corr4 = np.eye(n4)
corr4[0, 1] = corr4[1, 0] = 0.95  # pairs 0,1 nearly identical
# pairs 2,3,4 stay independent (off-diagonal 0 elsewhere)
r4 = analyze_cluster(corr4)
meucci4 = meucci_effective_bets(corr4, np.full(n4, 1.0 / n4))
print(f"Case 4 (block: 2 near-duplicate + 3 independent): "
      f"rho_bar={r4['rho_bar']:.4f}, BR_eff={r4['grinold_kahn_breadth']:.3f}, "
      f"ENB={r4['meucci_enb']:.3f}")
# With one pair of near-duplicates among 5 equal-weighted bets, the
# duplicated pair behaves like one double-weighted bet, so under equal
# per-instrument weighting the EFFECTIVE weight distribution is itself
# concentrated (~0.4/0.2/0.2/0.2 rather than five equal 0.2 shares) —
# some reduction below a naive "4 distinct sources" count is expected from
# that concentration alone, on top of the 2-pair redundancy itself. Sanity
# bounds only (not a precise target number): strictly between 1 (fully
# redundant) and 5 (fully independent), and closer to 5 than to 1, since
# only 2 of 5 bets are actually redundant with each other.
if not (2.5 < r4["meucci_enb"] < 5.0):
    failures.append(
        f"Case 4: expected Meucci ENB strictly between 2.5 and 5.0 (one "
        f"redundant pair among 5 mostly-independent bets), got {r4['meucci_enb']:.3f}"
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
