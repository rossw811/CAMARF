"""
Synthetic verification for research/wrds_deep_history_episodic_scan.py's
episodic_bhfdr_confirm_asof() (2026-08-02) -- the point-in-time-safe
sibling built to close the gap docs/HANDOFF.md flagged: the original
episodic_bhfdr_confirm() answers "was this pair EVER confirmed in any
window," not "as of date T, using only windows already concluded by T."

Checks:
  1. build_rolling_eg_tasks now attaches (window_start_date, window_end_date)
     to every task_meta tuple, even when adv_by_symbol is None (previously
     only computed transiently inside the ADV-gate branch and never kept).
  2. episodic_bhfdr_confirm_asof at an EARLY as_of_date excludes windows that
     haven't concluded yet, and the pair set it confirms is a SUBSET of what
     the full-history (non-causal) episodic_bhfdr_confirm finds -- a real
     deployment at an earlier date can never see MORE evidence than one that
     waited longer.
  3. Rows with no window_end_date (simulating a pre-fix checkpoint) are
     excluded, not silently treated as eligible.
  4. As as_of_date moves later, the confirmed set is monotonically
     non-shrinking (more windows become eligible, never fewer) -- direction
     sanity check independent of the specific FDR numbers.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from wrds_deep_history_episodic_scan import (
    build_rolling_eg_tasks, episodic_bhfdr_confirm, episodic_bhfdr_confirm_asof,
)


def test_build_rolling_eg_tasks_attaches_dates_without_adv():
    dates = pd.date_range("2000-01-01", periods=500, freq="D")
    rng = np.random.default_rng(0)
    log_price_df = pd.DataFrame({
        "AAA": np.cumsum(rng.normal(0, 0.01, 500)),
        "BBB": np.cumsum(rng.normal(0, 0.01, 500)),
    }, index=dates)
    pairs = [{"symbol_a": "AAA", "symbol_b": "BBB"}]

    tasks, task_meta = build_rolling_eg_tasks(pairs, log_price_df, max_lag=5, window=100, step=100)
    print(f"n_tasks={len(tasks)}, first task_meta entry: {task_meta[0]}")
    assert len(task_meta[0]) == 6, f"expected 6-tuple (sym_a, sym_b, start, direction, start_date, end_date), got {task_meta[0]}"
    sym_a, sym_b, start, direction, window_start_date, window_end_date = task_meta[0]
    assert window_start_date == dates[0]
    assert window_end_date == dates[99]  # window=100, so end is the 100th bar (index 99)


def _make_synthetic_flat_rows():
    """3 pairs, each with 3 windows at known dates and known p-values --
    hand-constructed so the expected confirmation outcome at each as_of_date
    is known in advance, not just plausible."""
    rows = []
    windows = [
        ("2000-01-01", "2000-06-30", 0.001),  # concludes mid-2000
        ("2001-01-01", "2001-06-30", 0.002),  # concludes mid-2001
        ("2002-01-01", "2002-06-30", 0.500),  # concludes mid-2002, not significant
    ]
    for pair_id in range(3):
        for i, (start_str, end_str, pval) in enumerate(windows):
            rows.append({
                "symbol_a": f"SYM{pair_id}A", "symbol_b": f"SYM{pair_id}B",
                "window_start": i, "pvalue": pval + pair_id * 0.0001,
                "window_end_date": pd.Timestamp(end_str),
            })
    return rows


def test_asof_excludes_future_windows_and_is_subset_of_full_history():
    rows = _make_synthetic_flat_rows()
    early_date = pd.Timestamp("2000-12-31")  # only the first window (ends 2000-06-30) has concluded
    late_date = pd.Timestamp("2010-01-01")   # all windows concluded

    confirmed_early = episodic_bhfdr_confirm_asof(rows, alpha=0.05, as_of_date=early_date)
    confirmed_full_history = episodic_bhfdr_confirm(rows, alpha=0.05)

    print(f"confirmed as-of {early_date.date()}: {len(confirmed_early)} pairs")
    print(f"confirmed full-history (non-causal): {len(confirmed_full_history)} pairs")

    early_pairs = {(c["symbol_a"], c["symbol_b"]) for c in confirmed_early}
    full_pairs = {(c["symbol_a"], c["symbol_b"]) for c in confirmed_full_history}
    assert early_pairs.issubset(full_pairs), (
        "an earlier as_of_date confirmed a pair the full-history scan did not -- "
        "this means the asof filter let future information through"
    )

    for c in confirmed_early:
        assert c["n_windows_tested"] == 1, (
            f"at as_of_date={early_date.date()}, only 1 window (ending 2000-06-30) should be "
            f"eligible per pair, got {c['n_windows_tested']}"
        )


def test_rows_without_window_end_date_are_excluded():
    rows = _make_synthetic_flat_rows()
    rows[0]["window_end_date"] = None  # simulate a pre-fix checkpoint row
    confirmed = episodic_bhfdr_confirm_asof(rows, alpha=0.05, as_of_date=pd.Timestamp("2010-01-01"))
    # SYM0's first window is now ineligible (no date) -- it should have one
    # fewer window counted than SYM1/SYM2 for the same as_of_date.
    by_pair = {(c["symbol_a"], c["symbol_b"]): c["n_windows_tested"] for c in confirmed}
    print(f"windows tested per pair: {by_pair}")
    assert by_pair.get(("SYM0A", "SYM0B"), 0) == 2, "row with missing window_end_date should be excluded, not counted"
    assert by_pair.get(("SYM1A", "SYM1B"), 0) == 3


def test_confirmed_set_nondecreasing_as_asof_date_advances():
    rows = _make_synthetic_flat_rows()
    dates = [pd.Timestamp("2000-12-31"), pd.Timestamp("2001-12-31"), pd.Timestamp("2010-01-01")]
    n_windows_over_time = []
    for d in dates:
        confirmed = episodic_bhfdr_confirm_asof(rows, alpha=0.05, as_of_date=d, min_windows_confirmed=1)
        total_windows = sum(c["n_windows_tested"] for c in confirmed)
        n_windows_over_time.append(total_windows)
    print(f"total eligible windows across dates {[d.date() for d in dates]}: {n_windows_over_time}")
    assert n_windows_over_time == sorted(n_windows_over_time), (
        "eligible window count should never decrease as as_of_date advances"
    )


if __name__ == "__main__":
    test_build_rolling_eg_tasks_attaches_dates_without_adv()
    test_asof_excludes_future_windows_and_is_subset_of_full_history()
    test_rows_without_window_end_date_are_excluded()
    test_confirmed_set_nondecreasing_as_asof_date_advances()
    print("\nAll episodic PIT asof() synthetic checks passed.")
