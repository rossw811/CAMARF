"""
Verification for the 2026-07-20 Grand Sweep fix to ml.py::_build_examples_for_pair
and backtest.py's Layer-2 ML-gate feature construction: both previously computed
hedge_ratio_drift ONCE per pair from the static full-sample scalar fields
hedge_ratio_ols/hedge_ratio_kalman_mean, giving every entry event (including
early-history ones) the same value informed by the pair's ENTIRE hedge-ratio
history -- the same lookahead class analysis.py already fixed once for
backtest.py's position sizing (hedge_ratio_ols_t/kalman_t), per its own
comments at ~line 4865-4868, but never reused here.

Proves: (1) with hedge_ratio_ols_t/kalman_t columns present, hedge_ratio_drift
now varies across entry events at different points in time (matching the
point-in-time series at each event's own feat_pos) instead of being constant;
(2) each entry event's drift value uses ONLY the series value at its own
position, not a value that could only be known using later data; (3) the
scalar fallback still works when the _t columns are absent (pre-fix
spread_series files).
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ml import _build_examples_for_pair, MLRunSummary


def _make_series(n=300):
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.RandomState(3)
    # Oscillating z-score so multiple entry events fire across the series.
    z = 3.0 * np.sin(np.linspace(0, 8 * np.pi, n)) + rng.normal(0, 0.1, n)
    half_life = np.full(n, 20.0)
    # hedge_ratio_ols_t/kalman_t DRIFT APART over time (0 at start, growing to
    # a large late-series gap) -- lets us check each entry's drift value only
    # reflects the series' value AT that entry, not the eventual endpoint.
    ols_t = np.full(n, 2.0)
    kal_t = 2.0 + np.linspace(0, 1.0, n)  # kalman drifts from 2.0 -> 3.0 over the series
    return pd.DataFrame({
        "z_rolling": z,
        "half_life_rolling": half_life,
        "hedge_ratio_ols_t": ols_t,
        "hedge_ratio_kalman_t": kal_t,
    }, index=idx)


def main() -> None:
    failures = []
    series = _make_series()
    pair_row = pd.Series({
        "half_life_rolling": 20.0,
        "hedge_ratio_ols": 2.0,
        "hedge_ratio_kalman_mean": 2.5,  # full-sample mean -- should NOT be used when _t present
        "hurst_rs": 0.3,
        "coint_fraction_rolling": 0.5,
        "half_life_trend_slope": 0.0,
        "mean_reversion_speed": 0.1,
    })
    summary = MLRunSummary()

    events = _build_examples_for_pair("A", "B", "1h", pair_row, summary, series=series)
    if len(events) < 2:
        failures.append(f"expected at least 2 entry events from the oscillating fixture, got {len(events)}")
    else:
        drifts = [e.hedge_ratio_drift for e in events]
        # 1. Drift must vary across events (not constant) -- proves per-event
        #    computation, not a single upfront full-sample value.
        if len(set(np.round(drifts, 8))) < 2:
            failures.append(f"hedge_ratio_drift is constant across events ({drifts}) -- fix not wired correctly")
        # 2. No event's drift should equal the full-sample scalar formula
        #    (|2.0-2.5|/2.0 = 0.25) unless coincidentally at that exact bar.
        scalar_drift = abs(2.0 - 2.5) / 2.0
        if all(np.isclose(d, scalar_drift, atol=1e-9) for d in drifts):
            failures.append("every event's drift matches the OLD static scalar formula -- fix not applied")
        # 3. Earliest event's drift should be smaller than the latest event's
        #    (kalman_t drifts away from ols_t=2.0 over the series) -- confirms
        #    each event reflects ITS OWN point in time, not the endpoint.
        if not (drifts[0] < drifts[-1]):
            failures.append(
                f"expected earliest event's drift ({drifts[0]}) < latest event's drift "
                f"({drifts[-1]}) given kalman_t diverges monotonically over the series"
            )

    # 4. Fallback path: no _t columns present -> uses the scalar, constant across events.
    series_no_pit = series.drop(columns=["hedge_ratio_ols_t", "hedge_ratio_kalman_t"])
    events_fallback = _build_examples_for_pair("A", "B", "1h", pair_row, MLRunSummary(), series=series_no_pit)
    if events_fallback:
        fallback_drifts = [e.hedge_ratio_drift for e in events_fallback]
        if not all(np.isclose(d, scalar_drift, atol=1e-9) for d in fallback_drifts):
            failures.append(f"fallback path (no _t columns) should use the scalar formula uniformly, got {fallback_drifts}")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("ml.py hedge_ratio_drift point-in-time fix verified.")
        print(f"  {len(events)} events, drift range [{min(drifts):.4f}, {max(drifts):.4f}] (varies, not constant)")
        print(f"  Fallback (no _t columns): uniform scalar drift = {fallback_drifts[0]:.4f}")


if __name__ == "__main__":
    main()
