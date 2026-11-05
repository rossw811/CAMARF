"""
Synthetic checks for research/fullsample_gated_arm.py (N2 comparison arm, 2026-11-04).
  1. a pair confirmed by the ungated screen but with no gated window is not in the gated screen;
  2. BH runs over the gated family only: a pair at p = 4e-4 is not confirmed among m = 1,000 but is among m = 10
     (the family-size effect the arm is meant to show), and the flags equal analysis._benjamini_hochberg on that subset;
  3. the original Tier 1 flags restricted to the family are reported separately (fs_orig);
  4. the cleaner's removals are counted (gated_confirmed vs gated_confirmed_clean);
  5. PIT matching ignores leg order, counts both directions, and reads eligible_from of shared pairs;
  6. PIT pairs outside the family are not counted against the screen (pit_in_family).
Run: python debug/_verify_fullsample_gated_arm.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "research")]
import numpy as np
import pandas as pd

from analysis import _benjamini_hochberg
from fullsample_gated_arm import compare, gated_screen, pkey

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


rng = np.random.default_rng(7)
m = 1000
sa = [f"A{i}" for i in range(m)]
sb = [f"B{i}" for i in range(m)]
p = rng.uniform(0.01, 1.0, m)       # nulls, none tiny
p[0] = 1e-7                         # confirmed in any family
p[1] = 4e-4                         # confirmed only in a small family
p[2] = 2e-7                         # confirmed ungated, but never gated-testable
p[3] = 3e-7                         # identity pair: confirmed, removed by the cleaner
sa[3], sb[3] = "X1", "X2"
tier1 = pd.DataFrame({"symbol_a": sa, "symbol_b": sb, "pvalue": p})
rej, _ = _benjamini_hochberg(p, 0.05)
tier1["fdr_confirmed"] = rej
fam_pairs = [0, 1, 3] + list(range(10, 17))          # 10 pairs with a gated window (not pair 2)
t2 = {pkey(sa[i], sb[i]) for i in fam_pairs}
t3 = t2 | {pkey("Z1", "Z2")}                          # a Tier 3-only pair outside Tier 1's list: ignored
cleaner = lambda f: f[~f["symbol_a"].astype(str).str.startswith("X")]
pit = {1: pd.DataFrame({"symbol_a": ["B0", "B11", "Q1"], "symbol_b": ["A0", "A11", "Q2"],
                        "eligible_from": pd.to_datetime(["2015-01-31", "2019-06-30", "2010-01-31"])})}

check("0 setup: ungated BH confirms pairs 0, 2, 3 but not 1",
      bool(tier1.fdr_confirmed[[0, 2, 3]].all()) and not bool(tier1.fdr_confirmed[1]), tier1.fdr_confirmed[:4].tolist())

S, M = compare(tier1, t2, t3, pit, 0.05, cleaner)
s = S[(S.family == "tier2") & (S.k == 1)].iloc[0]
F = gated_screen(tier1, t2, 0.05)
G = {pkey(a, b) for a, b in zip(F.symbol_a[F.fs_gated], F.symbol_b[F.fs_gated])}
check("1 untestable pair 2 not in the gated screen", pkey("A2", "B2") not in G and int(s.m_family) == 10, sorted(map(sorted, G)))
r_sub, _ = _benjamini_hochberg(tier1.pvalue.to_numpy()[fam_pairs], 0.05)
check("2a pair 1 confirmed within the 10-pair family", pkey("A1", "B1") in G)
check("2b gated flags equal analysis._benjamini_hochberg on the subset",
      sorted(map(sorted, G)) == sorted(sorted((sa[i], sb[i])) for i, r in zip(fam_pairs, r_sub) if r))
check("3 original flags in family reported separately", int(s.orig_flags_in_family) == 2 and int(s.gated_confirmed) == 3,
      (s.orig_flags_in_family, s.gated_confirmed))
check("4 cleaner removal counted", int(s.gated_confirmed_clean) == 2 and int(s.ungated_confirmed) == 3
      and int(s.ungated_confirmed_clean) == 2, (s.gated_confirmed_clean, s.ungated_confirmed, s.ungated_confirmed_clean))
check("5 PIT overlap: leg order ignored, both directions, eligible_from of shared",
      int(s.fs_clean_and_pit) == 1 and int(s.fs_clean_only) == 1 and int(s.pit_only) == 1
      and s.shared_eligible_from_median == pd.Timestamp("2015-01-31"),
      (s.fs_clean_and_pit, s.fs_clean_only, s.pit_only, s.shared_eligible_from_median))
check("6 PIT pair outside the family not counted", int(s.pit_pool) == 3 and int(s.pit_in_family) == 2,
      (s.pit_pool, s.pit_in_family))
row = M[(M.symbol_a == "A0") & (M.symbol_b == "B0")]
check("7 membership frame flags pair 0 in screen and pool",
      len(row) == 1 and bool(row.fs_gated_clean_tier2.iloc[0]) and bool(row.pit_k1.iloc[0]))

print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
