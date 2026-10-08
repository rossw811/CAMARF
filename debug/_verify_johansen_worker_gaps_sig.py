"""
Regression test for code review A11 (verified 2026-10-07, fixed the same day) in analysis._johansen_worker:
  (1) gaps: rows were packed with `log[isfinite(a)&isfinite(b)&isfinite(c)]`, stitching the trio straight across a
      genuine data outage (the BUG-D77 pattern the pairwise EG worker already avoids with
      data.longest_gap_respecting_segment);
  (2) significance: TrioBuilder.test_trios resolved sig_level (Config.ANALYSIS.JOHANSEN_SIGNIFICANCE) and wrote it
      to the bias audit log, but the worker always used the 5% critical-value column.
Checks: a 1h trio with a 150-bar outage (a genuine gap at 1h; daily gaps follow the DAILY_GAP_BREAKS arm, as
for EG) is tested on the longest gap-free segment only
(n_bars < finite count); sig 0.01 uses coint_johansen's 1% column (index 2), 0.10 the 10% column (index 0), 0.05
index 1; an unsupported level is refused.
Run: python debug/_verify_johansen_worker_gaps_sig.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import analysis

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    rng = np.random.default_rng(0)
    n = 600
    common = np.cumsum(rng.normal(0, .01, n))
    a = common + rng.normal(0, .002, n)
    b = 0.8 * common + rng.normal(0, .002, n)
    c = 1.2 * common + rng.normal(0, .002, n)
    for arr in (a, b, c):
        arr[300:450] = np.nan                       # a 150-bar 1h outage (> the 120 h routine-closure ceiling)
    finite = int(np.isfinite(a).sum())
    import inspect
    nargs = len(inspect.signature(analysis._johansen_worker).parameters)
    try:
        r = analysis._johansen_worker(("A", "B", "C", a, b, c, 0, 1, "1h", 0.05))
    except Exception as e:
        check("worker_accepts_tf_and_sig", False, f"{type(e).__name__}: {e}"); return finish()
    check("tested_on_gap_free_segment", r.get("ok") and r.get("n_bars", finite) < finite,
          f"n_bars={r.get('n_bars')} finite={finite}")
    for sig, col in ((0.10, 0), (0.05, 1), (0.01, 2)):
        r = analysis._johansen_worker(("A", "B", "C", a, b, c, 0, 1, "1h", sig))
        check(f"sig_{sig}_column_{col}", r.get("crit_column") == col, r.get("crit_column"))
    r = analysis._johansen_worker(("A", "B", "C", a, b, c, 0, 1, "1h", 0.07))
    check("unsupported_level_refused", r.get("ok") is False and "sig_level" in str(r.get("error", "")), r.get("error"))
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
