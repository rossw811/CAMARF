"""Synthetic verification for research/decay_rate_at_entry_diagnostic.py's
bucketing/correlation logic -- _bucket() and _asof_lookup(), the two pure
functions this diagnostic's real-data correctness depends on most directly
(decay_rate_signals.py itself is separately verified in
debug/_verify_decay_rate_signals.py)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from research.decay_rate_at_entry_diagnostic import _bucket, _asof_lookup

checks = []


def check(name, cond):
    checks.append((name, cond))
    print(f"{'PASS' if cond else 'FAIL'}: {name}")


# --- _bucket ---
check("_bucket: positive -> strengthening", _bucket(0.5) == "strengthening")
check("_bucket: negative -> weakening", _bucket(-0.5) == "weakening")
check("_bucket: NaN -> unknown", _bucket(float("nan")) == "unknown")
check("_bucket: None -> unknown", _bucket(None) == "unknown")
check("_bucket: exactly zero -> weakening (not >0, matches decay_rate_series' own convention)",
      _bucket(0.0) == "weakening")

# --- _asof_lookup: causal, last value at or before ts ---
idx = pd.date_range("2020-01-01", periods=10, freq="D")
vals = np.array([1.0, 2.0, np.nan, 4.0, 5.0, np.nan, np.nan, 8.0, 9.0, 10.0])

check("_asof_lookup: exact match on a valid bar returns that value",
      _asof_lookup(vals, idx, idx[4]) == 5.0)
check("_asof_lookup: ts falls on a NaN bar -> returns the last REAL value before it",
      _asof_lookup(vals, idx, idx[6]) == 5.0)
check("_asof_lookup: ts before any data -> NaN",
      np.isnan(_asof_lookup(vals, idx, pd.Timestamp("2019-01-01"))))
check("_asof_lookup: ts after all data -> last real value",
      _asof_lookup(vals, idx, pd.Timestamp("2021-01-01")) == 10.0)
check("_asof_lookup: all-NaN series -> NaN",
      np.isnan(_asof_lookup(np.full(10, np.nan), idx, idx[5])))

n_fail = sum(1 for _, c in checks if not c)
print(f"\n{len(checks) - n_fail}/{len(checks)} checks passed")
sys.exit(1 if n_fail else 0)
