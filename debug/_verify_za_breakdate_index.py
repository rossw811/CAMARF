"""
Regression test for code-review finding S7 (2026-09-26): stats.py read zivot_andrews()'s tuple as
if index 3 were the break index. statsmodels returns (zastat, pvalue, cvdict, baselag, bpidx), so the
recorded "break date" was the position of the lag count. Checks statsmodels' ordering directly on a
series with a planted level break, and that stats.py now reads index 4.

Run: python debug/_verify_za_breakdate_index.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from statsmodels.tsa.stattools import zivot_andrews

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    rng = np.random.default_rng(1)
    n, brk = 300, 150
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = 0.5 * x[t - 1] + rng.normal(0, 0.3)
    x[brk:] += 5.0
    r = zivot_andrews(x, trim=0.15, regression="c", autolag="AIC")
    check("statsmodels.index4_is_break", abs(int(r[4]) - brk) <= 3, f"r[3]={r[3]} r[4]={r[4]}")
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "stats.py"),
               encoding="utf-8").read()
    check("stats_py_reads_index_4", re.search(r"break_idx = int\(za_result\[4\]\)", src) is not None)
    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
