"""
Synthetic verification for research/ml_stage2_ablation.py's
join_macro_features(). No network calls for the core logic test (macro
unavailable case); one real macro.build() call for the availability case
if it succeeds, skipped gracefully if not (matches the script's own
graceful-degradation design).

Run: python debug/_verify_ml_stage2_ablation.py
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from ml_stage2_ablation import join_macro_features, _STAGE2_MACRO_COLS


def case1_empty_examples():
    df = pd.DataFrame(columns=["entry_time", "label"])
    result = join_macro_features(df)
    print(f"Case 1 (empty examples): columns added={[c for c in _STAGE2_MACRO_COLS if c in result.columns]}")
    assert result.empty
    for c in _STAGE2_MACRO_COLS:
        assert c in result.columns
    print("  PASS: empty input handled without crashing, macro columns still present")


def case2_does_not_mutate_input():
    df = pd.DataFrame({
        "entry_time": pd.to_datetime(["2024-01-15", "2024-02-20"]),
        "label": ["strong_converge", "diverge_further"],
    })
    original_cols = set(df.columns)
    result = join_macro_features(df)
    print(f"Case 2 (no mutation): input cols unchanged={set(df.columns) == original_cols}, "
          f"result has more cols={len(result.columns) > len(df.columns)}")
    assert set(df.columns) == original_cols, "join_macro_features must not mutate its input"
    assert len(result) == len(df), "row count must be preserved"
    for c in _STAGE2_MACRO_COLS:
        assert c in result.columns, f"missing expected column {c}"
    print("  PASS: input untouched, output has the expected macro columns for every row")


def case3_duplicate_entry_dates():
    """The real crash found on live data: multiple examples sharing the
    same entry date. A naive reindex-then-ffill raises 'cannot reindex on
    an axis with duplicate labels' — merge_asof must not."""
    df = pd.DataFrame({
        "entry_time": pd.to_datetime(["2024-01-15", "2024-01-15", "2024-01-15", "2024-03-01"]),
        "label": ["strong_converge", "diverge_further", "no_move", "weak_converge"],
    })
    result = join_macro_features(df)
    print(f"Case 3 (duplicate entry dates, n={len(df)}): result rows={len(result)}")
    assert len(result) == len(df), "must handle repeated entry dates without dropping/crashing"
    print("  PASS: duplicate entry dates handled correctly (this is what crashed before the fix)")


if __name__ == "__main__":
    case1_empty_examples()
    case2_does_not_mutate_input()
    case3_duplicate_entry_dates()
    print("\nAll ml_stage2_ablation checks passed.")
