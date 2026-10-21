"""
R4.11 (code review 2026-09-26; fixed 2026-10-20): regime_strength_vs_discovery_regime_test's inner merge on ordered
(symbol_a, symbol_b) dropped pairs whose legs were stored in the opposite order in the two tables. Check:
build_joined_table joins a reversed-order pair, and one pair stored both ways in the segments counts once.
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


import regime_strength_vs_discovery_regime_test as m  # noqa: E402
seg = pd.DataFrame({"symbol_a": ["B", "X", "Y"], "symbol_b": ["A", "Y", "X"], "state": ["coint"] * 3,
                    "strength": ["strong", "weak", "moderate"]})
disc = pd.DataFrame({"symbol_a": ["A", "X"], "symbol_b": ["B", "Y"], "first_regime": ["crisis", "calm"]})
j = m.build_joined_table(seg, disc)
check("reversed-order pair joined", len(j) == 2, f"{len(j)} rows: {j.values.tolist()}")
xy = j[(j.symbol_a == "X") & (j.symbol_b == "Y")]
check("pair stored both ways counted once, strongest label", len(xy) == 1 and xy.strength.iloc[0] == "moderate",
      f"{xy.values.tolist()}")
print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(1 if failed else 0)
