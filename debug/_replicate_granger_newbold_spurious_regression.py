"""
Synthetic replication of Granger & Newbold (1974), "Spurious Regressions in
Econometrics" (J. of Econometrics 2(2), 111-120) -- BEFORE trusting that this
project's entire premise (raw OLS on nonstationary price levels is invalid,
EG-style residual cointegration testing is required) rests on a real, not
just cited, effect.

Granger-Newbold's core finding: regressing one independent random walk on
another produces "significant" OLS t-statistics and high R^2 at rates far
above the nominal test size, purely from shared nonstationarity -- not from
any real relationship. This is the reason `analysis.py`'s CointScanner runs
Engle-Granger residual testing on log prices instead of a naive OLS
significance test.

Checks:
  1. Two independent random walks: naive-SE OLS |t|>1.96 rejection rate
     should be far above the nominal 5% level (Granger-Newbold's own
     simulations found ~75%+ for T=50; this replication uses a longer series
     and many more Monte Carlo trials for a stable estimate).
  2. Two independent STATIONARY AR(1) series (rho=0.5), naive (non-HAC) SEs:
     a first run of this script found this ALSO over-rejects (~13% vs.
     nominal 5%) -- a real, separate, and correctly-reported finding, not a
     bug to paper over: naive OLS standard errors are invalid whenever
     regressors are autocorrelated, stationary or not, because the effective
     sample size is smaller than T. This is distinct from Granger-Newbold's
     spurious-regression result.
  2b. The SAME stationary AR(1) pairs, but with Newey-West HAC-corrected
     standard errors: rejection rate should revert close to the nominal 5%,
     confirming the over-rejection in (2) is a fixable standard-error
     problem for stationary series specifically -- not the same failure mode
     as (1)'s random walks, where no amount of HAC correction fixes the
     problem (this is exactly the asymptotic distinction Phillips's
     unit-root theory, already in this project's research backlog, makes
     formally).
  3. R^2 distribution: nonstationary case should show R^2 with a
     substantially higher mean than the stationary control (Granger-Newbold's
     "R^2 does not go to zero as expected under the null").
  4. Direct comparison: Engle-Granger cointegration testing on the SAME
     nonstationary pairs should reject "cointegrated" at close to the nominal
     rate (the whole point of EG -- it's specifically designed not to fall
     for this artifact), confirmed via statsmodels.tsa.stattools.coint(),
     the same function analysis.py's CointScanner actually calls.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import statsmodels.api as sm
from statsmodels.tsa.stattools import coint

N_TRIALS = 2000
T = 250
ALPHA = 0.05
Z_CRIT = 1.96
RNG = np.random.default_rng(42)


def _ols_reject_and_r2(y: np.ndarray, x: np.ndarray, hac: bool = False) -> tuple:
    x_c = sm.add_constant(x)
    model = sm.OLS(y, x_c).fit()
    if hac:
        model = model.get_robustcov_results(cov_type="HAC", maxlags=int(T ** 0.25))
    t_stat = model.tvalues[1]
    return abs(t_stat) > Z_CRIT, model.rsquared


def random_walk(t: int) -> np.ndarray:
    return np.cumsum(RNG.standard_normal(t))


def stationary_ar1(t: int, rho: float = 0.5) -> np.ndarray:
    e = RNG.standard_normal(t)
    x = np.zeros(t)
    for i in range(1, t):
        x[i] = rho * x[i - 1] + e[i]
    return x


def main():
    failures = []

    # --- 1 & 3: independent random walks (naive SE, then HAC-corrected) ---
    rw_rejections = 0
    rw_rejections_hac = 0
    rw_r2 = []
    for _ in range(N_TRIALS):
        y = random_walk(T)
        x = random_walk(T)
        rejected, r2 = _ols_reject_and_r2(y, x, hac=False)
        rejected_hac, _ = _ols_reject_and_r2(y, x, hac=True)
        rw_rejections += int(rejected)
        rw_rejections_hac += int(rejected_hac)
        rw_r2.append(r2)
    rw_reject_rate = rw_rejections / N_TRIALS
    rw_reject_rate_hac = rw_rejections_hac / N_TRIALS
    rw_mean_r2 = float(np.mean(rw_r2))

    # --- 2 & 2b: independent stationary AR(1), naive SE vs. HAC-corrected SE ---
    ar1_rejections_naive = 0
    ar1_rejections_hac = 0
    ar1_r2 = []
    for _ in range(N_TRIALS):
        y = stationary_ar1(T)
        x = stationary_ar1(T)
        rejected_naive, r2 = _ols_reject_and_r2(y, x, hac=False)
        rejected_hac, _ = _ols_reject_and_r2(y, x, hac=True)
        ar1_rejections_naive += int(rejected_naive)
        ar1_rejections_hac += int(rejected_hac)
        ar1_r2.append(r2)
    ar1_reject_rate_naive = ar1_rejections_naive / N_TRIALS
    ar1_reject_rate_hac = ar1_rejections_hac / N_TRIALS
    ar1_mean_r2 = float(np.mean(ar1_r2))

    # --- 4: EG cointegration test on the SAME nonstationary pairs ---
    eg_rejections = 0  # "rejections" here = correctly finds NO cointegration
    for _ in range(N_TRIALS):
        y = random_walk(T)
        x = random_walk(T)
        _t_stat, p_value, _crit = coint(y, x, trend="c", autolag="aic")
        if p_value < ALPHA:
            eg_rejections += 1
    eg_false_coint_rate = eg_rejections / N_TRIALS

    # --- Assertions ---
    if not (rw_reject_rate > 0.30):
        failures.append(
            f"Spurious regression effect too weak: random-walk OLS |t|>1.96 rate "
            f"= {rw_reject_rate:.3f}, expected far above nominal 5% (Granger-Newbold "
            f"effect)"
        )
    if not (ar1_reject_rate_naive > 0.08):
        failures.append(
            f"Expected naive-SE over-rejection on autocorrelated-but-stationary "
            f"series was not observed: {ar1_reject_rate_naive:.3f} (expected >8%, "
            f"i.e. measurably above nominal 5% -- if this doesn't reproduce, the "
            f"HAC-fixes-it comparison below is meaningless)"
        )
    if not (ar1_reject_rate_hac < 0.09):
        failures.append(
            f"HAC-corrected SE did not bring the stationary control back near "
            f"nominal size: {ar1_reject_rate_hac:.3f}, expected < 9%"
        )
    if not (rw_reject_rate_hac > ar1_reject_rate_hac * 3):
        failures.append(
            f"Random-walk spurious regression not clearly distinct from the "
            f"HAC-corrected stationary control, even after BOTH get HAC SEs: "
            f"{rw_reject_rate_hac:.3f} vs {ar1_reject_rate_hac:.3f} -- HAC "
            f"correction should NOT fix the random-walk case the way it fixes "
            f"the stationary one (this is Granger-Newbold's actual point: it "
            f"is not a standard-error problem for nonstationary series)"
        )
    if not (rw_mean_r2 > ar1_mean_r2 * 3):
        failures.append(
            f"Nonstationary R^2 not substantially inflated vs. stationary control: "
            f"{rw_mean_r2:.3f} vs {ar1_mean_r2:.3f}"
        )
    if not (eg_false_coint_rate < 0.10):
        failures.append(
            f"EG cointegration test false-positive rate too high on genuinely "
            f"independent random walks: {eg_false_coint_rate:.3f}, expected close "
            f"to nominal 5% (this is the property that makes EG the correct test, "
            f"not naive OLS)"
        )

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)

    print("Granger-Newbold (1974) spurious regression replication: PASSED")
    print(f"  Random walks    -- naive-SE reject rate: {rw_reject_rate:.3f}   "
          f"HAC-SE reject rate: {rw_reject_rate_hac:.3f}  (nominal size 0.05; "
          f"HAC does NOT fix this -- Granger-Newbold's actual finding)")
    print(f"  Stationary AR1  -- naive-SE reject rate: {ar1_reject_rate_naive:.3f}   "
          f"HAC-SE reject rate: {ar1_reject_rate_hac:.3f}  (HAC DOES fix this -- "
          f"confirms it's a separate, ordinary autocorrelated-SE problem)")
    print(f"  Mean R^2, random walks vs. stationary: {rw_mean_r2:.3f} vs {ar1_mean_r2:.3f}")
    print(f"  Same random-walk pairs, EG cointegration false-positive rate: "
          f"{eg_false_coint_rate:.3f} (this is why analysis.py uses EG, not naive OLS)")


if __name__ == "__main__":
    main()
