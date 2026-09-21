"""
Verification for the 2026-09-15 addition of squeeze_min/rsi_diff_velocity to
ml.py's _FEATURE_COLS (Ross's direct instruction, same change as
backtest.py's squeeze_gate/momentum_gate/squeeze_momentum_gate STORM
variants and research/squeeze_momentum_features.py, which adds the
squeeze_indicator_a_t/b_t and rsi_diff_velocity_t columns these read).

Same "point-in-time, not full-sample scalar" verification pattern as
debug/_verify_ml_hedge_ratio_drift_pit.py: (1) with the _t columns present,
squeeze_min/rsi_diff_velocity vary across entry events at different points in
the series (per-event, staled to each event's own feat_pos), not a single
constant; (2) squeeze_min correctly takes the MIN of the two legs (the
tighter/more-compressed leg governs); (3) NaN when either leg's squeeze
value is NaN, not a silent 0 or the other leg's value alone; (4) both
features are NaN throughout (not crash) when the _t columns are absent, same
fail-safe convention as every other optional PIT feature.

Run: python debug/_verify_ml_squeeze_momentum_features.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ml import _build_examples_for_pair, MLRunSummary, _FEATURE_COLS

FAILURES = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")
    if not cond:
        FAILURES.append(name)


def _make_series(n=300):
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.RandomState(7)
    z = 3.0 * np.sin(np.linspace(0, 8 * np.pi, n)) + rng.normal(0, 0.1, n)
    half_life = np.full(n, 20.0)
    # squeeze_indicator drifts from tight (0.4) to loose (1.6) over the series
    # -- lets us confirm each event reflects its OWN point in time.
    sq_a = np.linspace(0.4, 1.6, n)
    sq_b = np.linspace(0.6, 1.2, n)
    rsi_diff = 10.0 * np.sin(np.linspace(0, 4 * np.pi, n))
    rsi_diff_velocity = np.gradient(rsi_diff) * 5  # non-constant, varies with position
    return pd.DataFrame({
        "z_rolling": z, "half_life_rolling": half_life,
        "squeeze_indicator_a_t": sq_a, "squeeze_indicator_b_t": sq_b,
        "rsi_diff_velocity_t": rsi_diff_velocity,
    }, index=idx)


def _pair_row():
    return pd.Series({
        "half_life_rolling": 20.0, "hurst_rs": 0.3, "coint_fraction_rolling": 0.5,
        "half_life_trend_slope": 0.0, "mean_reversion_speed": 0.1,
    })


def test_features_registered():
    check("feature_cols.squeeze_min_registered", "squeeze_min" in _FEATURE_COLS)
    check("feature_cols.rsi_diff_velocity_registered", "rsi_diff_velocity" in _FEATURE_COLS)


def test_squeeze_min_and_rsi_diff_velocity_vary_across_events():
    series = _make_series()
    events = _build_examples_for_pair("A", "B", "1h", _pair_row(), MLRunSummary(), series=series)
    if len(events) < 2:
        check("varies.enough_events", False, f"only {len(events)} events, need >=2")
        return
    sq_vals = [e.squeeze_min for e in events]
    rsi_vel_vals = [e.rsi_diff_velocity for e in events]
    check("varies.squeeze_min_not_constant", len(set(np.round(sq_vals, 8))) >= 2, sq_vals)
    check("varies.rsi_diff_velocity_not_constant", len(set(np.round(rsi_vel_vals, 8))) >= 2)
    check("varies.squeeze_min_earliest_lt_latest_given_monotonic_fixture",
          sq_vals[0] < sq_vals[-1], f"{sq_vals[0]} vs {sq_vals[-1]}")


def test_squeeze_min_takes_minimum_of_both_legs():
    series = _make_series()
    events = _build_examples_for_pair("A", "B", "1h", _pair_row(), MLRunSummary(), series=series)
    if not events:
        check("min.has_events", False)
        return
    # squeeze_indicator_b_t is always <= squeeze_indicator_a_t in this
    # fixture's early portion (0.6 vs 0.4 at pos 0 -- a NOT sq_b<sq_a case)
    # -- check the actual computed min against a direct re-derivation from
    # the raw series at each event's feat_pos, not just trust the sign.
    for e in events[:3]:
        pos = series.index.get_loc(e.entry_time)
        expected = min(series["squeeze_indicator_a_t"].iloc[pos],
                        series["squeeze_indicator_b_t"].iloc[pos])
        check(f"min.matches_direct_recomputation_at_{pos}",
              np.isclose(e.squeeze_min, expected, atol=1e-9),
              f"got {e.squeeze_min}, expected {expected}")


def test_nan_when_either_leg_nan():
    series = _make_series()
    series.loc[series.index[100:120], "squeeze_indicator_a_t"] = np.nan
    events = _build_examples_for_pair("A", "B", "1h", _pair_row(), MLRunSummary(), series=series)
    any_nan_region_event = any(
        series.index.get_loc(e.entry_time) in range(100, 120) for e in events
    )
    if any_nan_region_event:
        for e in events:
            pos = series.index.get_loc(e.entry_time)
            if 100 <= pos < 120:
                check(f"nan_propagation.squeeze_min_nan_at_pos_{pos}",
                      not np.isfinite(e.squeeze_min))
                break
    else:
        print("[SKIP] nan_propagation.squeeze_min -- no entry event landed in the NaN'd region")


def test_missing_columns_fallback_all_nan_no_crash():
    series = _make_series().drop(
        columns=["squeeze_indicator_a_t", "squeeze_indicator_b_t", "rsi_diff_velocity_t"])
    events = _build_examples_for_pair("A", "B", "1h", _pair_row(), MLRunSummary(), series=series)
    check("fallback.no_crash_without_columns", True)  # reaching here means no exception
    if events:
        check("fallback.squeeze_min_all_nan",
              all(not np.isfinite(e.squeeze_min) for e in events))
        check("fallback.rsi_diff_velocity_all_nan",
              all(not np.isfinite(e.rsi_diff_velocity) for e in events))


if __name__ == "__main__":
    test_features_registered()
    test_squeeze_min_and_rsi_diff_velocity_vary_across_events()
    test_squeeze_min_takes_minimum_of_both_legs()
    test_nan_when_either_leg_nan()
    test_missing_columns_fallback_all_nan_no_crash()

    print()
    n_total = len(FAILURES)
    print("FAILED:" , FAILURES) if FAILURES else print("All checks passed.")
    sys.exit(1 if FAILURES else 0)
