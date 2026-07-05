"""
Synthetic verification of research/strategy_risk_precision.py's
binomial_sharpe() formula, checked directly against Monte Carlo simulation
rather than trusted from memory alone.

For several (precision, n_bets) combinations, simulate many realizations
of n_bets independent +1/-1 bets with win probability p, compute the
EMPIRICAL per-bet Sharpe ratio (mean/std of the realized bet outcomes)
across a large number of simulated portfolios, and compare its average to
the formula's closed-form prediction.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from research.strategy_risk_precision import binomial_sharpe

failures = []
rng = np.random.default_rng(11)

test_cases = [(0.55, 50), (0.6, 100), (0.7, 20), (0.5, 100)]

for p, n_bets in test_cases:
    sr_per_bet_formula, sr_annualized_formula = binomial_sharpe(p, n_bets)

    # Monte Carlo: simulate a LARGE number of independent bets directly
    # (not "portfolios of n_bets" — the per-bet Sharpe is a property of a
    # single bet's own win/loss distribution, independent of n_bets; n_bets
    # only enters via the sqrt(n) annualization scaling, checked separately
    # below).
    n_sim = 2_000_000
    outcomes = rng.random(n_sim) < p
    pnl = np.where(outcomes, 1.0, -1.0)
    empirical_sr_per_bet = pnl.mean() / pnl.std(ddof=1)

    print(f"p={p}, n={n_bets}: formula per-bet SR={sr_per_bet_formula:.4f}, "
          f"Monte Carlo empirical SR={empirical_sr_per_bet:.4f}")
    if abs(sr_per_bet_formula - empirical_sr_per_bet) > 0.01:
        failures.append(
            f"p={p}: formula per-bet SR ({sr_per_bet_formula:.4f}) doesn't match "
            f"Monte Carlo ({empirical_sr_per_bet:.4f}) within tolerance"
        )

    # Annualization scaling check: SR_annualized should equal SR_per_bet * sqrt(n)
    # exactly (this part is definitional, not something Monte Carlo needs to
    # re-derive, but confirm the code actually implements it as such).
    expected_annualized = sr_per_bet_formula * np.sqrt(n_bets)
    if abs(sr_annualized_formula - expected_annualized) > 1e-9:
        failures.append(
            f"p={p}, n={n_bets}: annualized SR ({sr_annualized_formula}) != "
            f"per-bet SR * sqrt(n) ({expected_annualized})"
        )

# Sanity: p=0.5 (coin flip) should give exactly SR=0
sr_half, _ = binomial_sharpe(0.5, 100)
if abs(sr_half) > 1e-9:
    failures.append(f"p=0.5 should give exactly SR=0 (no edge), got {sr_half}")

print()
if failures:
    print(f"FAILED ({len(failures)} issue(s)):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("ALL CHECKS PASSED")
    sys.exit(0)
