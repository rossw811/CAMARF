"""
Synthetic checks for research/p2_share_class_family.py and the fixed-hedge mode of research/yearly_family_test.py.
  1. family rules: same PERMCO, common shares only, active at T, listed >= 2 years, has a file; nothing dated after T
  2. family_by_year decides each year at its own Dec 31 (a class listed in 2010 enters the 2012 family, not 2011)
  3. fixed_adf rejects a stationary log spread with a 1,500:1 price ratio (intercept absorbs it)
  4. fixed_adf size on independent random walks near nominal (5%), and EG's too
  5. fixed_adf has more power than EG on the same fast-reverting one-year pairs (the point of the fixed hedge)
  6. a per-year family is respected: a pair absent from year y's family has no year-y row
  7. apply_classification: tracking pairs dropped, same-claim kept only from same_claim_from_year, unclassified pairs
     dropped and reported (fail-closed)
  8. the declared classification file covers the real gated pairs with a source URL each, and every row is one of
     same_claim / tracking / other_structural
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


from p2_share_class_family import CLASSIFICATION_CSV, apply_classification, family_by_year, share_class_family  # noqa: E402
from yearly_family_test import yearly_family_tests  # noqa: E402

N = pd.DataFrame([
    # permno, permco, namedt, nameenddt, shrcd
    (1, 100, "2000-01-01", "2030-12-31", 11), (2, 100, "2000-01-01", "2030-12-31", 11),   # pair, kept
    (3, 100, "2000-01-01", "2030-12-31", 12),                                              # foreign shrcd: out
    (4, 200, "2000-01-01", "2030-12-31", 10), (5, 201, "2000-01-01", "2030-12-31", 10),   # different permco: out
    (6, 300, "2000-01-01", "2030-12-31", 11), (7, 300, "2010-06-01", "2030-12-31", 11),   # 7 listed 2010-06
    (8, 400, "2000-01-01", "2030-12-31", 11), (9, 400, "2000-01-01", "2011-06-30", 11),   # 9 ends 2011-06
    (10, 500, "2000-01-01", "2030-12-31", 11), (11, 500, "2000-01-01", "2030-12-31", 11),  # 11 has no file
    (12, 600, "2000-01-01", "2030-12-31", 11), (13, 600, "2013-01-01", "2030-12-31", 11),  # 13 after T
], columns=["permno", "permco", "namedt", "nameenddt", "shrcd"])
HAVE = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13]

f11 = share_class_family(N, HAVE, "2011-12-31")
check("1. family rules at 2011-12-31", f11 == [(1, 2)], str(f11))
# mutant guard: a permco-6 pair at 2012-12-31 (7 listed 2.5 years) must now enter; 13 (2013) must not
f12 = share_class_family(N, HAVE, "2012-12-31")
check("1b. 2-year listing and future rows", f12 == [(1, 2), (6, 7)], str(f12))
fy = family_by_year(N, HAVE, [2011, 2012])
check("2. family_by_year decided at each Dec 31", fy == {2011: [(1, 2)], 2012: [(1, 2), (6, 7)]}, str(fy))

rng = np.random.default_rng(20261112)
dates = pd.bdate_range("2015-01-01", "2015-12-31")
n = len(dates)


def ou(phi, sd, n):
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = phi * x[t - 1] + rng.normal(0, sd)
    return x


# 3. BRK-like: A = 1,500 x B in level, log spread stationary (5-day half-life)
common = np.cumsum(rng.normal(0, 0.01, n))
sp = ou(0.5 ** (1 / 5), 0.01, n)
lp = {"A": pd.Series(np.log(1500) + common + sp, dates), "B": pd.Series(common, dates)}
r = yearly_family_tests(lp, [("A", "B")], test="fixed_adf")
check("3. fixed_adf rejects 1,500:1 stationary spread", bool(r["rejected"].iloc[0]), f"p={r['pvalue'].iloc[0]:.2e}")


def paired(make, reps):
    """Both tests on the SAME draws: rejection indicators (fixed_adf, eg) at 5%."""
    out = np.zeros((reps, 2), bool)
    for i in range(reps):
        lp = make()
        for j, t in enumerate(("fixed_adf", "eg")):
            out[i, j] = yearly_family_tests(lp, [("A", "B")], alpha=0.05, test=t)["pvalue"].iloc[0] <= 0.05
    return out


def walks():
    return {"A": pd.Series(np.cumsum(rng.normal(0, 0.01, n)), dates),
            "B": pd.Series(np.cumsum(rng.normal(0, 0.01, n)), dates)}


# 1,000 draws: SE 0.007. Standalone 3,000-draw run (scratch, 2026-11-12): fixed_adf AIC 0.054, BIC 0.052, lag 0 0.049.
REPS = 1000
s = paired(walks, REPS)
se = np.sqrt(0.05 * 0.95 / REPS)
check("4. size near 5% on independent walks (within 3 SE)", bool(np.all(np.abs(s.mean(0) - 0.05) <= 3 * se)),
      f"fixed_adf {s[:, 0].mean():.3f} eg {s[:, 1].mean():.3f} (3SE {3*se:.3f})")


def fast_pair(hl=20, sd=0.01):
    c = np.cumsum(rng.normal(0, 0.01, n))
    return {"A": pd.Series(c + ou(0.5 ** (1 / hl), sd, n), dates), "B": pd.Series(c, dates)}


REPS_P = 300
w = paired(fast_pair, REPS_P)
d = w[:, 0].astype(float) - w[:, 1]                # paired difference: same draws, lower variance than two samples
check("5. fixed_adf power > EG on the same draws (20-day half-life, one year), by > 3 paired SE",
      d.mean() > 3 * d.std(ddof=1) / np.sqrt(REPS_P),
      f"fixed_adf {w[:, 0].mean():.3f} eg {w[:, 1].mean():.3f} diff {d.mean():.3f} (3SE {3*d.std(ddof=1)/np.sqrt(REPS_P):.3f})")

dates2 = pd.bdate_range("2015-01-01", "2016-12-31")
lp2 = {k: pd.Series(np.cumsum(rng.normal(0, 0.01, len(dates2))), dates2) for k in "ABCD"}
r2 = yearly_family_tests(lp2, {2015: [("A", "B")], 2016: [("A", "B"), ("C", "D")]}, test="fixed_adf")
got = sorted(map(tuple, r2[["symbol_a", "symbol_b", "year"]].values.tolist()))
check("6. per-year family respected", got == [("A", "B", 2015), ("A", "B", 2016), ("C", "D", 2016)], str(got))

cls = pd.DataFrame({"permno_a": [1, 6, 8], "permno_b": [2, 7, 9], "same_claim_from_year": [1900, 2012, None]})
fam = {2011: [(1, 2), (6, 7), (8, 9), (10, 11)], 2012: [(1, 2), (6, 7)]}
kept, unc = apply_classification(fam, cls)
check("7. classification: tracking dropped, from-year respected, unclassified dropped + reported",
      kept == {2011: [(1, 2)], 2012: [(1, 2), (6, 7)]} and unc == {2011: [(10, 11)], 2012: []}, f"{kept} {unc}")
C = pd.read_csv(os.path.join(ROOT, CLASSIFICATION_CSV))
check("8. declared classification file: 22 pairs, sourced, valid classes",
      len(C) == 22 and C["source_url"].str.startswith("http").all()
      and set(C["classification"]) <= {"same_claim", "tracking", "other_structural"},
      str(C["classification"].value_counts().to_dict()))

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(1 if failed else 0)
