"""
Synthetic ground truth for research/cointegration_estimator_arms.py (endogeneity arm (a), Ross 2026-10-13; written
before the module). OLS on a cointegrating regression is superconsistent but, with an endogenous regressor and serially
correlated errors, biased in finite samples (second-order bias); DOLS (Stock-Watson 1993) and FM-OLS (Phillips-Hansen
1990) remove it. Johansen (1991) is a system test, symmetric in the order of the series.
World: x_t random walk with shocks v_t; u_t = 0.7 u_{t-1} + e_t with corr(e_t, v_t) = 0.8; y_t = 1 + 2 x_t + u_t.
Checks (300 replications, T = 250, seeded):
  1. mean |beta_hat - 2|: DOLS < OLS and FM-OLS < OLS (bias reduction where it matters: short samples)
  2. Johansen trace test, 5% level: size on independent random walks within [0.02, 0.09] (400 reps); power on the
     cointegrated world >= 0.8
  3. symmetry: Johansen's trace statistic is identical (1e-8) with the legs swapped
Run: python debug/_verify_cointegration_estimator_arms.py
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def world(rng, T, coint=True):
    z = rng.multivariate_normal([0, 0], [[1, 0.8], [0.8, 1]], T)
    x = np.cumsum(z[:, 1])
    if not coint:
        return np.cumsum(rng.normal(size=T)), x
    u = np.zeros(T)
    for t in range(1, T):
        u[t] = 0.7 * u[t - 1] + z[t, 0]
    return 1 + 2 * x + u, x


def main():
    try:
        import research.cointegration_estimator_arms as m
    except ImportError as e:
        check("module_exists", False, e); return finish()
    rng = np.random.default_rng(13)
    e_ols, e_dols, e_fm = [], [], []
    for _ in range(300):
        y, x = world(rng, 250)
        e_ols.append(abs(m.ols_beta(y, x) - 2)); e_dols.append(abs(m.dols_beta(y, x) - 2)); e_fm.append(abs(m.fmols_beta(y, x) - 2))
    o, d, f = np.mean(e_ols), np.mean(e_dols), np.mean(e_fm)
    check("dols_beats_ols", d < o, f"mean |err| OLS {o:.4f} DOLS {d:.4f}")
    check("fmols_beats_ols", f < o, f"mean |err| OLS {o:.4f} FM-OLS {f:.4f}")
    rej0 = np.mean([m.johansen_rejects(*world(rng, 250, coint=False)) for _ in range(400)])
    rej1 = np.mean([m.johansen_rejects(*world(rng, 250)) for _ in range(300)])
    check("johansen_size", 0.02 <= rej0 <= 0.09, f"size {rej0:.3f}")
    check("johansen_power", rej1 >= 0.8, f"power {rej1:.3f}")
    y, x = world(rng, 250)
    t1, t2 = m.johansen_trace(y, x), m.johansen_trace(x, y)
    check("johansen_symmetric", abs(t1 - t2) < 1e-8, f"{t1:.6f} vs {t2:.6f}")
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
