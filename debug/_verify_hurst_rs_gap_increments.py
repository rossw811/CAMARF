"""
Regression test (2026-10-07, found re-checking BUG-A7): analysis.HurstEstimator.hurst_rs (and hurst_dfa) -- the production
`hurst_rs < 0.50` gate -- dropped non-finite spread values FIRST and differenced afterwards
(`np.diff(spread[isfinite])`), so an increment could span a data outage (masked to NaN upstream): the level move
across the whole outage became one "increment". Same drop-then-diff class as BUG-D81/D83/D85, fixed there, not here.
Rule: difference the full series, then drop increments touching a NaN.
Checks: an OU spread with 40 NaN outages each hiding a +-3 sd level jump: the fixed estimate equals the estimate on the
same series with the outage rows simply absent from the differencing (no bridged increments) and stays < 0.5; the old
construction is pulled up by the bridged jumps; a gap-free series is unchanged.
Run: python debug/_verify_hurst_rs_gap_increments.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import HurstEstimator

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    rng = np.random.default_rng(3)
    n = 4000
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = 0.9 * x[t - 1] + rng.normal()
    clean = HurstEstimator.hurst_rs(x)
    y = x.copy()
    gap_starts = rng.choice(np.arange(100, n - 100, 90), 40, replace=False)
    for g in gap_starts:                       # a 10-bar outage; the series resumes 3 sd away (a level jump)
        y[g:g + 10] = np.nan
        y[g + 10:] += rng.choice([-1, 1]) * 3 * x.std()
    fixed = HurstEstimator.hurst_rs(y)
    inc = np.diff(y)
    inc = inc[np.isfinite(inc)]                 # the rule: diff first, drop increments touching NaN
    bridged = np.diff(y[np.isfinite(y)])        # the old construction
    check("gap_free_unchanged", np.isfinite(clean) and clean < 0.5, f"{clean:.3f}")
    check("fixture_has_bridging_jumps", np.abs(bridged).max() > 2 * np.abs(inc).max(),
          f"max |bridged inc| {np.abs(bridged).max():.1f} vs max |clean inc| {np.abs(inc).max():.1f}")
    # decisive: hurst_rs on the gapped series must equal the estimator on its clean increments (no bridging)
    ref = HurstEstimator.hurst_rs(np.concatenate([[0.0], np.cumsum(inc)]))   # a series whose increments are `inc`
    check("equals_estimate_on_clean_increments", np.isclose(fixed, ref, atol=1e-9), f"{fixed:.6f} vs {ref:.6f}")
    check("gapped_estimate_below_half", np.isfinite(fixed) and fixed < 0.5, f"{fixed:.3f}")
    # hurst_dfa had the identical drop-then-diff construction (same rule applies)
    zc = np.concatenate([[0.0], np.cumsum(inc)])
    d_gap, d_ref = HurstEstimator.hurst_dfa(y), HurstEstimator.hurst_dfa(zc)
    check("dfa_equals_estimate_on_clean_increments", np.isclose(d_gap, d_ref, atol=1e-9), f"{d_gap:.6f} vs {d_ref:.6f}")
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
