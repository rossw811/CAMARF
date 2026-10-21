"""
Synthetic check for research/dlc_positive_controls_d14.py (D14 positive controls, 2026-10-20).
  1. twin label pairs: every side-A label x side-B label, unordered, no same-side pairs, unmapped labels ignored;
  2. discovery record: pair order does not matter; Tier 1 / Tier 3 prefilter / windows tested / rejected / first
     rejection read correctly; found_by_discovery = Tier 1 confirmed or any Tier 3 window rejected.
"""
import os
import sys

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


try:
    import dlc_positive_controls_d14 as m
except Exception as e:  # noqa: BLE001
    print(f"[FAIL] import: {type(e).__name__}: {e}\n\n0/1 checks passed")
    sys.exit(1)

ids = {"RDS": frozenset({"permco:1"}), "SHEL": frozenset({"permco:2"}), "RDSB": frozenset({"permco:1"}),
       "UL": frozenset({"permco:9"}), "UN": frozenset({"permco:8"}), "XOM": frozenset({"permco:5"}), "ZZ": None}
sides = {"Shell": ({"permco:1"}, {"permco:2"}), "Unilever": ({"permco:8"}, {"permco:9"})}
tw = m.twin_label_pairs(ids, sides)
got = sorted(map(tuple, tw[["symbol_a", "symbol_b"]].values.tolist()))
check("1. twin label pairs", got == [("RDS", "SHEL"), ("RDSB", "SHEL"), ("UL", "UN")], str(got))

tier1 = pd.DataFrame({"symbol_a": ["SHEL", "UL"], "symbol_b": ["RDS", "UN"], "pvalue": [0.001, 0.4],
                      "fdr_confirmed": [True, False]})
t3p = pd.DataFrame({"symbol_a": ["UN"], "symbol_b": ["UL"]})
t3w = pd.DataFrame({"symbol_a": ["UL", "UN", "UL", "RDS"], "symbol_b": ["UN", "UL", "UN", "XOM"],
                    "window_end_date": pd.to_datetime(["2010-12-31", "2008-12-31", "2012-12-31", "2009-12-31"]),
                    "fdr_rejected": [True, False, True, True]})
r = m.discovery_record(tw, tier1, t3p, t3w).set_index(["symbol_a", "symbol_b"])
s = r.loc[("RDS", "SHEL")]
check("2a. Tier 1 read in either order", bool(s.tier1_tested) and s.tier1_pvalue == 0.001 and bool(s.tier1_fdr_confirmed))
u = r.loc[("UL", "UN")]
check("2b. Tier 3 prefilter / windows (either order)", bool(u.tier3_prefilter_passed) and u.tier3_windows_tested == 3
      and u.tier3_windows_rejected == 2, f"{u.tier3_windows_tested} {u.tier3_windows_rejected}")
check("2c. first rejection", u.tier3_first_rejection == pd.Timestamp("2010-12-31"), str(u.tier3_first_rejection))
b = r.loc[("RDSB", "SHEL")]
check("2d. untested twin not found; others found", (not b.found_by_discovery) and not b.tier1_tested
      and bool(s.found_by_discovery) and bool(u.found_by_discovery))
check("2e. a non-twin window (RDS/XOM) is not counted", s.tier3_windows_tested == 0, str(s.tier3_windows_tested))

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(1 if failed else 0)
