"""
Synthetic verification of cvar.py's historical_cvar() before trusting it on
real backtest P&L.

Case 1: large-N standard normal sample — compare empirical historical CVaR_95
against the known analytical closed-form for a Normal(0,1) loss distribution:
CVaR_alpha = phi(z_alpha) / (1 - alpha), where z_alpha = Phi^-1(alpha) and
phi is the standard normal density. For alpha=0.95: z=1.6449, phi(z)=0.1031,
CVaR_95 = 0.1031/0.05 = 2.0627. With N=200,000 samples, empirical should
converge within ~5% of this (Monte Carlo tolerance, not exact).

Case 2: known small integer case — losses = -[1..100] means daily_pnl =
[-100..-1] (i.e. losses = [1..100]). At alpha=0.95, VaR is the 95th
percentile of losses = 96 (0-indexed quantile via numpy's linear
interpolation), CVaR = mean of losses >= that value. Checked against a
hand-computed value, not just "some positive number."

Case 3: all-profitable days (no tail loss) — losses are all negative
(pnl all positive), so VaR/CVaR should both be negative (no loss risk),
not clipped to zero or crashing.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from scipy import stats as sp_stats

from cvar import historical_cvar, var_exceedance_backtest

failures = []
rng = np.random.default_rng(7)

# --- Case 1: standard normal, large N ---
n = 200_000
sample = rng.normal(loc=0.0, scale=1.0, size=n)
result = historical_cvar(sample, 0.95)
z95 = sp_stats.norm.ppf(0.95)
analytical_cvar95 = sp_stats.norm.pdf(z95) / 0.05
rel_err = abs(result["cvar"] - analytical_cvar95) / analytical_cvar95
if rel_err > 0.05:
    failures.append(
        f"Case 1 (normal N={n}): empirical CVaR_95={result['cvar']:.4f} vs "
        f"analytical={analytical_cvar95:.4f}, rel_err={rel_err:.3f} > 0.05"
    )

# --- Case 2: known small integer case ---
daily_pnl = -np.arange(1, 101, dtype=float)  # pnl = [-1, -2, ..., -100] -> losses = [1..100]
result2 = historical_cvar(daily_pnl, 0.95)
losses = np.arange(1, 101, dtype=float)
expected_var = float(np.quantile(losses, 0.95))
expected_tail = losses[losses >= expected_var]
expected_cvar = float(expected_tail.mean())
if abs(result2["var"] - expected_var) > 1e-6 or abs(result2["cvar"] - expected_cvar) > 1e-6:
    failures.append(
        f"Case 2 (integer 1..100 losses): VaR={result2['var']} (expected {expected_var}), "
        f"CVaR={result2['cvar']} (expected {expected_cvar})"
    )

# --- Case 3: all-profitable days, no tail loss ---
all_profit = rng.uniform(10, 100, size=50)  # pnl always positive -> losses always negative
result3 = historical_cvar(all_profit, 0.95)
if result3["var"] >= 0 or result3["cvar"] >= 0:
    failures.append(
        f"Case 3 (all-profitable days): expected VaR and CVaR both negative "
        f"(no tail loss), got VaR={result3['var']}, CVaR={result3['cvar']}"
    )


# --- Case 4: well-calibrated VaR (iid normal P&L) should not systematically
# reject Kupiec across repeated trials — check the rejection RATE, not a
# single trial (a single trial passing or failing proves little on its own).
N_TRIALS = 15
n_rejected_kupiec = 0
n_rejected_ind = 0
for trial in range(N_TRIALS):
    trial_rng = np.random.default_rng(1000 + trial)
    daily_pnl_iid = -trial_rng.normal(loc=0.0, scale=1.0, size=1500)  # losses ~ N(0,1)
    bt = var_exceedance_backtest(daily_pnl_iid, 0.95, min_calibration_days=250)
    if bt is None or bt["kupiec_pvalue"] is None:
        failures.append(f"Case 4 trial {trial}: backtest returned no usable result")
        continue
    if bt["kupiec_pvalue"] < 0.05:
        n_rejected_kupiec += 1
    if bt["christoffersen_ind_pvalue"] is not None and bt["christoffersen_ind_pvalue"] < 0.05:
        n_rejected_ind += 1
print(f"Case 4 (well-calibrated, iid): Kupiec rejected {n_rejected_kupiec}/{N_TRIALS} trials, "
      f"independence rejected {n_rejected_ind}/{N_TRIALS} trials (nominal rate 0.05 each)")
# Generous ceiling (not a precise size calibration) — catches gross inflation.
if n_rejected_kupiec / N_TRIALS > 0.30:
    failures.append(
        f"Case 4: Kupiec rejection rate {n_rejected_kupiec/N_TRIALS:.2f} too high "
        f"for a genuinely well-calibrated iid VaR model."
    )
if n_rejected_ind / N_TRIALS > 0.30:
    failures.append(
        f"Case 4: Christoffersen-independence rejection rate {n_rejected_ind/N_TRIALS:.2f} "
        f"too high for genuinely independent exceedances."
    )

# --- Case 5: badly-calibrated VaR — a volatility regime break the expanding
# window can't see coming should blow through the calibrated VaR far more
# often than the nominal rate, and Kupiec should reject clearly.
rng5 = np.random.default_rng(99)
calm = rng5.normal(loc=0.0, scale=1.0, size=750)
volatile = rng5.normal(loc=0.0, scale=4.0, size=750)  # 4x vol, same mean
daily_pnl_regime_break = -np.concatenate([calm, volatile])
bt5 = var_exceedance_backtest(daily_pnl_regime_break, 0.95, min_calibration_days=250)
if bt5 is None or bt5["kupiec_pvalue"] is None:
    failures.append("Case 5: backtest returned no usable result")
else:
    print(f"Case 5 (regime break, badly calibrated): exceedance_rate={bt5['exceedance_rate']:.3f} "
          f"(expected {bt5['expected_rate']:.3f}), Kupiec p={bt5['kupiec_pvalue']:.4f}")
    if bt5["kupiec_pvalue"] >= 0.05:
        failures.append(
            f"Case 5: Kupiec test failed to reject a VaR model that is "
            f"obviously miscalibrated after a 4x volatility regime break "
            f"(p={bt5['kupiec_pvalue']:.4f})."
        )

# --- Case 6: clustered exceedances — deliberately force all exceedances
# into one contiguous block (even though the unconditional rate matches
# what's expected), so the independence test — not the POF test — is the
# one that should catch it.
rng6 = np.random.default_rng(17)
n6 = 1500
calib6 = 250
base = -rng6.normal(loc=0.0, scale=1.0, size=n6)
# After calibration, inject a short, deliberate high-loss cluster sized so
# the OVERALL post-calibration exceedance rate still lands near 5%, but
# every exceedance is packed into one contiguous run instead of scattered.
n_forecast_days = n6 - calib6
target_exceedances = max(3, round(0.05 * n_forecast_days))
cluster_start = calib6 + 40
base[cluster_start:cluster_start + target_exceedances] = -20.0  # deliberately huge losses, clustered
bt6 = var_exceedance_backtest(base, 0.95, min_calibration_days=calib6)
if bt6 is None or bt6["christoffersen_ind_pvalue"] is None:
    failures.append("Case 6: backtest returned no usable independence result")
else:
    print(f"Case 6 (clustered exceedances): rate={bt6['exceedance_rate']:.3f} "
          f"(expected {bt6['expected_rate']:.3f}), "
          f"Kupiec p={bt6['kupiec_pvalue']:.4f}, independence p={bt6['christoffersen_ind_pvalue']:.4f}")
    if bt6["christoffersen_ind_pvalue"] >= 0.05:
        failures.append(
            f"Case 6: independence test failed to detect deliberately "
            f"clustered exceedances (p={bt6['christoffersen_ind_pvalue']:.4f})."
        )

if failures:
    print("FAILURES:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All cvar.py checks passed.")
print(f"  Case 1: empirical CVaR_95={result['cvar']:.4f} vs analytical={analytical_cvar95:.4f} "
      f"(rel_err={rel_err:.4f})")
print(f"  Case 2: VaR={result2['var']}, CVaR={result2['cvar']}")
print(f"  Case 3: VaR={result3['var']:.2f}, CVaR={result3['cvar']:.2f} (both negative, no tail loss)")
