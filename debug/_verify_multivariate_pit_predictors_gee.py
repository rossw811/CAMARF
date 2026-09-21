"""
Synthetic verification for research/multivariate_pit_predictors.py's fit_gee()
(2026-09-15, added per literature sweep pass 3, topic 1's recommendation --
GEE clustered by pair directly addresses fit_logit's own disclosed
pseudo-replication limitation instead of just flagging it).

No live data. Fabricated pooled fold x L observations with a KNOWN pair
clustering structure (each pair repeated across several L values, same shape
as the real run_pilot() output).

Run: python debug/_verify_multivariate_pit_predictors_gee.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.multivariate_pit_predictors import fit_gee, fit_logit

FAILURES = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")
    if not cond:
        FAILURES.append(name)


def _make_pooled_df(n_pairs=15, cells_per_pair=4, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for p in range(n_pairs):
        sym_a, sym_b = f"SYM{p}A", f"SYM{p}B"
        # Real per-pair effect -- some pairs genuinely more likely to hold up.
        pair_effect = rng.normal(0, 1)
        for c in range(cells_per_pair):
            overlap = rng.normal(500, 100)
            corr = rng.uniform(0.3, 0.9)
            cfrac = rng.uniform(0.3, 0.9)
            hr_cv = rng.uniform(0.05, 0.5)
            logit_p = -1.0 + 0.3 * pair_effect + 0.001 * overlap
            p_hold = 1 / (1 + np.exp(-logit_p))
            held_up = rng.uniform() < p_hold
            rows.append({
                "symbol_a": sym_a, "symbol_b": sym_b,
                "actual_n_overlap": overlap, "pearson_corr": corr,
                "coint_fraction_rolling": cfrac, "hedge_ratio_cv": hr_cv,
                "held_up": held_up,
            })
    return pd.DataFrame(rows)


def test_fit_gee_runs_and_reports_pair_count():
    df = _make_pooled_df()
    result = fit_gee(df)
    check("fit_gee.mentions_distinct_pairs", "distinct pairs" in result, result[:80])
    check("fit_gee.mentions_n_equals", "n=" in result[:20])
    check("fit_gee.not_an_error_message", "Not enough" not in result and "Cannot cluster" not in result)


def test_fit_gee_handles_missing_symbol_columns():
    df = _make_pooled_df().drop(columns=["symbol_a", "symbol_b"])
    result = fit_gee(df)
    check("fit_gee.missing_columns_returns_clear_message",
          "symbol_a/symbol_b" in result)


def test_fit_gee_handles_insufficient_data():
    df = pd.DataFrame([{
        "symbol_a": "A", "symbol_b": "B", "actual_n_overlap": 100,
        "pearson_corr": 0.5, "coint_fraction_rolling": 0.5,
        "hedge_ratio_cv": 0.1, "held_up": True,
    }])
    result = fit_gee(df)
    check("fit_gee.insufficient_data_returns_clear_message", "Not enough" in result)


def test_fit_gee_and_fit_logit_both_run_on_same_data_without_crash():
    df = _make_pooled_df()
    logit_result = fit_logit(df)
    gee_result = fit_gee(df)
    check("both.logit_ran", "n=" in logit_result[:10])
    check("both.gee_ran", "n=" in gee_result[:10])
    check("both.reports_differ", logit_result != gee_result)


if __name__ == "__main__":
    test_fit_gee_runs_and_reports_pair_count()
    test_fit_gee_handles_missing_symbol_columns()
    test_fit_gee_handles_insufficient_data()
    test_fit_gee_and_fit_logit_both_run_on_same_data_without_crash()

    print()
    print("FAILED:", FAILURES) if FAILURES else print("All checks passed.")
    sys.exit(1 if FAILURES else 0)
