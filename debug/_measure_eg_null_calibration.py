"""
V3 (E1 validity check, 2026-11-05): where does the placebo's excess of tiny EG p-values come from?
E1 v2 seed 1: placebo window rates vs nominal -- p<0.05 ~0.4x, p<1e-3 1.1-1.6x, p<1e-4 2.6-5.9x.
Production test on null pairs (no cointegration), 2520-bar windows, exactly as discovery calls it
(statsmodels coint, trend="c", maxlag=Config.ANALYSIS.EG_MAX_LAG, autolag="aic"; both directions, pair p = max):
  A  independent Gaussian random walks
  B  Gaussian, return correlation 0.6 (the prefilter level)
  C  correlation 0.6, GARCH(1,1) volatility clustering, Student-t(4) shocks, shared volatility
  D  C plus one 252-bar crisis stretch at 3x volatility
Output: rejection rate at 0.05 / 1e-2 / 1e-3 / 1e-4 for the production p (max) and the min-direction p.
Run: python debug/_measure_eg_null_calibration.py [reps]   (CachyOS 2026-11-11, 40000 reps: Development.md 2026-11-11 V3)
"""
import os
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
N = 2520
TH = (0.05, 1e-2, 1e-3, 1e-4)


def returns(dgp, rng):
    z = rng.standard_normal((N, 2))
    if dgp == "A":
        e = z
    else:
        rho = 0.6
        e = np.column_stack([z[:, 0], rho * z[:, 0] + np.sqrt(1 - rho ** 2) * z[:, 1]])
        if dgp in ("C", "D"):
            t = rng.standard_t(4, (N, 2)) / np.sqrt(2.0)                    # unit-variance t(4)
            e = np.column_stack([t[:, 0], rho * t[:, 0] + np.sqrt(1 - rho ** 2) * t[:, 1]])
            h = np.empty(N); h[0] = 1.0
            w, a, b = 0.05, 0.08, 0.90                                        # persistence 0.98, unconditional var 2.5
            for i in range(1, N):
                h[i] = w + a * h[i - 1] * e[i - 1, 0] ** 2 + b * h[i - 1]
            e = e * np.sqrt(h / 2.5)[:, None]
            if dgp == "D":
                s = rng.integers(0, N - 252)
                e[s:s + 252] *= 3.0
    return 0.015 * e


def one(args):
    dgp, seed = args
    from statsmodels.tsa.stattools import coint
    from config import Config
    rng = np.random.default_rng(seed)
    r = returns(dgp, rng)
    la, lb = np.log(50) + np.cumsum(r[:, 0]), np.log(40) + np.cumsum(r[:, 1])
    L = Config.ANALYSIS.EG_MAX_LAG
    p1 = coint(la, lb, trend="c", maxlag=L, autolag="aic")[1]
    p2 = coint(lb, la, trend="c", maxlag=L, autolag="aic")[1]
    return dgp, max(p1, p2), min(p1, p2)


if __name__ == "__main__":
    reps = int(sys.argv[1]) if len(sys.argv) > 1 else 40000
    tasks = [(d, 1_000_000 * k + i) for k, d in enumerate("ABCD") for i in range(reps)]
    res = {d: ([], []) for d in "ABCD"}
    with ProcessPoolExecutor(max_workers=max(1, min(8, (os.cpu_count() or 2) - 4))) as ex:
        for d, pmax, pmin in ex.map(one, tasks, chunksize=500):
            res[d][0].append(pmax); res[d][1].append(pmin)
    print(f"reps per scenario: {reps}; window {N} bars")
    for d in "ABCD":
        pmax, pmin = np.array(res[d][0]), np.array(res[d][1])
        row = "  ".join(f"p<{t:g}: max {np.mean(pmax < t) / t:5.2f}x ({int((pmax < t).sum())}) "
                        f"min {np.mean(pmin < t) / t:5.2f}x" for t in TH)
        print(f"{d}: {row}")
