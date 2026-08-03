"""
Synthetic verification for research/options_greeks_features.py's bs_greeks(),
before trusting it on real pair data.

The rigorous way to verify closed-form Greeks without any external
reference table: check them against FINITE-DIFFERENCE derivatives of
options.py's own already-existing black_scholes_call() -- delta is
dPrice/dS, gamma is d2Price/dS2, vega is dPrice/dsigma. If the closed-form
formulas disagree with numerically differentiating the SAME pricing
function they're supposed to describe, something is wrong.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from options import black_scholes_call
from options_greeks_features import bs_greeks


def test_delta_matches_finite_difference():
    S, K, T, sigma = 100.0, 100.0, 30 / 365.0, 0.25
    h = 0.01
    fd_delta = (black_scholes_call(S + h, K, T, sigma) - black_scholes_call(S - h, K, T, sigma)) / (2 * h)
    analytic = bs_greeks(np.array([S]), np.array([K]), T, np.array([sigma]))["delta"][0]
    print(f"delta: analytic={analytic:.6f}  finite-diff={fd_delta:.6f}")
    assert abs(analytic - fd_delta) < 1e-4, f"delta mismatch: {analytic} vs {fd_delta}"


def test_gamma_matches_finite_difference():
    S, K, T, sigma = 100.0, 100.0, 30 / 365.0, 0.25
    h = 0.5
    fd_gamma = (black_scholes_call(S + h, K, T, sigma) - 2 * black_scholes_call(S, K, T, sigma)
                + black_scholes_call(S - h, K, T, sigma)) / (h ** 2)
    analytic = bs_greeks(np.array([S]), np.array([K]), T, np.array([sigma]))["gamma"][0]
    print(f"gamma: analytic={analytic:.6f}  finite-diff={fd_gamma:.6f}")
    assert abs(analytic - fd_gamma) < 1e-3, f"gamma mismatch: {analytic} vs {fd_gamma}"


def test_vega_matches_finite_difference():
    S, K, T, sigma = 100.0, 100.0, 30 / 365.0, 0.25
    h = 0.001
    fd_vega = (black_scholes_call(S, K, T, sigma + h) - black_scholes_call(S, K, T, sigma - h)) / (2 * h)
    analytic = bs_greeks(np.array([S]), np.array([K]), T, np.array([sigma]))["vega"][0]
    print(f"vega: analytic={analytic:.6f}  finite-diff={fd_vega:.6f}")
    assert abs(analytic - fd_vega) < 1e-3, f"vega mismatch: {analytic} vs {fd_vega}"


def test_gamma_peaks_atm():
    """Gamma should be highest ATM and fall off away from the strike --
    a basic sanity/direction check independent of the finite-diff match."""
    S, T, sigma = 100.0, 30 / 365.0, 0.25
    strikes = np.array([80.0, 100.0, 120.0])
    gammas = bs_greeks(np.full(3, S), strikes, T, np.full(3, sigma))["gamma"]
    print(f"gamma at K=80/100/120: {gammas}")
    assert gammas[1] > gammas[0] and gammas[1] > gammas[2], "ATM gamma should exceed OTM/ITM gamma"


def test_invalid_inputs_give_nan_not_crash():
    result = bs_greeks(np.array([0.0, -5.0, 100.0]), np.array([100.0, 100.0, 100.0]), 30 / 365.0,
                        np.array([0.2, 0.2, 0.0]))
    print(f"invalid-input gamma: {result['gamma']}")
    assert np.isnan(result["gamma"][0]) and np.isnan(result["gamma"][1]) and np.isnan(result["gamma"][2])


if __name__ == "__main__":
    test_delta_matches_finite_difference()
    test_gamma_matches_finite_difference()
    test_vega_matches_finite_difference()
    test_gamma_peaks_atm()
    test_invalid_inputs_give_nan_not_crash()
    print("\nAll options_greeks_features.py synthetic checks passed.")
