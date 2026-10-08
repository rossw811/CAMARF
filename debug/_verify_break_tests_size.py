"""
Regression test for code review A7 + A8 (verified 2026-10-07): the two structural-break tests behind analysis.py's
coint_frac secondary-evidence override had the wrong critical values.
  A7 StrategyDecayDetector.zivot_andrews (a Quandt-Andrews sup-F on the AR(1) intercept + slope, 15% trimming):
     compared sup-F = sup-Wald/2 with 8.85, the 1-parameter sup-Wald value. For 2 parameters Andrews (1993, Table 1,
     pi0 = 0.15) gives sup-Wald 11.72 at 5%, i.e. sup-F 5.86 -> the test's real size was far below 5% (misses
     breaks -> the override rescues too easily).
  A8 StrategyDecayDetector.cusum: a pointwise +-2*sqrt(t) band on the cumulated OLS residuals is crossed almost
     surely on long series (law of the iterated logarithm) -> "break" nearly always. Fix: Ploberger & Kraemer (1992)
     OLS-CUSUM, sup_t |S_t| / (sigma * sqrt(n)) > 1.358 at 5%.
Checks (Monte Carlo, fixed seeds): under no break (stationary AR(1), phi 0.5, n 600, 300 runs) each test rejects
2%-9% of the time; with a break (phi 0.2 -> 0.9 at mid-sample) the sup-F test rejects in >= 80% of 150 runs; CUSUM
size stays <= 9% at n 3000 (the LIL failure mode).
Run: python debug/_verify_break_tests_size.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import StrategyDecayDetector as S

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def ar1(n, phi, rng, phi2=None):
    e = rng.normal(size=n); x = np.zeros(n)
    for t in range(1, n):
        p = phi if (phi2 is None or t < n // 2) else phi2
        x[t] = p * x[t - 1] + e[t]
    return x


def rate(fn, gen, runs, seed):
    rng = np.random.default_rng(seed)
    return float(np.mean([fn(gen(rng)) is not None for _ in range(runs)]))


def main():
    za0 = rate(S.zivot_andrews, lambda r: ar1(600, 0.5, r), 300, 1)
    cs0 = rate(S.cusum, lambda r: ar1(600, 0.5, r), 300, 2)
    za1 = rate(S.zivot_andrews, lambda r: ar1(600, 0.2, r, 0.9), 150, 3)
    cs_long = rate(S.cusum, lambda r: ar1(3000, 0.5, r), 100, 4)
    check("supF_size_near_5pct", 0.02 <= za0 <= 0.09, f"{za0:.3f}")
    check("cusum_size_near_5pct", 0.02 <= cs0 <= 0.09, f"{cs0:.3f}")
    check("supF_power_on_break", za1 >= 0.80, f"{za1:.3f}")
    check("cusum_size_long_series", cs_long <= 0.09, f"{cs_long:.3f}")
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
