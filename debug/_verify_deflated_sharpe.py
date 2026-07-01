"""
Synthetic verification of deflated_sharpe.py's core math
(expected_max_sharpe_null / deflated_sharpe_ratio) against known-answer
cases from Bailey & Lopez de Prado (2014), BEFORE trusting it on real
CAMARF backtest numbers — per this project's standing discipline that a
statistical computation gets a synthetic reproduction first.

Checks:
  1. N=1 trial -> SR0*=0 regardless of cross-trial variance (no multiple-
     testing correction should apply with only one trial).
  2. Monotonicity: SR0* strictly increases as N grows (holding variance
     fixed) -> DSR strictly decreases for the same SR_hat/T/skew/kurtosis.
  3. Exact arithmetic check: skew=0, kurtosis=1 collapses the denominator
     to exactly 1, so z_stat = (SR_hat - SR0*) * sqrt(T-1) — verified
     against manual arithmetic, not just "runs without crashing."
  4. expected_max_sharpe_null(N, var) reproduces the textbook formula
     sqrt(var) * [(1-gamma)*Phi^-1(1-1/N) + gamma*Phi^-1(1-1/(N*e))]
     computed independently via scipy.stats.norm.ppf in this test file
     (not by re-importing the same implementation).
  5. Higher SR_hat (holding T, skew, kurtosis, N, var fixed) strictly
     increases DSR — a basic sanity property the formula must satisfy.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from scipy import stats as sp_stats

from deflated_sharpe import expected_max_sharpe_null, deflated_sharpe_ratio, _EULER_MASCHERONI


def main():
    failures = []

    # --- 1. N=1 -> SR0*=0 ---
    sr0_n1 = expected_max_sharpe_null(n_trials=1, var_sr_across_trials=0.5)
    if sr0_n1 != 0.0:
        failures.append(f"N=1 should give SR0*=0, got {sr0_n1}")

    # --- 2. Monotonicity in N ---
    var = 0.02
    sr0_values = [expected_max_sharpe_null(n, var) for n in [2, 5, 10, 50, 100, 500]]
    if not all(sr0_values[i] < sr0_values[i + 1] for i in range(len(sr0_values) - 1)):
        failures.append(f"SR0* not monotonically increasing in N: {sr0_values}")

    # sr_hat/t_obs deliberately modest here (not CAMARF's real annualized-scale
    # Sharpe) so the z-statistic stays in the CDF's sensitive range across all
    # tested N — a saturated 0.0/1.0 CDF can't reveal monotonicity by
    # construction, independent of whether the underlying formula is correct.
    dsr_values = [
        deflated_sharpe_ratio(sr_hat=0.3, t_obs=20, skew=0.0, kurtosis=3.0,
                               n_trials=n, var_sr_across_trials=var)
        for n in [2, 5, 10, 50, 100, 500]
    ]
    if not all(dsr_values[i] > dsr_values[i + 1] for i in range(len(dsr_values) - 1)):
        failures.append(f"DSR not monotonically decreasing in N: {dsr_values}")

    # --- 3. Exact arithmetic with skew=0, kurtosis=1 (denominator collapses to 1) ---
    sr_hat, t_obs, n_trials, var2 = 0.8, 100, 10, 0.03
    sr0 = expected_max_sharpe_null(n_trials, var2)
    expected_z = (sr_hat - sr0) * np.sqrt(t_obs - 1) / 1.0  # denom = sqrt(1-0+0*0.64) = 1
    expected_dsr = sp_stats.norm.cdf(expected_z)
    actual_dsr = deflated_sharpe_ratio(sr_hat, t_obs, skew=0.0, kurtosis=1.0,
                                        n_trials=n_trials, var_sr_across_trials=var2)
    if not np.isclose(actual_dsr, expected_dsr, atol=1e-10):
        failures.append(
            f"Exact arithmetic mismatch: expected {expected_dsr}, got {actual_dsr}"
        )

    # --- 4. expected_max_sharpe_null reproduces textbook formula independently ---
    n_check, var_check = 37, 0.015
    z1 = sp_stats.norm.ppf(1 - 1.0 / n_check)
    z2 = sp_stats.norm.ppf(1 - 1.0 / (n_check * np.e))
    expected_sr0 = np.sqrt(var_check) * ((1 - _EULER_MASCHERONI) * z1 + _EULER_MASCHERONI * z2)
    actual_sr0 = expected_max_sharpe_null(n_check, var_check)
    if not np.isclose(actual_sr0, expected_sr0, atol=1e-10):
        failures.append(
            f"expected_max_sharpe_null mismatch: expected {expected_sr0}, got {actual_sr0}"
        )

    # --- 5. Higher SR_hat -> higher DSR, all else fixed ---
    dsr_low = deflated_sharpe_ratio(0.5, 252, 0.0, 3.0, 20, 0.01)
    dsr_high = deflated_sharpe_ratio(2.0, 252, 0.0, 3.0, 20, 0.01)
    if not dsr_high > dsr_low:
        failures.append(f"Higher SR_hat should give higher DSR: {dsr_low} vs {dsr_high}")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All deflated_sharpe_ratio checks passed.")
    print(f"  SR0*(N=1)=0: OK")
    print(f"  SR0* monotonic in N: {[round(v, 4) for v in sr0_values]}")
    print(f"  DSR monotonic decreasing in N: {[round(v, 4) for v in dsr_values]}")
    print(f"  Exact arithmetic (skew=0,kurt=1): {actual_dsr:.10f} == {expected_dsr:.10f}")
    print(f"  expected_max_sharpe_null textbook match: {actual_sr0:.10f} == {expected_sr0:.10f}")


if __name__ == "__main__":
    main()
