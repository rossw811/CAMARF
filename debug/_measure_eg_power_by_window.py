"""2026-11-11 (one-year discovery arm, dropped on this evidence): EG power by window length x half-life x spread s.d.: production coint call, max over both directions. Planted pair: a random walk
(daily sd 0.015), b = 0.3 + 0.9 a + AR(1) spread with s.d. sd. Rejection share at the real BH cutoff
(~2e-5, E1 score_false_share) and at 1e-3."""
import sys, os
sys.path.insert(0, os.getcwd())
import numpy as np
from concurrent.futures import ProcessPoolExecutor
from statsmodels.tsa.stattools import coint

def one(args):
    W, hl, sd, seed = args
    r = np.random.default_rng(seed)
    a = np.log(50) + np.cumsum(r.normal(0, 0.015, W))
    phi = 0.5 ** (1 / hl); e = r.normal(0, sd * np.sqrt(1 - phi ** 2), W + 200); s = np.zeros(W + 200)
    for i in range(1, W + 200):
        s[i] = phi * s[i - 1] + e[i]
    b = 0.3 + 0.9 * a + s[200:]
    p = max(coint(a, b, trend="c", maxlag=10, autolag="aic")[1], coint(b, a, trend="c", maxlag=10, autolag="aic")[1])
    return W, hl, sd, p



if __name__ == "__main__":
    import numpy as np
    reps = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    grid = ([(252, h, 0.10) for h in (1, 2, 3, 5, 10, 20)] + [(2520, h, 0.10) for h in (5, 20, 60, 120)]
            + [(252, h, sd) for sd in (0.02, 0.05) for h in (2, 5, 10, 20)])
    tasks = [(W, h, sd, 10_000 * i + k) for i, (W, h, sd) in enumerate(grid) for k in range(reps)]
    res = {}
    with ProcessPoolExecutor(max_workers=max(1, min(3, (os.cpu_count() or 2) - 2))) as ex:
        for W, h, sd, p in ex.map(one, tasks, chunksize=20):
            res.setdefault((W, sd, h), []).append(p)
    print(f"reps {reps}; p<2e-5 ~ the real Tier 3 BH cutoff (E1 score_false_share)")
    for (W, sd, h), ps in res.items():
        ps = np.array(ps)
        print(f"window {W:>4} spread sd {sd:.2f} half-life {h:>3}: p<2e-5 {np.mean(ps < 2e-5):.2f}  "
              f"p<1e-3 {np.mean(ps < 1e-3):.2f}  median p {np.median(ps):.1e}")
