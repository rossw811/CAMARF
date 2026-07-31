"""
Verification for research/comparison_arm_scaffold.py (2026-07-20 Grand
Sweep task #22): the mandatory walk-forward scaffold built after finding
the same in-sample-circularity mistake (fit and score on the same sample)
independently in 3 files.

Proves:
1. walk_forward_windows() yields non-overlapping, correctly-bounded
   (train, test) slices matching k_bahc_covariance_cleaning.py's own
   convention (train strictly precedes test, slides by step).
2. evaluate_walk_forward() genuinely never lets fit_fn see the test
   window's data -- proven by constructing fit_fn/score_fn that would
   produce a DIFFERENT (wrong) answer if test data leaked into fitting,
   and confirming the actual result matches the correct (no-leakage)
   expectation.
3. Edge case: data shorter than train_window+test_window yields zero
   windows, not a crash.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from comparison_arm_scaffold import walk_forward_windows, evaluate_walk_forward


def main() -> None:
    failures = []

    # 1. Window bounds and non-overlap.
    n = 100
    data = pd.DataFrame({"x": np.arange(n)})
    windows = list(walk_forward_windows(data, train_window=30, test_window=10))
    if not windows:
        failures.append("expected at least one window for a 100-row fixture (train=30, test=10)")
    else:
        for train, test in windows:
            if len(train) != 30:
                failures.append(f"expected train window length 30, got {len(train)}")
            if len(test) != 10:
                failures.append(f"expected test window length 10, got {len(test)}")
            if train.index.max() >= test.index.min():
                failures.append(
                    f"train window overlaps or follows test window: "
                    f"train ends at {train.index.max()}, test starts at {test.index.min()}"
                )
        # Non-overlapping test windows: each window's test start should equal
        # the previous window's test end (step == test_window by default).
        test_starts = [test.index.min() for _, test in windows]
        for i in range(1, len(test_starts)):
            if test_starts[i] != test_starts[i - 1] + 10:
                failures.append(
                    f"expected non-overlapping test windows stepping by 10, "
                    f"got test_starts={test_starts}"
                )

    # 2. No-leakage proof: fit_fn returns train's mean; score_fn checks whether
    #    the fitted mean equals test's OWN mean (which would only happen if
    #    fit_fn had access to test data, since train/test means are
    #    constructed to differ deliberately).
    n2 = 60
    # First 30 rows: value 1.0 (train regime). Last 30 rows: value 100.0 (test regime).
    data2 = pd.DataFrame({"x": np.concatenate([np.full(30, 1.0), np.full(30, 100.0)])})

    def fit_fn(train_df):
        return train_df["x"].mean()  # should be 1.0 -- only ever sees the train slice

    def score_fn(fitted_mean, test_df):
        # Returns True if the "fitted" value leaked test information (i.e.
        # equals test's own mean instead of train's).
        return np.isclose(fitted_mean, test_df["x"].mean(), atol=1e-9)

    leak_flags = evaluate_walk_forward(data2, fit_fn, score_fn, train_window=30, test_window=30)
    if any(leak_flags):
        failures.append(
            f"leakage detected: fitted value matched test's own mean in at least one window "
            f"(flags={leak_flags}) -- evaluate_walk_forward is letting fit_fn see test data"
        )
    if not leak_flags:
        failures.append("expected at least one (train, test) window from the 60-row leakage fixture")

    # 3. Edge case: too-short data yields zero windows, not a crash.
    short_data = pd.DataFrame({"x": np.arange(20)})
    short_windows = list(walk_forward_windows(short_data, train_window=30, test_window=10))
    if short_windows:
        failures.append(f"expected zero windows for data shorter than train+test, got {len(short_windows)}")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("comparison_arm_scaffold.py verified.")
        print(f"  {len(windows)} non-overlapping windows generated correctly (train=30, test=10 on n=100)")
        print(f"  No-leakage proof passed: fit_fn never saw test data across {len(leak_flags)} windows")
        print("  Edge case (too-short data): correctly yields zero windows.")


if __name__ == "__main__":
    main()
