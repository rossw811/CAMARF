"""
Johansen trios, restricted-constant comparison arm (Ross, DECISIONS_2026-10-21 #3). The approved det_order 0 switch is
not applied: statsmodels' det_order 0 is the unrestricted constant (drift critical values) and rejected 11.7% of
independent driftless random walks at a nominal 5%. Checks on research/cointegration_estimator_arms:
  1. johansen_trace_n reproduces the bivariate johansen_trace values of the committed code exactly (refactor safe)
  2. trace(r) is decreasing in r and trace(n-1) >= 0
  3. size: 3 independent driftless random walks, T = 500 -> restricted arm rejects rank 0 in 2.5-8% (nominal 5%);
     statsmodels det_order 0 over-rejects on the same draws (> restricted)
  4. power: trio with one cointegrating relation and a large intercept (log-price-like) -> restricted arm finds
     rank >= 1 in >= 90%, and statsmodels det_order -1 loses power there (the reason -1 is not the answer either)
  5. johansen_crit_n_interp equals johansen_crit_n on a grid point and lies between the bracketing grid values
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


import research.cointegration_estimator_arms as arms  # noqa: E402

if not hasattr(arms, "johansen_rank_restricted"):
    check("trio arm exists", False)
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1)
from statsmodels.tsa.vector_ar.vecm import coint_johansen  # noqa: E402

rng = np.random.default_rng(7)
y = np.cumsum(rng.normal(size=400)); x = 0.5 * y + rng.normal(size=400) + 3
v1 = arms.johansen_trace(y, x)
v2 = arms.johansen_trace(np.cumsum(rng.normal(size=300)), np.cumsum(rng.normal(size=300)))
check("1 bivariate values unchanged by the n-variate refactor",
      np.isclose(v1, 164.63996423942692, rtol=1e-12) and np.isclose(v2, 5.143801826449093, rtol=1e-12), f"{v1} {v2}")

tr = arms.johansen_trace_n(np.column_stack([y, x, np.cumsum(rng.normal(size=400))]))
check("2 trace decreasing in r, last >= 0", np.all(np.diff(tr) <= 0) and tr[-1] >= 0, str(tr))

T, R = 500, 300
crit = {m: arms.johansen_crit_n(T, m, 0.05, None, reps=1000) for m in (1, 2, 3)}
cfun = lambda TT, m, lev, k: crit[m]
rej_r, rej_d0, rej_dm1 = 0, 0, 0
g = np.random.default_rng(11)
for _ in range(R):
    Y = np.cumsum(g.normal(size=(T, 3)), axis=0)
    rej_r += arms.johansen_rank_restricted(Y, crit=cfun)["rank"] >= 1
    j0 = coint_johansen(Y, det_order=0, k_ar_diff=1)
    rej_d0 += j0.lr1[0] > j0.cvt[0, 1]
size_r, size_0 = rej_r / R, rej_d0 / R
check("3a restricted arm size at nominal 5%", 0.025 <= size_r <= 0.08, f"{size_r:.3f}")
check("3b statsmodels det_order 0 over-rejects on the same draws", size_0 > size_r, f"det0 {size_0:.3f} vs {size_r:.3f}")

pw_r = pw_m1 = 0
for _ in range(R):
    w = np.cumsum(g.normal(size=T)); z = np.cumsum(g.normal(size=T))
    e = np.zeros(T)
    for t in range(1, T):
        e[t] = 0.7 * e[t - 1] + g.normal()
    Y = np.column_stack([w + 0.8 * z + 20 + e, w, z])          # one relation, intercept 20
    pw_r += arms.johansen_rank_restricted(Y, crit=cfun)["rank"] >= 1
    jm = coint_johansen(Y, det_order=-1, k_ar_diff=1)
    pw_m1 += jm.lr1[0] > jm.cvt[0, 1]
check("4a restricted arm power with an intercept", pw_r / R >= 0.90, f"{pw_r / R:.3f}")
check("4b det_order -1 loses power with an intercept", pw_m1 / R < pw_r / R, f"det-1 {pw_m1 / R:.3f}")

c400 = arms.johansen_crit_n(400, 3, 0.05, None, reps=500)
ci400 = arms.johansen_crit_n_interp(400, 3, 0.05, None, reps=500)
c200, c800 = arms.johansen_crit_n(200, 3, 0.05, None, reps=500), arms.johansen_crit_n(800, 3, 0.05, None, reps=500)
c600 = arms.johansen_crit_n_interp(600, 3, 0.05, None, reps=500)
c400b = arms.johansen_crit_n(400, 3, 0.05, None, reps=500)
check("5 interpolation: exact on the grid, bracketed off it",
      ci400 == c400 and min(c400b, c800) <= c600 <= max(c400b, c800), f"{c200:.2f} {c400:.2f} {c600:.2f} {c800:.2f}")

# 6. the real-data script's per-trio comparison on one synthetic cointegrated trio
from research.johansen_trio_arm_comparison import compare_trio  # noqa: E402
w = np.cumsum(g.normal(size=T)); z = np.cumsum(g.normal(size=T))
Y = np.column_stack([w + 0.8 * z + 20 + g.normal(size=T) * 0.5, w, z])
r = compare_trio(Y, crit=cfun)
check("6 compare_trio: restricted rejects, fields present",
      r["restricted_reject0"] and r["restricted_rank"] >= 1 and {"prod_det_m1_reject0", "det0_reject0", "n_bars"} <= set(r),
      str({k: r[k] for k in ("prod_det_m1_reject0", "det0_reject0", "restricted_reject0", "restricted_rank")}))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
