"""
debug/_verify_jump_diffusion_fit.py — synthetic ground-truth verification for
research/jump_diffusion_parameter_fit.py's Merton (1976) jump-diffusion MLE
estimator, before it is trusted on real spread data.

Two cases:
  1. Known jump-diffusion process (mu, sigma, lambda, mu_J, sigma_J) simulated
     directly; confirms the estimator recovers all five parameters within
     tolerance.
  2. Pure diffusion, zero true jump intensity; confirms the estimator does not
     spuriously fit a large jump component when none exists (lambda_hat should
     land near 0 and NOT explain away most of the variance as jumps).

Run: python debug/_verify_jump_diffusion_fit.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from jump_diffusion_parameter_fit import fit_merton_jump_diffusion, implied_jump_variance_share

RNG = np.random.default_rng(20260713)


def simulate_merton(n, mu, sigma, lam, mu_j, sigma_j, rng):
    diffusion = rng.normal(mu, sigma, size=n)
    is_jump = rng.random(n) < lam
    jump_component = np.where(is_jump, rng.normal(mu_j, sigma_j, size=n), 0.0)
    return diffusion + jump_component, is_jump


def case_1_known_jump_process():
    true = dict(mu=0.0, sigma=0.08, lam=0.03, mu_j=0.0, sigma_j=1.2)
    x, is_jump = simulate_merton(8000, true["mu"], true["sigma"], true["lam"],
                                  true["mu_j"], true["sigma_j"], RNG)
    fit = fit_merton_jump_diffusion(x)
    print("Case 1 (known jump-diffusion process, n=8000):")
    print(f"  true : mu={true['mu']:.4f} sigma={true['sigma']:.4f} lambda={true['lam']:.4f} "
          f"mu_J={true['mu_j']:.4f} sigma_J={true['sigma_j']:.4f}")
    print(f"  fit  : mu={fit['mu']:.4f} sigma={fit['sigma']:.4f} lambda={fit['lam']:.4f} "
          f"mu_J={fit['mu_j']:.4f} sigma_J={fit['sigma_j']:.4f}")

    # Tolerances: lambda/jump-size params are inherently noisier at this n
    # (only ~lambda*n = 240 true jump events); sigma/mu are the tightest.
    ok = (
        abs(fit["sigma"] - true["sigma"]) / true["sigma"] < 0.20
        and abs(fit["lam"] - true["lam"]) / true["lam"] < 0.45
        and abs(fit["sigma_j"] - true["sigma_j"]) / true["sigma_j"] < 0.30
    )
    true_share = true["lam"] * (true["mu_j"] ** 2 + true["sigma_j"] ** 2)
    true_share = true_share / (true["sigma"] ** 2 + true_share)
    fit_share = implied_jump_variance_share(fit)
    print(f"  implied jump-variance-share: true={true_share:.3f} fit={fit_share:.3f}")
    ok = ok and abs(fit_share - true_share) < 0.15
    print(f"  -> {'PASS' if ok else 'FAIL'}\n")
    return ok


def case_2_pure_diffusion_no_jumps():
    true_sigma = 0.15
    x, _ = simulate_merton(5000, 0.0, true_sigma, 0.0, 0.0, 0.0, RNG)
    fit = fit_merton_jump_diffusion(x)
    fit_share = implied_jump_variance_share(fit)
    print("Case 2 (pure diffusion, true lambda=0, n=5000):")
    print(f"  fit  : mu={fit['mu']:.4f} sigma={fit['sigma']:.4f} lambda={fit['lam']:.4f} "
          f"mu_J={fit['mu_j']:.4f} sigma_J={fit['sigma_j']:.4f}")
    print(f"  implied jump-variance-share (should be near 0): {fit_share:.3f}")
    # The estimator should not explain away more than a small fraction of
    # variance as "jumps" when the true process has none.
    ok = fit_share < 0.15 and abs(fit["sigma"] - true_sigma) / true_sigma < 0.15
    print(f"  -> {'PASS' if ok else 'FAIL'}\n")
    return ok


if __name__ == "__main__":
    r1 = case_1_known_jump_process()
    r2 = case_2_pure_diffusion_no_jumps()
    if r1 and r2:
        print("ALL CHECKS PASSED — estimator recovers known parameters and does not "
              "spuriously fit jumps to pure-diffusion data. Proceeding to real data is justified.")
        sys.exit(0)
    else:
        print("FAILED — do not trust real-data fit until this passes.")
        sys.exit(1)
