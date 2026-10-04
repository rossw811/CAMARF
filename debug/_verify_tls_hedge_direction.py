"""
Regression test (2026-10-03; found by the independent A3 review, re-checked by hand): HedgeRatioEstimator.tls returned
the slope of B on A (-n_a/n_b from the minor singular vector n), while OLS and Kalman -- and the spread
log_a - beta * log_b -- use A on B. True beta 0.7 gave TLS 1.429 (= 1/0.7). Used only for reporting (stats.py
beta_tls), so no result depended on it. Fix: slope = -n_b/n_a.
Checks: with tiny noise TLS ~= OLS ~= true beta for beta in {0.7, 1.5, -0.4}; TLS is symmetric (tls(b, a) = 1/tls(a, b)).
Run: python debug/_verify_tls_hedge_direction.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from analysis import HedgeRatioEstimator as H

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


rng = np.random.default_rng(0)
lb = np.cumsum(rng.normal(0, 0.01, 2000)) + 4.0
for beta in (0.7, 1.5, -0.4):
    la = beta * lb + 1.0 + rng.normal(0, 0.0005, lb.size)
    t = H.tls(la, lb)
    check(f"tls_matches_true_beta_{beta}", abs(t - beta) < 0.01, f"tls={t:.4f}")
    check(f"tls_symmetric_{beta}", abs(H.tls(lb, la) * t - 1.0) < 0.01, f"tls(b,a)*tls(a,b)={H.tls(lb, la) * t:.4f}")
print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
if FAIL:
    print("FAILED:", FAIL); sys.exit(1)
