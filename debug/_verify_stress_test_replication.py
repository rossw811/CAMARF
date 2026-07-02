"""
Synthetic verification of stress_test_replication.py's stress_test_pair()
before trusting it on real crisis-window data.

Case 1 (no dislocation): baseline + crisis both drawn from the SAME
stationary, mean-reverting spread process (noise added directly to the
price level, matching pit_wfa's synthetic-cointegration convention) — the
crisis window should show a bounded max|z| (not exceeding ~4-5 by
construction) and cointegration should still hold on baseline+crisis
combined.

Case 2 (genuine dislocation): baseline is a normal stationary spread, but
the "crisis" window injects a large, sustained one-directional shock (a
level shift far outside the baseline's spread distribution) — this should
produce extreme_dislocation=True (max|z| far past the 3.5 threshold).

Case 3 (insufficient history): baseline window shorter than the requested
lookback should return status="INSUFFICIENT_HISTORY", not crash or silently
proceed with too little data.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

failures = []
rng = np.random.default_rng(11)


def _make_pair_frames(a_vals, b_vals, start):
    idx = pd.bdate_range(start=start, periods=len(a_vals), freq="B")
    return (
        pd.Series(a_vals, index=idx),
        pd.Series(b_vals, index=idx),
    )


# Monkeypatch DataStore.load-backed loader instead of hitting real cached
# files — inject synthetic series directly by monkeypatching the module's
# _load_log_close_1D, matching the pattern used to unit-test pure functions
# elsewhere in this project's debug/ suite.
import research.stress_test_replication as mod

_SERIES = {}


def _fake_loader(symbol):
    return _SERIES.get(symbol)


mod._load_log_close_1D = _fake_loader

# --- Case 1: no dislocation, genuine stationary cointegration throughout ---
n_baseline = 560  # ~2 trading years + margin (business-day/calendar-year rounding)
n_crisis = 15
n_total = n_baseline + n_crisis
shared = np.cumsum(rng.normal(scale=0.01, size=n_total))
a_vals = 4.0 + shared + rng.normal(scale=0.02, size=n_total)  # log-price level ~ e^4 = 54.6
b_vals = 4.0 + shared

crisis_start = pd.bdate_range("2020-01-01", periods=n_baseline + 1, freq="B")[-1]
crisis_end = pd.bdate_range(crisis_start, periods=n_crisis, freq="B")[-1]

a_series, b_series = _make_pair_frames(a_vals, b_vals, pd.bdate_range(end=crisis_end, periods=n_total, freq="B")[0])
_SERIES["A1"], _SERIES["B1"] = a_series, b_series

r1 = mod.stress_test_pair("A1", "B1", "synthetic_calm", str(crisis_start.date()), str(crisis_end.date()))
if r1["status"] != "TESTED":
    failures.append(f"Case 1: expected status=TESTED, got {r1['status']}")
elif r1["extreme_dislocation"]:
    failures.append(f"Case 1: expected no extreme dislocation, got max_abs_z={r1['max_abs_z_during_crisis']:.2f}")
elif not r1["cointegration_holds"]:
    failures.append(f"Case 1: expected cointegration to hold, got p={r1['eg_pvalue_baseline_plus_crisis']:.4f}")

# --- Case 2: genuine dislocation — crisis window has a large sustained shock ---
shared2 = np.cumsum(rng.normal(scale=0.01, size=n_total))
a_vals2 = 4.0 + shared2 + rng.normal(scale=0.02, size=n_total)
b_vals2 = 4.0 + shared2
# Inject a large, sustained one-directional shock into leg A only during the crisis window.
a_vals2[n_baseline:] += np.linspace(0, 2.0, n_crisis)  # a huge level shift relative to spread_std

a_series2, b_series2 = _make_pair_frames(a_vals2, b_vals2, pd.bdate_range(end=crisis_end, periods=n_total, freq="B")[0])
_SERIES["A2"], _SERIES["B2"] = a_series2, b_series2

r2 = mod.stress_test_pair("A2", "B2", "synthetic_shock", str(crisis_start.date()), str(crisis_end.date()))
if r2["status"] != "TESTED":
    failures.append(f"Case 2: expected status=TESTED, got {r2['status']}")
elif not r2["extreme_dislocation"]:
    failures.append(f"Case 2: expected extreme dislocation, got max_abs_z={r2['max_abs_z_during_crisis']:.2f}")

# --- Case 3: insufficient history ---
short_a, short_b = _make_pair_frames(shared[:50] + 4.0, shared[:50] + 4.0, crisis_start - pd.Timedelta(days=60))
_SERIES["A3"], _SERIES["B3"] = short_a, short_b
r3 = mod.stress_test_pair("A3", "B3", "synthetic_short", str(crisis_start.date()), str(crisis_end.date()))
if r3["status"] != "INSUFFICIENT_HISTORY":
    failures.append(f"Case 3: expected status=INSUFFICIENT_HISTORY, got {r3['status']}")

if failures:
    print("FAILURES:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All stress_test_replication.py checks passed.")
print(f"  Case 1 (calm): max|z|={r1['max_abs_z_during_crisis']:.2f}, EG p={r1['eg_pvalue_baseline_plus_crisis']:.4f}")
print(f"  Case 2 (shock): max|z|={r2['max_abs_z_during_crisis']:.2f}, extreme={r2['extreme_dislocation']}")
print(f"  Case 3 (short history): status={r3['status']}")
