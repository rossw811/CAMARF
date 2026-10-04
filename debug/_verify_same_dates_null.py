"""
Synthetic check for the M-1 comparison arm (design approved; 2026-10-03): research/trend_dominance_diagnostic.
spurious_regression_risk_score(..., null="same_dates") pairs the leg with random partners ALIGNED ON COMMON DATES
(contemporaneous: the real pair's setting), next to the existing null="count_aligned" (right-aligned by count after
dropping NaNs: non-contemporaneous by design).
Mechanical check (what reaches the EG test), not a rejection-rate check: a first attempt compared rejection rates on
"market random walk + stationary noise" stocks and BOTH nulls rejected 100% -- a random walk and its lagged copy are
still cointegrated (a fixed-lag difference is stationary), so count-misalignment does not break the relationship in
that design. Which null rejects more on real data is the empirical question the arm answers, not a property to assert.
Checks: (1) default unchanged = count_aligned; (2) both nulls evaluate the SAME partners; (3) same_dates feeds EG the
leg and partner on their COMMON DATES; count_aligned feeds the last-n values of each (non-contemporaneous).
Run: python debug/_verify_same_dates_null.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import research.trend_dominance_diagnostic as td

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    if not hasattr(td, "load_log_close_series"):
        check("same_dates_arm_exists", False); return finish()
    idx = pd.bdate_range("2020-01-02", periods=200)
    A = pd.Series(np.arange(200, dtype=float), index=idx)                    # values = position in the calendar
    B = pd.Series(1000 + np.arange(150, dtype=float), index=idx[20:170])     # covers days 20..169
    series = {"A": A, "B": B}
    seen = []
    orig = (td.load_log_close, td.load_log_close_series, td.eg_pvalue)
    td.load_log_close = lambda s, suf: series[s].to_numpy()
    td.load_log_close_series = lambda s, suf: series[s]
    td.eg_pvalue = lambda a, b: (seen.append((np.asarray(a).copy(), np.asarray(b).copy())), 0.5)[1]
    try:
        base = td.spurious_regression_risk_score("A", "x", ["A", "B"], 1, np.random.default_rng(0), {})
        cnt = td.spurious_regression_risk_score("A", "x", ["A", "B"], 1, np.random.default_rng(0), {}, null="count_aligned")
        same = td.spurious_regression_risk_score("A", "x", ["A", "B"], 1, np.random.default_rng(0), {}, null="same_dates")
    finally:
        td.load_log_close, td.load_log_close_series, td.eg_pvalue = orig
    check("1.default_is_count_aligned", base["pvalues"] == cnt["pvalues"] and len(seen) == 3)
    check("2.same_partners", list(cnt["partners"]) == list(same["partners"]) == ["B"])
    a_cnt, b_cnt = seen[1]
    a_same, b_same = seen[2]
    check("3a.count_aligned_is_last_n", np.array_equal(a_cnt, np.arange(50, 200)) and np.array_equal(b_cnt, 1000 + np.arange(150)),
          f"A days {a_cnt[0]:.0f}..{a_cnt[-1]:.0f}")
    check("3b.same_dates_is_contemporaneous", np.array_equal(a_same, np.arange(20, 170)) and
          np.array_equal(b_same - 1000 + 20, a_same), f"A days {a_same[0]:.0f}..{a_same[-1]:.0f}")
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
