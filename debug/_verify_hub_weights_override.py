"""
Regression test for code-review B14 (confirmed 2026-09-26, fixed 2026-10-03, bug recheck T14.4): compute_hub_weights
counted each symbol's pairs from output/results/*/pairs.parquet even when --pairs-override supplied a different pair
set, so hub weights for an override run came from pairs that run did not trade. Fix: an override pair set, when
given, is the population the hub counts come from.
Check: override {A/B, A/C, D/E} -> A is a hub of 2 -> A/B and A/C weigh 0.5, D/E 1.0, and no pair outside the
override gets a weight; with a tf filter, rows of other timeframes are ignored.
Run: python debug/_verify_hub_weights_override.py
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import backtest

checks = {}
sig = inspect.signature(backtest.compute_hub_weights)
checks["accepts_pairs_df"] = "pairs_df" in sig.parameters
if checks["accepts_pairs_df"]:
    ov = pd.DataFrame({"symbol_a": ["A", "A", "D", "X"], "symbol_b": ["B", "C", "E", "Y"],
                       "tf_label": ["1D", "1D", "1D", "1h"]})
    w = backtest.compute_hub_weights(backtest._TF_DIRS, "1D", pairs_df=ov)
    checks["weights_from_override"] = w == {"A/B": 0.5, "A/C": 0.5, "D/E": 1.0}
    print(w)
src = open(backtest.__file__, encoding="utf-8").read()
checks["caller_passes_override"] = "compute_hub_weights(_TF_DIRS, args.tf, pairs_df=_pairs_override_df)" in src
for k, v in checks.items():
    print(f"[{'PASS' if v else 'FAIL'}] {k}")
print(); print(f"{sum(checks.values())}/{len(checks)} checks passed")
sys.exit(0 if all(checks.values()) else 1)
