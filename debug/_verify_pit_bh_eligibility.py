"""
Test for plan S32 (Ross 2026-10-10; written before the code): research/purity_pit_eligibility.py set eligible_from =
the end date of a pair's k-th window flagged fdr_rejected by the scan, whose BH family is the WHOLE history -- so
whether an early window counted as rejected could depend on p-values of windows that ended later (lookahead).
Rule now: at each month-end T, BH over the windows concluded by T (window_end_date <= T); a pair's eligible_from is the
first month-end at which it has >= k windows rejected under that as-of family (pit_kth_rejection_dates). Month-end
evaluation is conservative (up to a month late) and never uses a window that had not ended.
Synthetic family (alpha 0.05): pair EARLY has one window ending 2001-01-10 with p = 0.004; in Jan-2001 the family is
that window + 99 windows with p = 0.9 (BH cutoff for rank 1 = 0.05/100 = 0.0005 -> NOT rejected). From 2010 on,
1,000 windows with p = 1e-6 arrive (other pairs), which raises the whole-history BH cutoff enough to reject 0.004.
Checks: whole-history rule -> EARLY eligible from 2001-01-10 (the lookahead); PIT rule -> EARLY not eligible in 2001
(first eligible only once the family at T rejects it, here 2010-01-31); a pair with p = 1e-8 in 2001 is eligible at the
2001-01-31 month-end under both; k = 2 needs two as-of rejections.
Run: python debug/_verify_pit_bh_eligibility.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def family():
    rows = [("EARLY", "X", "2001-01-10", 0.004), ("STRONG", "Y", "2001-01-12", 1e-8),
            ("STRONG", "Y", "2003-01-12", 1e-8)]
    rows += [(f"N{i}", "Z", "2001-01-05", 0.9) for i in range(99)]
    rows += [(f"L{i}", "W", "2010-01-15", 1e-6) for i in range(1000)]
    w = pd.DataFrame(rows, columns=["symbol_a", "symbol_b", "window_end_date", "pvalue"])
    w["window_end_date"] = pd.to_datetime(w["window_end_date"])
    from analysis import AnalysisPipeline  # noqa: F401  (import check only)
    return w


def main():
    import research.purity_pit_eligibility as m
    if not hasattr(m, "pit_kth_rejection_dates"):
        check("function_exists", False); return finish()
    from research.wrds_deep_history_episodic_scan import _benjamini_hochberg
    w = family()
    rej, _ = _benjamini_hochberg(w["pvalue"].to_numpy(), 0.05)
    whole = w.assign(fdr_rejected=rej)
    old = m.kth_rejection_dates(whole, 1).set_index(["key_a", "key_b"])
    check("fixture_whole_history_lookahead", ("EARLY", "X") in old.index
          and old.loc[("EARLY", "X"), "eligible_from"] == pd.Timestamp("2001-01-10"),
          old.loc[("EARLY", "X"), "eligible_from"] if ("EARLY", "X") in old.index else None)
    pit = m.pit_kth_rejection_dates(w, 1, alpha=0.05).set_index(["key_a", "key_b"])
    e = pit.loc[("EARLY", "X"), "eligible_from"] if ("EARLY", "X") in pit.index else None
    check("pit_not_eligible_in_2001", e is None or pd.Timestamp(e) >= pd.Timestamp("2010-01-31"), e)
    s = pit.loc[("STRONG", "Y"), "eligible_from"] if ("STRONG", "Y") in pit.index else None
    check("strong_pair_eligible_at_month_end", s is not None and pd.Timestamp(s) == pd.Timestamp("2001-01-31"), s)
    pit2 = m.pit_kth_rejection_dates(w, 2, alpha=0.05).set_index(["key_a", "key_b"])
    s2 = pit2.loc[("STRONG", "Y"), "eligible_from"] if ("STRONG", "Y") in pit2.index else None
    check("k2_second_rejection", s2 is not None and pd.Timestamp(s2) == pd.Timestamp("2003-01-31"), s2)
    check("k2_needs_two", ("EARLY", "X") not in pit2.index)
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
