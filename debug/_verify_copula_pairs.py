"""
Synthetic verification for copula_pairs.py (2026-06-24).

Simulates data from KNOWN Gaussian, Clayton, and rotated-Clayton copulas
and confirms:
  1. Each fitting procedure recovers its true parameter to a reasonable
     tolerance (these are closed-form moment estimators, not MLE, so
     tolerance is generous, not exact).
  2. The log-likelihood comparison correctly identifies the TRUE
     generating family on each synthetic dataset — including, critically,
     that data with genuine UPPER-tail dependence (simulated by rotating
     a standard Clayton draw) is correctly identified as rotated-Clayton,
     NOT plain Clayton — this is the specific mechanism the CCL/NCLH
     application depends on, not just "some non-Gaussian copula wins."
  3. The Kendall's-tau invariance claimed in copula_pairs.py's docstring
     (theta fit on (u,v) equals theta fit on (1-u,1-v) for the SAME data)
     actually holds — a sanity check on the derivation, even though
     production code fits both independently rather than relying on it.

Run: python debug/_verify_copula_pairs.py
"""
import os
import sys

import numpy as np
from scipy.stats import norm

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "research"))

from copula_pairs import (
    fit_clayton_theta,
    fit_gaussian,
    loglik_clayton,
    loglik_gaussian,
    pseudo_observations,
)

SEED = 7
N = 3000


def simulate_gaussian_copula(rho, n, rng):
    z1 = rng.normal(size=n)
    z2 = rho * z1 + np.sqrt(1 - rho ** 2) * rng.normal(size=n)
    return norm.cdf(z1), norm.cdf(z2)


def simulate_clayton_copula(theta, n, rng):
    """Conditional-inversion sampling, derived directly from
    C(u,v) = (u^-theta + v^-theta - 1)^(-1/theta) by inverting
    dC/du(u,v) = W for v (re-derived and checked here rather than
    trusted from memory alone, per this project's standing discipline):
        V = [ U^-theta * (W^(-theta/(1+theta)) - 1) + 1 ]^(-1/theta)
    """
    u = rng.uniform(size=n)
    w = rng.uniform(size=n)
    v = (u ** (-theta) * (w ** (-theta / (1 + theta)) - 1) + 1) ** (-1 / theta)
    return u, v


def mean_ll(family, u, v, rho=None, theta=None):
    if family == "gaussian":
        return float(np.mean(loglik_gaussian(u, v, rho)))
    if family == "clayton":
        return float(np.mean(loglik_clayton(u, v, theta)))
    if family == "rotated_clayton":
        return float(np.mean(loglik_clayton(1 - u, 1 - v, theta)))
    raise ValueError(family)


def check_recovery_and_ranking(label, u, v, true_family, true_param):
    rho_hat = fit_gaussian(u, v)
    theta_hat = fit_clayton_theta(u, v)
    theta_rot_hat = fit_clayton_theta(1 - u, 1 - v)

    lls = {
        "gaussian": mean_ll("gaussian", u, v, rho=rho_hat),
        "clayton": mean_ll("clayton", u, v, theta=theta_hat) if theta_hat else None,
        "rotated_clayton": mean_ll("rotated_clayton", u, v, theta=theta_rot_hat) if theta_rot_hat else None,
    }
    winner = max((f for f in lls if lls[f] is not None), key=lambda f: lls[f])

    print(f"\n[{label}] true_family={true_family} true_param={true_param}")
    print(f"  fitted rho_gaussian={rho_hat:.4f}")
    print(f"  fitted theta_clayton={theta_hat}")
    print(f"  fitted theta_rotated_clayton={theta_rot_hat}")
    print(f"  mean log-lik: {lls}")
    print(f"  winner: {winner}")

    assert winner == true_family, (
        f"FAILED [{label}]: expected {true_family} to win, got {winner} ({lls})"
    )
    print(f"  PASS: {true_family} correctly identified as best fit.")
    return rho_hat, theta_hat, theta_rot_hat


def main():
    rng = np.random.default_rng(SEED)

    # --- Gaussian copula, rho_true=0.6 ---
    u, v = simulate_gaussian_copula(0.6, N, rng)
    rho_hat, _, _ = check_recovery_and_ranking("gaussian rho=0.6", u, v, "gaussian", 0.6)
    assert abs(rho_hat - 0.6) < 0.05, f"FAILED: rho recovery off: {rho_hat} vs 0.6"
    print(f"  PASS: rho recovered within tolerance ({rho_hat:.4f} vs 0.6).")

    # --- Standard Clayton copula (lower-tail), theta_true=3.0 ---
    u, v = simulate_clayton_copula(3.0, N, rng)
    _, theta_hat, theta_rot_hat = check_recovery_and_ranking(
        "clayton (lower-tail) theta=3.0", u, v, "clayton", 3.0
    )
    assert theta_hat is not None and abs(theta_hat - 3.0) < 0.75, (
        f"FAILED: theta recovery off: {theta_hat} vs 3.0"
    )
    print(f"  PASS: theta recovered within tolerance ({theta_hat:.4f} vs 3.0).")

    # Kendall's-tau invariance check: theta fit on (1-u,1-v) for this SAME
    # lower-tail-generated data should match theta fit on (u,v) closely —
    # validates the docstring's invariance claim directly.
    assert theta_rot_hat is not None
    rel_diff = abs(theta_rot_hat - theta_hat) / theta_hat
    print(f"  invariance check: theta(u,v)={theta_hat:.4f} vs theta(1-u,1-v)={theta_rot_hat:.4f} "
          f"(rel diff={rel_diff:.4f})")
    assert rel_diff < 0.05, (
        f"FAILED: Kendall's-tau invariance claim does not hold within tolerance: "
        f"{theta_hat} vs {theta_rot_hat}"
    )
    print("  PASS: Kendall's-tau invariance under (1-u,1-v) reflection confirmed.")

    # --- Rotated Clayton copula (upper-tail), theta_true=3.0 ---
    # Generate a standard (lower-tail) Clayton draw, then reflect it —
    # this IS a draw from the rotated/survival Clayton copula by
    # definition (C_hat(u,v) = u+v-1+C(1-u,1-v) is exactly the
    # distribution of (1-U,1-V) when (U,V) ~ C).
    u_base, v_base = simulate_clayton_copula(3.0, N, rng)
    u_rot, v_rot = 1 - u_base, 1 - v_base
    check_recovery_and_ranking(
        "rotated clayton (upper-tail) theta=3.0", u_rot, v_rot, "rotated_clayton", 3.0
    )

    print("\nALL CHECKS PASSED.")


if __name__ == "__main__":
    main()
