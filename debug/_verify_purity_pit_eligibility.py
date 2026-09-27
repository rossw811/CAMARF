"""
Synthetic checks for research/purity_pit_eligibility.py (2026-09-27, Design 2).
  1. eligible_from = end date of the k-th REJECTED window, chronological, ignoring non-rejected windows;
  2. symbol order in the window file may be reversed relative to the pool (code review R1.15) -- still matched;
  3. k=2 drops pairs with a single rejected window; the drop is REPORTED, not silent.
Run: python debug/_verify_purity_pit_eligibility.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from research.purity_pit_eligibility import attach_eligibility

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    W = pd.DataFrame([
        ("A", "B", "2005-12-31", False), ("A", "B", "2008-12-31", True), ("A", "B", "2006-12-31", True),
        ("B", "A", "2012-12-31", True),                        # reversed order, same unordered pair
        ("C", "D", "2010-12-31", True), ("C", "D", "2011-12-31", False),
    ], columns=["symbol_a", "symbol_b", "window_end_date", "fdr_rejected"])
    pool = pd.DataFrame({"symbol_a": ["A", "D", "E"], "symbol_b": ["B", "C", "F"], "tf_label": ["1D"] * 3})
    r1, m1 = attach_eligibility(pool, {"1D": W}, 1)
    e1 = {(a, b): d for a, b, d in zip(r1.symbol_a, r1.symbol_b, pd.to_datetime(r1.eligible_from))}
    check("k1.first_rejected_window", e1.get(("A", "B")) == pd.Timestamp("2006-12-31"), f"{e1.get(('A', 'B'))}")
    check("k1.reversed_pool_order_matched", e1.get(("D", "C")) == pd.Timestamp("2010-12-31"), f"{e1}")
    check("k1.missing_pair_reported", ("E", "F") not in e1 and any(n == 1 for _, n, _ in m1), f"{m1}")
    r2, m2 = attach_eligibility(pool, {"1D": W}, 2)
    e2 = {(a, b): d for a, b, d in zip(r2.symbol_a, r2.symbol_b, pd.to_datetime(r2.eligible_from))}
    check("k2.second_rejected_window", e2.get(("A", "B")) == pd.Timestamp("2008-12-31"), f"{e2}")
    check("k2.single_window_pair_dropped", ("D", "C") not in e2)
    check("k2.drops_reported", sum(n for _, n, _ in m2) == 2, f"{m2}")
    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
