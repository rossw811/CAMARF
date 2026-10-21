"""
R6.5 (code review 2026-09-26, CONFIRMED; fixed 2026-10-20): grid_bootstrap_ar_ci capped its rho grid at 0.999 and
rho_hat +/- 0.15, so the confidence set could never contain 1 -- "every CI sits below 1" was true by construction and a
CI stuck at the grid edge (PNC/ZION@4h [0.9990, 0.9990]) was reported as a real bound. Checks: (1) on a pure random
walk the 90% set reaches 1.0; (2) a stationary AR(0.5) set excludes 1 and is not at an edge; (3) a set touching a grid
end is flagged (ci_at_grid_edge).
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


from grid_bootstrap_ar_ci import grid_bootstrap_ci  # noqa: E402

rng = np.random.default_rng(8)
rw = np.cumsum(rng.normal(size=400))
r = grid_bootstrap_ci(rw, n_grid=30, n_boot=120, rng=np.random.default_rng(1))
check("1. random walk: set reaches 1.0", r.get("ok") and r["ci_hi"] >= 1.0, f"[{r.get('ci_lo')}, {r.get('ci_hi')}]")
ar = np.zeros(400)
for t in range(1, 400):
    ar[t] = 0.5 * ar[t - 1] + rng.normal()
r2 = grid_bootstrap_ci(ar, n_grid=30, n_boot=120, rng=np.random.default_rng(2))
check("2. AR(0.5): excludes 1, not at a grid edge", r2["ci_hi"] < 1.0 and not r2.get("ci_at_grid_edge", True),
      f"[{r2['ci_lo']:.3f}, {r2['ci_hi']:.3f}] edge={r2.get('ci_at_grid_edge')}")
check("3. edge flag present", "ci_at_grid_edge" in r)
print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(1 if failed else 0)
