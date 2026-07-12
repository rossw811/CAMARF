"""
Permanent verification for ml.py's `feature_lag` parameter on
`_build_examples_for_pair` (added 2026-07-11 for
research/ml_lookahead_selftest.py's mechanical lookahead self-test).

Confirms:
  1. Entry timing (entry_time) is IDENTICAL regardless of feature_lag --
     the entry detection must stay anchored to the true z_rolling crossing,
     never shift with the lag.
  2. z_entry (the label-driving value, via _classify_outcome) is IDENTICAL
     regardless of feature_lag -- the label must always reflect what
     actually happened at the real entry, never a staled value.
  3. label is therefore also IDENTICAL regardless of feature_lag.
  4. zscore (the actual _FEATURE_COLS value fed to the model) DOES differ:
     feature_lag=0 reads the true spike value; feature_lag=1 reads the
     stale pre-spike value.

An earlier version of the self-test lagged the WHOLE spread_series before
passing it in, which silently shifted entry detection along with the
feature values, defeating the test (entry moved forward by the same amount
as the feature, so the "feature at entry" looked identical either way).
This caught that bug via a failing assertion before the self-test was ever
trusted -- see Development.md's mechanical-lookahead-self-test entry,
Session 28 (2026-07-11).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from ml import _build_examples_for_pair, MLRunSummary


def main():
    failures = []
    n = 200
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    z = np.full(n, 0.3)
    z[100] = 2.0  # single clean crossing above TRAINING_ENTRY_THRESHOLD=1.5
    series = pd.DataFrame(
        {"z_rolling": z, "spread": np.zeros(n), "half_life_rolling": np.full(n, 20.0)},
        index=idx,
    )
    row = pd.Series({
        "hurst_rs": 0.4, "coint_fraction_rolling": 0.8, "half_life_trend_slope": 0.0,
        "mean_reversion_speed": 0.1, "hedge_ratio_ols": 1.0, "hedge_ratio_kalman_mean": 1.0,
    })

    ev0 = _build_examples_for_pair("A", "B", "1h", row, MLRunSummary(), series=series, feature_lag=0)
    ev1 = _build_examples_for_pair("A", "B", "1h", row, MLRunSummary(), series=series, feature_lag=1)

    if len(ev0) != 1 or len(ev1) != 1:
        failures.append(f"expected exactly 1 entry event each, got {len(ev0)} (lag=0), {len(ev1)} (lag=1)")
    else:
        e0, e1 = ev0[0], ev1[0]
        if e0.entry_time != e1.entry_time:
            failures.append(f"entry_time shifted with feature_lag: {e0.entry_time} vs {e1.entry_time}")
        if e0.z_entry != 2.0 or e1.z_entry != 2.0:
            failures.append(f"z_entry (label-driving) must stay true value 2.0 in both cases, got {e0.z_entry}, {e1.z_entry}")
        if e0.label != e1.label:
            failures.append(f"label changed with feature_lag: {e0.label} vs {e1.label}")
        if e0.zscore != 2.0:
            failures.append(f"unlagged feature should read the true spike value 2.0, got {e0.zscore}")
        if e1.zscore != 0.3:
            failures.append(f"lagged feature should read the stale pre-spike value 0.3, got {e1.zscore}")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("PASSED: feature_lag correctly stales only the model-facing feature snapshot; "
          "entry timing and label stay anchored to the true entry bar.")


if __name__ == "__main__":
    main()
