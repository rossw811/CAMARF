"""
Synthetic verification for research/kalman_slope_intercept.py, checked
against analysis.py's existing production HedgeRatioEstimator.kalman()
directly, not in isolation.

Case 1: true relationship has NO intercept (alpha=0) — both filters should
recover approximately the same beta, and the slope+intercept filter's own
recovered alpha should be small (near 0), confirming it doesn't invent a
spurious intercept when none exists.

Case 2: true relationship HAS a material, nonzero intercept — the
slope+intercept filter should recover alpha close to its true value, AND
the origin-only filter's beta estimate should be measurably biased (the
classic omitted-intercept bias: forcing a through-the-origin fit onto data
with a real intercept distorts the slope to compensate) relative to the
slope+intercept filter's beta, which should track the true beta more
closely.

Case 3: given the recovered beta+alpha, the slope+intercept spread
(log_a - beta*log_b - alpha) should have LOWER variance than the
origin-only spread (log_a - beta*log_b) when a true intercept exists —
the origin-only spread carries the omitted intercept as extra, unexplained
variance.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from analysis import HedgeRatioEstimator
from research.kalman_slope_intercept import kalman_slope_intercept

failures = []


def simulate_pair(n, true_beta, true_alpha, seed, noise_scale=0.05):
    rng = np.random.default_rng(seed)
    log_b = np.cumsum(rng.normal(scale=0.01, size=n)) + 4.0  # a log-price-like random walk
    log_a = true_alpha + true_beta * log_b + rng.normal(scale=noise_scale, size=n)
    return log_a, log_b


# --- Case 1: no true intercept ---
TRUE_BETA1, TRUE_ALPHA1 = 1.2, 0.0
log_a1, log_b1 = simulate_pair(1000, TRUE_BETA1, TRUE_ALPHA1, seed=1)
beta_origin1, mean_beta_origin1 = HedgeRatioEstimator.kalman(log_a1, log_b1)
beta_si1, alpha_si1, mean_beta_si1, mean_alpha_si1 = kalman_slope_intercept(log_a1, log_b1)
print(f"Case 1 (true alpha=0): origin beta={mean_beta_origin1:.4f}, "
      f"slope+intercept beta={mean_beta_si1:.4f}, alpha={mean_alpha_si1:.4f} (true beta={TRUE_BETA1})")
if abs(mean_alpha_si1) > 0.15:
    failures.append(f"Case 1: slope+intercept filter should recover alpha near 0 when "
                    f"no true intercept exists, got {mean_alpha_si1:.4f}")
if abs(mean_beta_si1 - TRUE_BETA1) > 0.15:
    failures.append(f"Case 1: slope+intercept beta ({mean_beta_si1:.4f}) too far from "
                    f"true beta ({TRUE_BETA1})")

# --- Case 2 & 3: material true intercept ---
TRUE_BETA2, TRUE_ALPHA2 = 1.2, 2.5  # a substantial, clearly-nonzero intercept
log_a2, log_b2 = simulate_pair(1000, TRUE_BETA2, TRUE_ALPHA2, seed=2)
beta_origin2, mean_beta_origin2 = HedgeRatioEstimator.kalman(log_a2, log_b2)
beta_si2, alpha_si2, mean_beta_si2, mean_alpha_si2 = kalman_slope_intercept(log_a2, log_b2)
print(f"\nCase 2 (true alpha={TRUE_ALPHA2}): origin beta={mean_beta_origin2:.4f}, "
      f"slope+intercept beta={mean_beta_si2:.4f}, alpha={mean_alpha_si2:.4f} (true beta={TRUE_BETA2})")

if abs(mean_alpha_si2 - TRUE_ALPHA2) > 0.5:
    failures.append(f"Case 2: slope+intercept filter failed to recover the true alpha "
                    f"({TRUE_ALPHA2}), got {mean_alpha_si2:.4f}")

error_origin = abs(mean_beta_origin2 - TRUE_BETA2)
error_si = abs(mean_beta_si2 - TRUE_BETA2)
print(f"  beta error: origin-only={error_origin:.4f}, slope+intercept={error_si:.4f} "
      f"(slope+intercept should be smaller — the omitted-intercept bias)")
if not (error_si < error_origin):
    failures.append(f"Case 2: slope+intercept beta error ({error_si:.4f}) should be smaller "
                    f"than origin-only's ({error_origin:.4f}) when a true intercept exists")

# Case 3: spread variance comparison
spread_origin2 = log_a2 - beta_origin2 * log_b2
spread_si2 = log_a2 - beta_si2 * log_b2 - alpha_si2
warmup = 130
var_origin = np.nanvar(spread_origin2[warmup:])
var_si = np.nanvar(spread_si2[warmup:])
print(f"\nCase 3: spread variance origin-only={var_origin:.4f}, "
      f"slope+intercept={var_si:.4f} (slope+intercept should be lower)")
if not (var_si < var_origin):
    failures.append(f"Case 3: slope+intercept spread variance ({var_si:.4f}) should be lower "
                    f"than origin-only's ({var_origin:.4f}) when a true intercept exists")

print()
if failures:
    print(f"FAILED ({len(failures)} issue(s)):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("ALL CHECKS PASSED")
    sys.exit(0)
