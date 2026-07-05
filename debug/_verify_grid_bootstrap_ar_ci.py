"""
Synthetic verification for research/grid_bootstrap_ar_ci.py.

Coverage check: for a known true AR(1) coefficient rho_true, simulate many
independent series, compute the 90% grid-bootstrap CI on each, and check
that the true rho falls inside the CI in roughly 90% of trials (not
exactly 90% — this uses a small number of trials for runtime reasons, so a
generous band is checked, not a precise calibration).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from research.grid_bootstrap_ar_ci import grid_bootstrap_ci

failures = []

RHO_TRUE = 0.95  # near-unit-root, exactly the regime this test targets
N_TRIALS = 15
n_covered = 0

for trial in range(N_TRIALS):
    rng = np.random.default_rng(100 + trial)
    n = 400
    z = np.zeros(n)
    for t in range(1, n):
        z[t] = RHO_TRUE * z[t - 1] + rng.normal(scale=1.0)
    boot_rng = np.random.default_rng(200 + trial)
    r = grid_bootstrap_ci(z, n_grid=25, n_boot=80, conf_level=0.90, rng=boot_rng, grid_halfwidth=0.12)
    if not r["ok"] or not np.isfinite(r.get("ci_lo", np.nan)):
        print(f"Trial {trial}: no usable CI ({r.get('note', r.get('error'))})")
        continue
    covered = r["ci_lo"] <= RHO_TRUE <= r["ci_hi"]
    n_covered += int(covered)
    print(f"Trial {trial}: rho_hat={r['rho_hat']:.4f} CI=[{r['ci_lo']:.4f}, {r['ci_hi']:.4f}] "
          f"covers_true={covered}")

coverage_rate = n_covered / N_TRIALS
print(f"\nCoverage rate: {n_covered}/{N_TRIALS} = {coverage_rate:.2f} (target ~0.90)")
# Generous band given only 15 trials — this is a sanity check against gross
# miscalibration (e.g. covering 30% of the time), not a precise size test.
if coverage_rate < 0.60:
    failures.append(f"Coverage rate {coverage_rate:.2f} far too low for a nominal 90% CI")

if failures:
    print(f"\nFAILED ({len(failures)} issue(s)):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("\nALL CHECKS PASSED")
    sys.exit(0)
