"""
Synthetic verification for pit_wfa.py's build_window_sweep_specs() (task
#67's absolute-window-length dimension, 2026-07-14). Confirms the fraction
math is right before spending real compute on it: fixed test_start/test_end
anchor (0.80/1.00), train_start_pct shrinks correctly as window_days grows,
and an over-long window clips to 0.0 instead of going negative.
"""
import sys
import os
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pit_wfa import build_window_sweep_specs, compute_fold_dates

start = pd.Timestamp("2023-07-24")
end = pd.Timestamp("2026-07-14")  # 1086 days total
total_days = (end - start).days
assert total_days == 1086, f"sanity check on the fixture itself failed: {total_days}"

specs = build_window_sweep_specs(start, end, window_days_list=[180, 365, 730, 2000], anchor_pct=0.80)

for (ts_pct, te_pct, test_s_pct, test_e_pct, label), wd in zip(specs, [180, 365, 730, 2000]):
    assert te_pct == 0.80, f"{label}: train_end_pct should be fixed at 0.80, got {te_pct}"
    assert test_s_pct == 0.80 and test_e_pct == 1.0, f"{label}: test anchor drifted"
    expected_ts_pct = max(0.0, 0.80 - wd / total_days)
    assert abs(ts_pct - expected_ts_pct) < 1e-9, f"{label}: train_start_pct {ts_pct} != {expected_ts_pct}"
    fold_dates = compute_fold_dates(start, end, (ts_pct, te_pct, test_s_pct, test_e_pct, label))
    actual_train_days = (fold_dates["train_end"] - fold_dates["train_start"]).days
    print(f"{label}: train_start_pct={ts_pct:.4f}  actual_train_days={actual_train_days}  "
          f"train=[{fold_dates['train_start'].date()}, {fold_dates['train_end'].date()}]  "
          f"test=[{fold_dates['test_start'].date()}, {fold_dates['test_end'].date()}]")

# The 2000-day request exceeds the 0.80*1086=868.8-day pre-anchor budget -> must clip to 0.0.
clipped = specs[3]
assert clipped[0] == 0.0, f"over-long window should clip to train_start_pct=0.0, got {clipped[0]}"

print("\nPASS: all window-sweep fold specs correct, over-long window clips as expected.")
