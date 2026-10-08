"""
Regression test for code review S14 (verified 2026-10-07, fixed the same day): pit_wfa folds set train_end ==
test_start, and screen_universe_at_cutoff kept bars with index <= train_end while the test slice keeps >= test_start,
so the boundary bar was used both to SELECT a pair and to TRADE it. Fix: the training slice is [train_start,
train_end) (pit_wfa._train_slice); the boundary bar belongs to the test window only. (An embargo beyond one bar is a
methodology choice, not part of this fix -- noted for Ross in the recheck verdict.)
Checks: with train_end == test_start, the training slice excludes that timestamp, the test slice includes it, and no
timestamp is in both.
Run: python debug/_verify_pit_wfa_train_test_boundary.py
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    import pit_wfa
    if not hasattr(pit_wfa, "_train_slice"):
        check("helper_exists", False)
    else:
        idx = pd.bdate_range("2020-01-01", periods=100)
        df = pd.DataFrame({"close": range(100)}, index=idx)
        cut = idx[60]
        tr = pit_wfa._train_slice(df, idx[0], cut)
        te = df.loc[(df.index >= cut)]
        check("boundary_not_in_train", cut not in tr.index, tr.index.max())
        check("boundary_in_test", cut in te.index)
        check("no_overlap", len(tr.index.intersection(te.index)) == 0)
        check("train_keeps_start", idx[0] in tr.index and len(tr) == 60, len(tr))
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
