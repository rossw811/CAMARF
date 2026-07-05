"""
Synthetic verification for research/threshold_cointegration.py, following
this project's standing discipline: prove the test behaves correctly on
data with a KNOWN true answer before trusting it on real confirmed pairs.

Two cases:
  1. Linear null (no real threshold effect) — a single-regime AR(1)
     error-correction spread. Repeated trials should reject the linear
     null (boot_pvalue < 0.05) at close to the nominal 5% rate, not
     systematically. A single-trial "not significant" result on its own
     would prove nothing (could just be luck); the point is the rejection
     rate across many independent trials should track the level the test
     claims, not be inflated.
  2. Genuine single-threshold effect — mild, slow mean-reversion below a
     true threshold gamma, much faster reversion pulling back down above
     it (an asymmetric "ceiling" story, matching Hansen & Seo's actual
     2-regime specification, not a symmetric band). The test should (a)
     reject the linear null, (b) recover gamma close to the true value,
     and (c) correctly flag the outside regime as the faster-reverting one.

Both cases use a fixed seed so the result is reproducible, not a single
lucky draw.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from research.threshold_cointegration import threshold_coint_test

failures = []


def simulate_linear(n, alpha, seed):
    rng = np.random.default_rng(seed)
    z = np.zeros(n)
    for t in range(1, n):
        z[t] = z[t - 1] + alpha * z[t - 1] + rng.normal(scale=0.5)
    return z


def simulate_threshold(n, gamma_true, alpha_in, alpha_out, seed, noise_scale=0.3):
    rng = np.random.default_rng(seed)
    z = np.zeros(n)
    for t in range(1, n):
        prev = z[t - 1]
        if prev <= gamma_true:
            dz = alpha_in * prev + rng.normal(scale=noise_scale)
        else:
            dz = alpha_out * (prev - gamma_true) + rng.normal(scale=noise_scale)
        z[t] = prev + dz
    return z


# --- Case 1: linear null, rejection rate should track ~5% across trials ---
N_TRIALS = 20
rng_master = np.random.default_rng(123)
n_rejected = 0
for trial in range(N_TRIALS):
    z = simulate_linear(n=300, alpha=-0.05, seed=1000 + trial)
    boot_rng = np.random.default_rng(2000 + trial)
    result = threshold_coint_test(z, trim=0.15, n_grid=40, n_boot=200, rng=boot_rng)
    if not result.get("ok"):
        failures.append(f"Case 1 trial {trial}: test failed to run ({result.get('error')})")
        continue
    if result["boot_pvalue"] < 0.05:
        n_rejected += 1

rejection_rate = n_rejected / N_TRIALS
print(f"Case 1 (linear null): rejected {n_rejected}/{N_TRIALS} trials "
      f"(rate={rejection_rate:.2f}, nominal=0.05)")
# Generous band (0-25%) given only 20 trials at n_boot=200 — this is a
# sanity check against gross inflation (e.g. rejecting every trial), not a
# precise size calibration.
if rejection_rate > 0.25:
    failures.append(
        f"Case 1: rejection rate {rejection_rate:.2f} is too high for a "
        f"linear-null series — the test may be spuriously finding threshold "
        f"effects in genuinely linear data."
    )

# --- Case 2: genuine threshold effect, single well-powered trial ---
# Parameters tuned (checked empirically, not guessed) so gamma_true sits
# well inside the 15th-85th percentile of the resulting series and both
# regimes get a healthy share of observations (~34% above threshold) — an
# earlier attempt placed gamma_true near the 95th percentile of the
# simulated data, which is structurally unfindable by design, since the
# grid search only ever searches within the trimmed empirical range (the
# correct, standard restriction — Hansen's own convention — not a bug to
# route around; the synthetic scenario just has to respect it).
GAMMA_TRUE = 0.0
z2 = simulate_threshold(n=3000, gamma_true=GAMMA_TRUE, alpha_in=-0.1, alpha_out=-0.3, seed=42, noise_scale=0.4)
boot_rng2 = np.random.default_rng(43)
result2 = threshold_coint_test(z2, trim=0.15, n_grid=100, n_boot=500, rng=boot_rng2)

print(f"\nCase 2 (genuine threshold, true gamma={GAMMA_TRUE}):")
if not result2.get("ok"):
    failures.append(f"Case 2: test failed to run ({result2.get('error')})")
else:
    print(f"  estimated gamma={result2['gamma']:.3f} "
          f"(percentile {result2['gamma_percentile']*100:.0f}%)")
    print(f"  alpha_inside={result2['alpha_inside']:.4f} "
          f"alpha_outside={result2['alpha_outside']:.4f}")
    print(f"  outside_faster={result2['outside_faster']} "
          f"boot_pvalue={result2['boot_pvalue']:.4f}")

    if result2["boot_pvalue"] >= 0.05:
        failures.append(
            f"Case 2: test failed to reject the linear null "
            f"(boot_pvalue={result2['boot_pvalue']:.4f}) on data with a "
            f"strong, well-powered true threshold effect."
        )
    if not result2["outside_faster"]:
        failures.append(
            "Case 2: test did not correctly identify the outside regime "
            "as faster-reverting, despite alpha_out=-0.3 vs alpha_in=-0.1."
        )
    # Tolerance set from direct measurement, not a guess: gamma-hat's
    # sampling variability was checked across n=3000/6000/10000 replicates
    # of this same DGP and stayed within roughly +/-0.4 of the true value
    # every time, while alpha_inside/alpha_outside stayed tightly close to
    # their true (-0.1, -0.3) generating values — gamma has a genuinely
    # noisier finite-sample distribution than the regime slopes do, which
    # is a known property of threshold estimators, not a red flag on its
    # own as long as the slopes and the rejection itself are both correct.
    if abs(result2["gamma"] - GAMMA_TRUE) > 0.6:
        failures.append(
            f"Case 2: estimated gamma ({result2['gamma']:.3f}) is too far "
            f"from the true value ({GAMMA_TRUE}) to trust the estimator."
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
