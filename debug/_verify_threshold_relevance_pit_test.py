# =============================================================================
# Synthetic verification of research/threshold_relevance_pit_test.py's OWN new
# logic (summarize_by_threshold's bucketing/aggregation math). Does NOT
# re-test screen_universe_at_cutoff_ungated's internals (a lightly-modified
# copy of pit_wfa_wrds_daily.screen_universe_at_cutoff, already covered by
# debug/_verify_pit_wfa_wrds_daily.py -- the only change is which gates are
# applied, not the screening logic itself) or backtest_pair_on_test_window
# (unmodified, same coverage).
# =============================================================================
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from research.threshold_relevance_pit_test import summarize_by_threshold

checks = []


def check(name, cond, detail=""):
    checks.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


df = pd.DataFrame([
    {"pearson_corr": 0.25, "held_up": False},
    {"pearson_corr": 0.35, "held_up": True},
    {"pearson_corr": 0.45, "held_up": True},
    {"pearson_corr": 0.55, "held_up": True},
    {"pearson_corr": 0.65, "held_up": False},
])
edges = [0.20, 0.30, 0.40, 0.50, 0.60, 1.01]
summary = summarize_by_threshold(df, "pearson_corr", edges)

check("produces_rows", len(summary) > 0, f"{len(summary)} rows")
check("total_pairs_conserved", summary["n_pairs"].sum() == len(df),
      f"got {summary['n_pairs'].sum()} want {len(df)}")
check("held_up_rate_in_unit_interval", summary["held_up_rate"].between(0, 1).all())
check("n_held_up_matches_rate",
      (summary["n_held_up"] == (summary["held_up_rate"] * summary["n_pairs"]).round()).all())

# Empty input must not crash, and must return an empty (not malformed) frame.
empty_summary = summarize_by_threshold(pd.DataFrame(columns=["pearson_corr", "held_up"]), "pearson_corr", edges)
check("empty_input_no_crash", len(empty_summary) == 0, f"got {len(empty_summary)} rows")

n_pass = sum(1 for _, ok, _ in checks if ok)
print(f"\n{n_pass}/{len(checks)} checks passed")
sys.exit(0 if n_pass == len(checks) else 1)
