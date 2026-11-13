"""
Synthetic checks for research/p2_placebo_power.py
  1. planted_spread (piecewise lfilter) = the plain recursion u_t = phi_t u_(t-1) + e_t, for 0-3 change points
  2. phi_path: full / starts_mid / ends_mid hold where documented (mid = the middle common date of year y)
  3. planted_leg: a - b* = mean + u exactly; where the relation does not hold, the spread moves with the pair's own noise
     (d(a - b*) = d(a - b)); point-in-time: data after year y does not change year y's (a, b*)
  4. power ordering with white noise, 252 bars, fixed_adf at 5%: hl 5 > hl 120 > random-walk spread (paired draws)
  5. one_true_rejected = BH over [plant] + others; the m-dependent cutoff alpha/m is what decides a lone true pair
  6. bh_bounds: each family uses its own year's m; the planted pair's own null p is excluded from "others";
     all_true = BH over the year's planted p-values
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))

from p2_placebo_power import bh_bounds, one_true_rejected, phi_path, planted_leg, planted_spread  # noqa: E402
from yearly_family_test import _pvalue, bh_reject  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


rng = np.random.default_rng(20261113)


def naive(e, ph):
    u = np.empty(len(e)); u[0] = e[0]
    for t in range(1, len(e)):
        u[t] = ph[t] * u[t - 1] + e[t]
    return u


worst = 0.0
for trial in range(200):
    n = int(rng.integers(2, 400))
    e = rng.normal(size=n)
    ph = np.full(n, rng.uniform(0.5, 1.0))
    for c in rng.integers(0, n, size=int(rng.integers(0, 4))):
        ph[c:] = rng.choice([1.0, rng.uniform(0.5, 0.99)])
    worst = max(worst, float(np.max(np.abs(planted_spread(e, ph) - naive(e, ph)))))
check("1. piecewise lfilter = plain recursion (200 random cases, 0-3 change points)", worst < 1e-10, f"max diff {worst:.2e}")

d = pd.bdate_range("2014-01-01", "2016-12-31")
y = 2015
pos = np.flatnonzero(d.year == y); mid = pos[len(pos) // 2]; phi = 0.5 ** (1 / 20)
f, s, en = (phi_path(d, y, 20, v) for v in ("full", "starts_mid", "ends_mid"))
check("2. phi_path variants",
      np.all(f == phi) and np.all(s[:mid] == 1) and np.all(s[mid:] == phi) and np.all(en[:mid] == phi)
      and np.all(en[mid:] == 1), f"mid {d[mid].date()}")

la = pd.Series(np.cumsum(rng.normal(0, 0.01, len(d))), d)
lb = la + np.cumsum(rng.normal(0, 0.003, len(d)))          # random-walk spread (a placebo-like null pair)
ok3 = True
for v in ("full", "starts_mid", "ends_mid"):
    a, b = planted_leg(la, lb, y, 20, v)
    sp = (la - lb)[a.index]
    e = np.r_[0.0, np.diff(sp.to_numpy())]
    u = planted_spread(e, phi_path(a.index, y, 20, v))
    ok3 &= np.allclose((a - b).to_numpy(), np.nanmean(sp) + u, atol=1e-12) and a.index.max().year == y
    if v == "starts_mid":            # before mid: random walk with the pair's own noise
        k = a.index.get_loc(d[mid])
        ok3 &= np.allclose(np.diff((a - b).to_numpy()[:k]), np.diff(sp.to_numpy()[:k]), atol=1e-12)
la2, lb2 = la.copy(), lb.copy()
la2[la2.index.year > y] += 5.0; lb2[lb2.index.year > y] -= 3.0
a1, b1 = planted_leg(la, lb, y, 20, "full"); a2, b2 = planted_leg(la2, lb2, y, 20, "full")
ok3 &= a1.equals(a2) and b1.equals(b2)
check("3. planted_leg: a - b* = mean + u; own noise where not holding; nothing after year y used", bool(ok3))

dy = pd.bdate_range("2015-01-01", "2015-12-31"); R = 300
rej = np.zeros((R, 3), bool)
for i in range(R):
    la = pd.Series(np.cumsum(rng.normal(0, 0.01, len(dy))), dy)
    lb = la + np.cumsum(rng.normal(0, 0.003, len(dy)))
    for j, hl in enumerate((5, 120)):
        a, b = planted_leg(la, lb, 2015, hl, "full")
        rej[i, j] = _pvalue(a, b, "fixed_adf") < 0.05
    rej[i, 2] = _pvalue(la, lb, "fixed_adf") < 0.05
r = rej.mean(0)
check("4. power ordering hl5 > hl120 > null (white noise, 252 bars)", r[0] > r[1] > r[2] and r[0] > 0.9,
      f"hl5 {r[0]:.3f} hl120 {r[1]:.3f} null {r[2]:.3f}")

others = np.linspace(0.06, 0.99, 26)                         # 26 nulls, none small: m = 27, lone cutoff 0.05/27
cut = 0.05 / 27
ok5 = one_true_rejected(cut * 0.99, others) and not one_true_rejected(cut * 1.01, others)
for _ in range(500):
    p0, o = float(rng.uniform(0, 0.05)), rng.uniform(0, 1, int(rng.integers(1, 60)))
    ok5 &= one_true_rejected(p0, o) == bool(bh_reject(np.r_[p0, o], 0.05)[0])
ok5 &= not one_true_rejected(np.nan, others)
check("5. one_true = BH over [plant] + others; lone pair needs alpha/m", bool(ok5), f"cutoff {cut:.5f}")

N = pd.DataFrame({"family": ["kept"] * 2 + ["ungated"] * 4, "seed": 1, "year": 2015,
                  "symbol_a": [1, 3, 1, 3, 5, 7], "symbol_b": [2, 4, 2, 4, 6, 8],
                  "pvalue": [0.0001, 0.9, 0.0001, 0.9, 0.9, 0.9], "rejected": False, "test": "fixed_adf"})
P = pd.DataFrame({"seed": 1, "year": 2015, "half_life": 5, "variant": "full", "symbol_a": [1, 3, 5, 7],
                  "symbol_b": [2, 4, 6, 8], "pvalue": [0.03, 0.02, 0.9, 0.9], "test": "fixed_adf"})
B = bh_bounds(N, P).set_index(["family", "symbol_a"])
# pair (3,4) planted p 0.02: kept m=2 -> others = [p of (1,2) = 0.0001] -> BH: sorted [0.0001, 0.02] vs [0.025, 0.05] ->
# both pass -> rejected. ungated m=4 -> others [0.0001, 0.9, 0.9] -> 0.02 <= 0.05*2/4 = 0.025 -> rejected.
# pair (1,2) planted p 0.03: its own null 0.0001 must NOT count. kept: others [0.9] -> 0.03 > 0.025 -> not rejected
# (counting its own null: [0.0001, 0.03, 0.9] -> 0.03 <= 0.0333 -> rejected, the mutant). ungated: 0.03 > 0.0125 -> no.
ok6 = (B.loc[("kept", 3), "m"] == 2 and B.loc[("ungated", 3), "m"] == 4 and B.loc[("kept", 3), "one_true"]
       and B.loc[("ungated", 3), "one_true"] and not B.loc[("kept", 1), "one_true"] and not B.loc[("ungated", 1), "one_true"]
       and len(B.loc["kept"]) == 2 and len(B.loc["ungated"]) == 4)
# all_true, ungated: planted [0.03, 0.02, 0.9, 0.9] -> 0.02 > 0.0125, 0.03 > 0.025 -> nothing; kept [0.03, 0.02] -> both
ok6 &= B.loc[("kept", 3), "all_true"] and not B.loc[("ungated", 3), "all_true"]
check("6. bh_bounds: own m per family, own null excluded, all_true over planted p-values", bool(ok6))

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(1 if failed else 0)
