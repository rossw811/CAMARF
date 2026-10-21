"""
R8.1 (code review 2026-09-26, CONFIRMED; fixed 2026-10-20): news_impact_asymmetry.py coded "after narrowing" as
dz_{t-1} < 0. Narrowing means the spread moved TOWARD zero (|z| fell); with z on both sides of 0 each sign group is
half narrowing and half widening, so the variance ratio is pulled to 1 by construction. Also, the caller compacted the
deltas, so a lag could span a data gap. Fixed: news_impact_asymmetry_test(z) takes the z LEVEL series (NaN at masked
bars), narrowing_{t-1} = |z_{t-1}| < |z_{t-2}|, and only uses rows where z_t, z_{t-1}, z_{t-2} are all finite.
Checks: (1) a planted asymmetry (larger moves after widening) is detected; (2) a symmetric AR(1) z is not flagged;
(3) a NaN breaks the lag chain (no row spans it).
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


from news_impact_asymmetry import news_impact_asymmetry_test as t  # noqa: E402

rng = np.random.default_rng(5)
n = 4000
z = np.zeros(n)
for i in range(2, n):                      # mean-reverting, shocks 2x larger right after a widening move
    widened = abs(z[i - 1]) > abs(z[i - 2])
    z[i] = 0.9 * z[i - 1] + rng.normal(0, 2.0 if widened else 1.0)
r = t(z, n_perm=500, rng=np.random.default_rng(1))
check("1. planted asymmetry detected (ratio narrow/widen < 1, p < 0.01)",
      r.get("ok") and r["variance_ratio_narrow_over_widen"] < 0.8 and r["pvalue"] < 0.01, f"{r.get('variance_ratio_narrow_over_widen')} {r.get('pvalue')}")
z0 = np.zeros(n)
for i in range(1, n):
    z0[i] = 0.9 * z0[i - 1] + rng.normal()
r0 = t(z0, n_perm=500, rng=np.random.default_rng(2))
check("2. symmetric AR(1) not flagged at 1%", r0.get("ok") and r0["pvalue"] > 0.01, f"{r0.get('pvalue')}")
zg = z0.copy(); zg[100] = np.nan
rg = t(zg, n_perm=10, rng=np.random.default_rng(3))
check("3. a NaN removes the 3 rows whose window spans it", rg.get("ok") and rg["n_narrow"] + rg["n_widen"] == (n - 2) - 3,
      f"{rg.get('n_narrow', 0) + rg.get('n_widen', 0)} vs {(n - 2) - 3}")
print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(1 if failed else 0)
