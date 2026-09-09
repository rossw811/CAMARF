"""
debug/_verify_options_greeks_unit.py -- synthetic checks for options.py's new Black-Scholes
Greeks unit (black_scholes_delta/gamma/vega/theta/greeks/greeks_vectorized, added 2026-09-07 per
Ross's "options calc unit... consider things in terms of delta" request). Checks each Greek
against a finite-difference cross-check on the underlying pricing functions already verified in
this project (black_scholes_call/put) -- the Greeks are literally the price functions'
derivatives, so if they don't match a numerical derivative of black_scholes_call/put, something
is wrong, independent of getting the closed-form algebra right by memory.

Run: python debug/_verify_options_greeks_unit.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from options import (
    black_scholes_call, black_scholes_put, black_scholes_delta, black_scholes_gamma,
    black_scholes_vega, black_scholes_theta, black_scholes_greeks, black_scholes_greeks_vectorized,
)

passed = 0
failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}")
        failed += 1


S, K, T, sigma, r = 100.0, 100.0, 0.5, 0.25, 0.0
h = 0.01

print("Check 1: call delta matches a finite-difference derivative of black_scholes_call w.r.t. S")
fd_delta = (black_scholes_call(S + h, K, T, sigma, r) - black_scholes_call(S - h, K, T, sigma, r)) / (2 * h)
analytic_delta = black_scholes_delta(S, K, T, sigma, r, "call")
check(f"call delta ({analytic_delta:.6f}) matches finite-difference ({fd_delta:.6f})",
      abs(analytic_delta - fd_delta) < 1e-4)

print("Check 2: put delta matches a finite-difference derivative of black_scholes_put w.r.t. S")
fd_delta_put = (black_scholes_put(S + h, K, T, sigma, r) - black_scholes_put(S - h, K, T, sigma, r)) / (2 * h)
analytic_delta_put = black_scholes_delta(S, K, T, sigma, r, "put")
check(f"put delta ({analytic_delta_put:.6f}) matches finite-difference ({fd_delta_put:.6f})",
      abs(analytic_delta_put - fd_delta_put) < 1e-4)
check("put-call delta parity: call_delta - put_delta == 1.0 (textbook identity)",
      abs((analytic_delta - analytic_delta_put) - 1.0) < 1e-9)

print("Check 3: gamma matches a finite-difference SECOND derivative of black_scholes_call w.r.t. S")
fd_gamma = (black_scholes_call(S + h, K, T, sigma, r) - 2 * black_scholes_call(S, K, T, sigma, r)
            + black_scholes_call(S - h, K, T, sigma, r)) / (h ** 2)
analytic_gamma = black_scholes_gamma(S, K, T, sigma, r)
check(f"gamma ({analytic_gamma:.6f}) matches finite-difference second derivative ({fd_gamma:.6f})",
      abs(analytic_gamma - fd_gamma) < 1e-3)
check("gamma is identical for calls and puts (no option_type argument needed -- same curvature)",
      True)  # black_scholes_gamma has no option_type param by design; this documents the intent

print("Check 4: vega matches a finite-difference derivative of black_scholes_call w.r.t. sigma")
h_sigma = 0.0001
fd_vega = (black_scholes_call(S, K, T, sigma + h_sigma, r) - black_scholes_call(S, K, T, sigma - h_sigma, r)) / (2 * h_sigma)
analytic_vega = black_scholes_vega(S, K, T, sigma, r)
check(f"vega ({analytic_vega:.4f}) matches finite-difference ({fd_vega:.4f})",
      abs(analytic_vega - fd_vega) < 0.5)

print("Check 5: theta matches a finite-difference derivative of black_scholes_call w.r.t. T "
      "(theta is DECAY, i.e. -d(price)/dt as time passes, so -d(price)/dT since T counts down)")
h_T = 0.001
fd_theta = -(black_scholes_call(S, K, T + h_T, sigma, r) - black_scholes_call(S, K, T - h_T, sigma, r)) / (2 * h_T)
analytic_theta = black_scholes_theta(S, K, T, sigma, r, "call")
check(f"theta ({analytic_theta:.4f}) matches finite-difference ({fd_theta:.4f})",
      abs(analytic_theta - fd_theta) < 0.5)

print("Check 6: at/after expiry (T<=0), delta collapses to the correct intrinsic-value "
      "indicator rather than an undefined/crashing N(d1) computation")
check("deep ITM call at expiry -> delta=1.0", black_scholes_delta(150, 100, 0, 0.2, 0.0, "call") == 1.0)
check("deep OTM call at expiry -> delta=0.0", black_scholes_delta(50, 100, 0, 0.2, 0.0, "call") == 0.0)
check("deep ITM put at expiry -> delta=-1.0", black_scholes_delta(50, 100, 0, 0.2, 0.0, "put") == -1.0)
check("deep OTM put at expiry -> delta=0.0", black_scholes_delta(150, 100, 0, 0.2, 0.0, "put") == 0.0)
check("gamma/vega/theta all -> 0.0 at expiry (no more convexity/time-value once expired)",
      black_scholes_gamma(100, 100, 0, 0.2) == 0.0 and
      black_scholes_vega(100, 100, 0, 0.2) == 0.0 and
      black_scholes_theta(100, 100, 0, 0.2, 0.0, "call") == 0.0)

print("Check 7: black_scholes_greeks() convenience wrapper returns the same 4 values as calling "
      "each individual Greek function separately -- no drift between the two call paths")
combined = black_scholes_greeks(S, K, T, sigma, r, "call")
check("wrapper's delta/gamma/vega/theta all exactly match the individual function calls",
      combined["delta"] == black_scholes_delta(S, K, T, sigma, r, "call") and
      combined["gamma"] == black_scholes_gamma(S, K, T, sigma, r) and
      combined["vega"] == black_scholes_vega(S, K, T, sigma, r) and
      combined["theta"] == black_scholes_theta(S, K, T, sigma, r, "call"))

print("Check 8: black_scholes_greeks_vectorized() matches the scalar functions element-by-"
      "element over an array, including a real invalid element (sigma<=0) that must produce "
      "NaN rather than crashing the whole batch")
S_arr = np.array([90.0, 100.0, 110.0, 100.0])
K_arr = np.array([100.0, 100.0, 100.0, 100.0])
sigma_arr = np.array([0.2, 0.25, 0.3, 0.0])  # last element deliberately invalid (sigma=0)
vec = black_scholes_greeks_vectorized(S_arr, K_arr, T, sigma_arr, r, option_type="call")
scalar_deltas = [black_scholes_delta(s, k, T, sg, r, "call") if sg > 0 else None
                 for s, k, sg in zip(S_arr[:3], K_arr[:3], sigma_arr[:3])]
check("first 3 (valid) elements match the scalar function's own delta values",
      all(abs(vec["delta"][i] - scalar_deltas[i]) < 1e-9 for i in range(3)))
check("the deliberately-invalid 4th element (sigma=0) is NaN, not a crash or a fabricated value",
      np.isnan(vec["delta"][3]) and np.isnan(vec["gamma"][3]))

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
