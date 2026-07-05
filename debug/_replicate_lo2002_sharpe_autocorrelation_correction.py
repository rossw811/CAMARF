"""
Synthetic replication of Lo (2002), "The Statistics of Sharpe Ratios"
(Financial Analysts Journal 58(4), 36-52) -- BEFORE using this as a basis
for evaluating CAMARF's own reported Sharpe ratios (backtest.py:740, :804,
both currently plain sqrt(N)-annualized with no autocorrelation term).

Lo's correction: for a return series with lag-1..q autocorrelations rho_k,
the correct q-period-scaled Sharpe is

    SR(q) = SR(1) * q / sqrt(eta(q))
    eta(q) = q + 2 * sum_{k=1}^{q-1} (q-k) * rho_k

(the multi-period variance scaling factor), vs. the naive iid assumption
SR(q)_naive = SR(1) * sqrt(q). When rho_k > 0, eta(q) > q, so SR(q)_naive
OVERSTATES the true SR(q). When rho_k < 0, the opposite: SR(q)_naive
UNDERSTATES the true value. This script validates the formula's DIRECTION
and rough magnitude in BOTH cases on synthetic AR(1) data -- it deliberately
does NOT assume which direction applies to CAMARF's own real portfolio P&L,
since that depends on the empirical sign of realized daily-P&L
autocorrelation (a distinct, not-yet-checked question -- see the
interpretation note at the end of this script's output).

Checks:
  1. rho=0 (true iid returns): SR(q) via the full formula should equal the
     naive sqrt(q) scaling almost exactly (eta(q) should collapse to q).
  2. rho>0 (momentum-like, positive serial correlation in P&L): naive
     Sharpe should OVERSTATE the corrected Sharpe, with the overstatement
     growing as rho and q both grow -- Lo's own paper example uses monthly
     hedge-fund returns with high rho showing up to ~65% overstatement at
     annual (q=12) scaling; this replication checks the same qualitative
     direction and an economically similar order of magnitude, not an
     exact percentage match (different rho/q/T than Lo's specific dataset).
  3. rho<0 (mean-reversion-like, negative serial correlation in P&L):
     naive Sharpe should UNDERSTATE the corrected Sharpe -- the opposite
     direction from (2), confirming the correction is genuinely
     sign-sensitive and not just "always shrinks the naive number."
  4. Numerical cross-check: the closed-form eta(q) formula matches the
     variance of an actual simulated q-period AGGREGATED return series
     (sum of q consecutive 1-period returns) computed directly from the
     AR(1) process's theoretical autocovariance, not just the formula
     re-stated in code.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

RNG = np.random.default_rng(11)
T = 5000  # long series for stable rho/variance estimates
Q = 12    # e.g. monthly->annual scaling, matches Lo's own worked example


def simulate_ar1_returns(t: int, rho: float, mu: float = 0.01, sigma: float = 0.04) -> np.ndarray:
    """AR(1) return series with a given lag-1 autocorrelation `rho`, mean mu,
    unconditional std sigma (matching Lo's own hedge-fund-return scale)."""
    e = RNG.normal(0, sigma * np.sqrt(1 - rho ** 2), t)
    r = np.zeros(t)
    r[0] = mu + e[0]
    for i in range(1, t):
        r[i] = mu + rho * (r[i - 1] - mu) + e[i]
    return r


def theoretical_eta(rho: float, q: int) -> float:
    """eta(q) = q + 2*sum_{k=1}^{q-1}(q-k)*rho^k for an AR(1) process,
    using rho_k = rho^k (the AR(1) autocorrelation function)."""
    total = q
    for k in range(1, q):
        total += 2 * (q - k) * (rho ** k)
    return total


def naive_and_corrected_sharpe(r: np.ndarray, q: int) -> tuple:
    mu_hat = r.mean()
    sigma_hat = r.std(ddof=1)
    sr1 = mu_hat / sigma_hat
    rho_hat = np.corrcoef(r[:-1], r[1:])[0, 1]
    eta_hat = theoretical_eta(rho_hat, q)
    sr_q_naive = sr1 * np.sqrt(q)
    sr_q_corrected = sr1 * q / np.sqrt(eta_hat)
    return sr_q_naive, sr_q_corrected, rho_hat


def main():
    failures = []

    # --- 1: rho=0, eta(q) should collapse to q ---
    eta_zero = theoretical_eta(0.0, Q)
    if not np.isclose(eta_zero, Q, atol=1e-9):
        failures.append(f"eta(q) with rho=0 should equal q={Q} exactly, got {eta_zero}")

    r_iid = simulate_ar1_returns(T, rho=0.0)
    sr_naive_iid, sr_corr_iid, rho_hat_iid = naive_and_corrected_sharpe(r_iid, Q)
    if not np.isclose(sr_naive_iid, sr_corr_iid, rtol=0.05):
        failures.append(
            f"rho~0 case: naive and corrected Sharpe should nearly coincide, got "
            f"naive={sr_naive_iid:.3f} corrected={sr_corr_iid:.3f} (rho_hat={rho_hat_iid:.3f})"
        )

    # --- 2: rho>0, naive should OVERSTATE ---
    r_pos = simulate_ar1_returns(T, rho=0.3)
    sr_naive_pos, sr_corr_pos, rho_hat_pos = naive_and_corrected_sharpe(r_pos, Q)
    if not (sr_naive_pos > sr_corr_pos):
        failures.append(
            f"rho>0 case: naive Sharpe should OVERSTATE the corrected value, got "
            f"naive={sr_naive_pos:.3f} <= corrected={sr_corr_pos:.3f} (rho_hat={rho_hat_pos:.3f})"
        )
    overstatement_pct = (sr_naive_pos / sr_corr_pos - 1) * 100 if sr_corr_pos != 0 else float("nan")
    if not (overstatement_pct > 10):
        failures.append(
            f"rho>0 overstatement too small to be economically meaningful: "
            f"{overstatement_pct:.1f}% at rho_hat={rho_hat_pos:.3f}, q={Q}"
        )

    # --- 3: rho<0, naive should UNDERSTATE ---
    r_neg = simulate_ar1_returns(T, rho=-0.3)
    sr_naive_neg, sr_corr_neg, rho_hat_neg = naive_and_corrected_sharpe(r_neg, Q)
    if not (sr_naive_neg < sr_corr_neg):
        failures.append(
            f"rho<0 case: naive Sharpe should UNDERSTATE the corrected value, got "
            f"naive={sr_naive_neg:.3f} >= corrected={sr_corr_neg:.3f} (rho_hat={rho_hat_neg:.3f})"
        )
    understatement_pct = (sr_corr_neg / sr_naive_neg - 1) * 100 if sr_naive_neg != 0 else float("nan")

    # --- 4: eta(q) formula matches direct simulation of aggregated q-period variance ---
    rho_check = 0.4
    r_check = simulate_ar1_returns(20000, rho=rho_check)
    q_period_sums = r_check[: len(r_check) - len(r_check) % Q].reshape(-1, Q).sum(axis=1)
    empirical_var_ratio = q_period_sums.var(ddof=1) / (r_check.var(ddof=1))
    theoretical_ratio = theoretical_eta(rho_check, Q)
    if not np.isclose(empirical_var_ratio, theoretical_ratio, rtol=0.15):
        failures.append(
            f"eta(q) formula mismatch vs. direct simulation: theoretical={theoretical_ratio:.3f}, "
            f"empirical (from actual q-period sums)={empirical_var_ratio:.3f}"
        )

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)

    print("Lo (2002) Sharpe autocorrelation correction replication: PASSED")
    print(f"  rho~0   : naive SR(q)={sr_naive_iid:.3f}  corrected SR(q)={sr_corr_iid:.3f}  "
          f"(should nearly coincide)")
    print(f"  rho={rho_hat_pos:+.2f} : naive SR(q)={sr_naive_pos:.3f}  corrected SR(q)={sr_corr_pos:.3f}  "
          f"naive OVERSTATES by {overstatement_pct:.1f}%")
    print(f"  rho={rho_hat_neg:+.2f} : naive SR(q)={sr_naive_neg:.3f}  corrected SR(q)={sr_corr_neg:.3f}  "
          f"naive UNDERSTATES by {understatement_pct:.1f}%")
    print(f"  eta(q) formula vs. direct q-period-sum simulation at rho={rho_check}: "
          f"{theoretical_ratio:.3f} (theory) vs {empirical_var_ratio:.3f} (simulated)")
    print()
    print("  IMPORTANT -- this script validates the FORMULA's direction and magnitude on")
    print("  synthetic data only. It does NOT tell us which direction applies to CAMARF's")
    print("  own reported 5.24 OOS Sharpe -- that depends on the empirical sign of")
    print("  autocorrelation in the ACTUAL daily portfolio P&L series (trades_layer1_*.parquet),")
    print("  which has not been checked. Note this is a distinct question from the OU spread's")
    print("  own mean-reversion (Development.md's existing note that OU spreads have rho<0")
    print("  is about the SPREAD level, not necessarily the realized daily P&L of the traded")
    print("  strategy, which can show either sign depending on entry/exit clustering and regime")
    print("  persistence). The next real step is computing lag-1 autocorrelation directly on")
    print("  CAMARF's own daily portfolio P&L and applying this same eta(q) correction to the")
    print("  actual reported Sharpe -- flagged as a Tier 1 comparison-arm item, not done here.")


if __name__ == "__main__":
    main()
