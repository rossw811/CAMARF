"""
research/weak_exogeneity_test.py rebuilt on the point-in-time pool (2026-10-25; PAPER.md section 7.14 result "not citable
until re-run", ERRATA "Johansen trio specification"). Checks:
  1. restricted constant: a pair where only B error-corrects and the relation has an intercept of 20 is read as
     "A weakly exogenous, B adjusts" with deterministic="ci" (the default)
  2. gaps: legs with a 150-bar 1h outage (bars 1000-1149 of 2500) are tested on the longest gap-respecting segment only, never stitched across
     the outage (the BUG-D77 pattern the old script's finite-row packing had)
  3. the summary's symmetric reading (one leg adjusts / both / neither) does not change when legs A and B are swapped;
     "A leads" depends on which leg the pool calls A
Run: python debug/_verify_weak_exogeneity_restricted.py
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


import weak_exogeneity_test as we  # noqa: E402

if not all(hasattr(we, f) for f in ("pair_segment", "summarize")):
    check("pair_segment and summarize exist", False)
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1)

g = np.random.default_rng(5)
T = 2500
a = np.cumsum(g.normal(0, 0.01, T))                     # A: random walk, never responds
b = np.zeros(T)
b[0] = a[0] - 20
for t in range(1, T):                                    # B corrects toward a - 20
    b[t] = b[t - 1] + (a[t] - a[t - 1]) - 0.08 * (b[t - 1] - (a[t - 1] - 20)) + g.normal(0, 0.004)
r = we.test_weak_exogeneity(a, b)
check("1 restricted constant: only B adjusts -> A_leads", r.get("verdict") == "A_leads" and r.get("deterministic") == "ci",
      f"{r.get('verdict')} p_a {r.get('p_alpha_a', np.nan):.3f} p_b {r.get('p_alpha_b', np.nan):.2e} {r.get('deterministic')}")

ga, gb = a.copy(), b.copy()
ga[1000:1150] = np.nan
gb[1000:1150] = np.nan
idx = pd.date_range("2024-01-01", periods=T, freq="1h")
seg = we.pair_segment(pd.Series(ga, idx), pd.Series(gb, idx), "1h")
check("2 tested on the longest gap-respecting segment only", seg is not None and len(seg) == T - 1150,
      f"{None if seg is None else len(seg)} (longest run {T - 1150}, finite {T - 150})")

R = pd.DataFrame({"p_alpha_a": [0.5, 0.01, 0.01, 0.4, 0.02], "p_alpha_b": [0.01, 0.6, 0.02, 0.3, 0.7]})
S = pd.DataFrame({"p_alpha_a": R["p_alpha_b"], "p_alpha_b": R["p_alpha_a"]})
s1, s2 = we.summarize(R), we.summarize(S)
sym = {k: s1[k] for k in ("one_leg_adjusts", "both_adjust", "neither_adjusts")}
check("3 symmetric summary invariant to swapping legs; A_leads is not",
      sym == {k: s2[k] for k in sym} and s1["A_leads"] != s2["A_leads"], f"{s1} vs {s2}")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
