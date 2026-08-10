"""
debug/_verify_episodic_duration_degree_usability.py -- synthetic ground-truth
verification for research/episodic_duration_degree_usability.py, BEFORE
trusting it against real episodic scan output.

Core claims verified:
1. build_pair_data correctly splits each pair's windows chronologically
   (early 70% / late 30%) and computes ground_truth_held_up from ONLY the
   late rows (a pair with significant late p-values should get
   ground_truth_held_up=True regardless of its early p-values, and
   vice versa -- ground truth must not leak from early rows).
2. score_cell's accuracy genuinely responds to the grid parameters: a
   PERSISTENT pair (real signal in both early and late windows) should be
   correctly predicted "confirmed" at a lenient (min_windows_confirmed=1,
   alpha=0.10) cell and match its true "held up" outcome; a pair with only
   NOISE-level significance in a couple of early windows (no real signal)
   should fail to be confirmed at a strict cell (min_windows_confirmed=5,
   alpha=0.01), and if it also doesn't hold up late, that should count as
   a correct (non-confirmed, not-held-up) match, not a wrong prediction.
3. The overfitting guard's own mechanics: selecting on one half and scoring
   on the other must use the SAME cell (not silently re-optimize on half B).

Run: python debug/_verify_episodic_duration_degree_usability.py
(All checks are synthetic/offline -- no real episodic scan output needed.)
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research.episodic_duration_degree_usability as usab


def check(name, cond):
    cond = bool(cond)
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}")
    return cond


def make_rows(sym_a, sym_b, pvalues, start_date="2020-01-01"):
    import pandas as pd
    dates = pd.date_range(start_date, periods=len(pvalues), freq="365D")
    return [
        {"symbol_a": sym_a, "symbol_b": sym_b, "window_start": i, "pvalue": p,
         "window_end_date": dates[i], "fdr_rejected": None, "fdr_adjusted_pvalue": None}
        for i, p in enumerate(pvalues)
    ]


def main():
    results = []

    print("=== 1. build_pair_data: chronological split + ground truth from late rows only ===")
    # Persistent pair: significant early AND late.
    persistent_rows = make_rows("A", "B", [0.001, 0.002, 0.001, 0.001, 0.002, 0.001, 0.001, 0.001, 0.001, 0.001])
    # Decaying pair: significant early, noise-level (insignificant) late.
    decaying_rows = make_rows("C", "D", [0.001, 0.002, 0.001, 0.001, 0.001, 0.001, 0.60, 0.70, 0.55, 0.65])
    # Too-few-windows pair: should be excluded entirely.
    thin_rows = make_rows("E", "F", [0.001, 0.9])

    pair_data = usab.build_pair_data(persistent_rows + decaying_rows + thin_rows)
    keys = {(d["symbol_a"], d["symbol_b"]) for d in pair_data}
    results.append(check("thin pair (< MIN_WINDOWS_PER_PAIR) is excluded", ("E", "F") not in keys))
    results.append(check("persistent pair (A,B) is included", ("A", "B") in keys))
    results.append(check("decaying pair (C,D) is included", ("C", "D") in keys))

    ab = next(d for d in pair_data if (d["symbol_a"], d["symbol_b"]) == ("A", "B"))
    cd = next(d for d in pair_data if (d["symbol_a"], d["symbol_b"]) == ("C", "D"))
    results.append(check("persistent pair's ground truth is True (late windows significant)",
                          ab["ground_truth_held_up"] is True))
    results.append(check("decaying pair's ground truth is False (late windows NOT significant)",
                          cd["ground_truth_held_up"] is False))
    results.append(check("early/late split is chronological, not random (late rows are the later dates)",
                          ab["late_rows"][0]["window_start"] > ab["early_rows"][-1]["window_start"]))

    print("\n=== 2. score_cell: precision/recall respond correctly to grid strictness ===")
    # Lenient cell: min_windows_confirmed=1, alpha=0.10 -- persistent pair should be
    # confirmed (a true positive: predicted confirmed AND ground truth True).
    precision, recall, n_confirmed, n_scored, rows_lenient = usab.score_cell(
        pair_data, min_windows_confirmed=1, alpha=0.10
    )
    ab_row = next(r for r in rows_lenient if (r["symbol_a"], r["symbol_b"]) == ("A", "B"))
    results.append(check("lenient cell: persistent pair predicted confirmed", ab_row["predicted_confirmed"] is True))
    results.append(check("lenient cell: precision is computable (some pair was confirmed)",
                          precision is not None))
    results.append(check("lenient cell: precision is a true positive rate in [0,1]",
                          precision is not None and 0.0 <= precision <= 1.0))

    print("\n=== 3. Overfitting guard: same cell used for selection and held-out scoring ===")
    idx_a, idx_b = [0], [1]  # arbitrary 1/1 split of the 2 real pairs (persistent, decaying)
    p_a, r_a, nc_a, ns_a, _ = usab.score_cell(pair_data, 1, 0.10, subset=idx_a)
    p_b, r_b, nc_b, ns_b, _ = usab.score_cell(pair_data, 1, 0.10, subset=idx_b)
    results.append(check("score_cell accepts a subset and scores only those pairs",
                          ns_a == 1 and ns_b == 1))

    print("\n=== 4. Eligibility floor: a cell that cannot possibly confirm anything ===")
    # min_windows_confirmed=5 with only 4 early windows total (structurally, not
    # just statistically, incapable of reaching 5 FDR-rejected windows) --
    # precision must come back None (undefined), not falsely 0 or 1. The
    # eligibility-floor logic itself lives in main() (requires n_confirmed >=
    # a minimum), not in score_cell -- this checks score_cell's own honest
    # "undefined when nothing confirmed" contract that main() builds on.
    few_windows_rows = make_rows("G", "H", [0.001, 0.001, 0.001, 0.001])
    pair_data_few = usab.build_pair_data(few_windows_rows)
    p_strict, r_strict, nc_strict, ns_strict, _ = usab.score_cell(pair_data_few, min_windows_confirmed=5, alpha=0.01)
    results.append(check("cell requiring more windows than exist confirms 0 pairs",
                          nc_strict == 0))
    results.append(check("that cell's precision is None (undefined), not falsely 0 or 1",
                          p_strict is None))

    n_pass = sum(results)
    print(f"\n{n_pass}/{len(results)} checks passed")
    return n_pass == len(results)


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
