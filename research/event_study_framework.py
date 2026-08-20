"""
research/event_study_framework.py -- Thread L: local event-study framework,
mirroring gs-quant's timeseries.event_study pattern (frame_timeseries_around_
events / event_impact_analysis: "detect event dates, frame a series' response
around them") but using CAMARF's OWN local event data -- no Marquee dependency
(gs-quant's own event loaders are confirmed Marquee-gated).

Two real, already-cached local event sources, no new data needed:
  - earnings.py::EarningsCalendar -- real quarterly earnings dates per symbol
  - macro.py's regime classification output -- regime TRANSITION dates
    (wherever a regime label changes day-to-day), derived generically here,
    not a new macro.py function (macro.py's job is classification, not
    event-framing -- keeping this separation matches the project's existing
    fetch/analyze split discipline).

Core primitive: frame_series_around_events(series, event_dates, window_before,
window_after) -- CAMARF-native equivalent of gs-quant's function. For each
event date, extracts a window of `series` re-indexed to RELATIVE trading-day
offset (0 = event day), returns a DataFrame with one column per event
occurrence. Downstream aggregation (mean/median response, confidence bands)
is a simple .mean(axis=1)/.std(axis=1) on the result -- not built as a
separate function, since it's a one-liner on the returned DataFrame.

Explicit non-goal (per the Thread L plan doc): NOT a new predictive-signal
search -- lead-lag/event-driven prediction already has 3 independent null
results on this universe (Finding #11 area). This is REGIME/CHARACTERISTIC
framing around events (does a pair's spread/z-score/cointegration status
change around earnings or macro transitions), a descriptive question, not a
new trading signal.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd


def frame_series_around_events(series: pd.Series, event_dates: list,
                                window_before: int, window_after: int) -> pd.DataFrame:
    """For each event date, extract series[event_date - window_before : event_date +
    window_after] re-indexed to relative trading-BAR offset (0 = the bar at or
    immediately after the event date). Returns a DataFrame indexed by relative
    offset, one column per event (named by its actual event date), NaN where a
    window extends past the series' own range. Events with NO data at all in
    their window are silently excluded (not a lookahead concern -- this is a
    purely descriptive/retrospective framing tool, not a trading decision)."""
    if series.empty or not event_dates:
        return pd.DataFrame()
    idx = series.index
    offsets = range(-window_before, window_after + 1)
    columns = {}
    for event_date in event_dates:
        event_date = pd.Timestamp(event_date)
        # searchsorted finds the first bar AT OR AFTER event_date -- the "0" anchor.
        pos = idx.searchsorted(event_date)
        if pos >= len(idx):
            continue  # event is after the series' own last bar -- nothing to frame
        col = {}
        for off in offsets:
            i = pos + off
            if 0 <= i < len(idx):
                col[off] = series.iloc[i]
        if col:
            columns[event_date] = pd.Series(col)
    if not columns:
        return pd.DataFrame()
    return pd.DataFrame(columns).reindex(list(offsets))


def macro_regime_transition_dates(regime_series: pd.Series) -> list:
    """Dates where a macro regime LABEL changes from the prior session --
    derived generically from any of macro.py's classification output columns
    (e.g. MacroResult's vix_regime/yield_regime/credit_regime), not a new
    macro.py function -- transition detection is event-framing, not
    classification, matching this project's fetch/analyze separation."""
    changed = regime_series != regime_series.shift(1)
    changed.iloc[0] = False  # the first observation is not a "transition"
    return list(regime_series.index[changed])


def frame_pair_around_earnings(spread_series: pd.Series, sym_a: str, sym_b: str,
                                earnings_cal, window_before: int = 10,
                                window_after: int = 10) -> pd.DataFrame:
    """Frames a pair's spread (or z-score) series around EITHER leg's earnings
    dates -- the union of both symbols' known earnings dates, since either
    leg's announcement is a real, potentially-disruptive event for the pair
    as a whole."""
    dates_a = earnings_cal.dates_by_symbol.get(sym_a, [])
    dates_b = earnings_cal.dates_by_symbol.get(sym_b, [])
    all_dates = sorted(set(dates_a) | set(dates_b))
    return frame_series_around_events(spread_series, all_dates, window_before, window_after)


def frame_pair_around_macro_transition(spread_series: pd.Series, regime_series: pd.Series,
                                        window_before: int = 10,
                                        window_after: int = 10) -> pd.DataFrame:
    """Frames a pair's spread (or z-score) series around macro regime
    TRANSITION dates (e.g. VIX regime flipping from 'low' to 'elevated')."""
    transition_dates = macro_regime_transition_dates(regime_series)
    return frame_series_around_events(spread_series, transition_dates, window_before, window_after)


def main():
    import argparse

    p = argparse.ArgumentParser(description="Thread L: event-study framing driver")
    p.add_argument("--symbol-a", required=True)
    p.add_argument("--symbol-b", required=True)
    p.add_argument("--tf-dir", default="1day")
    p.add_argument("--window-before", type=int, default=10)
    p.add_argument("--window-after", type=int, default=10)
    args = p.parse_args()

    from earnings import EarningsCalendar

    spread_path = f"output/results/{args.tf_dir}/spread_series_{args.symbol_a}_{args.symbol_b}.parquet"
    if not os.path.exists(spread_path):
        print(f"FATAL: {spread_path} not found")
        sys.exit(1)
    df = pd.read_parquet(spread_path)
    z_series = df["z_rolling"].dropna()

    cal = EarningsCalendar.load_or_build([args.symbol_a, args.symbol_b])
    framed = frame_pair_around_earnings(z_series, args.symbol_a, args.symbol_b, cal,
                                         args.window_before, args.window_after)
    if framed.empty:
        print(f"No earnings-date overlap found for {args.symbol_a}/{args.symbol_b} in this series' range")
        return

    mean_response = framed.mean(axis=1)
    std_response = framed.std(axis=1)
    print(f"Earnings-date-framed z-score response, {args.symbol_a}/{args.symbol_b} "
          f"({framed.shape[1]} earnings events, {len(framed)} relative bars):")
    print(pd.DataFrame({"mean_z": mean_response, "std_z": std_response, "n_events":
                         framed.notna().sum(axis=1)}).to_string())


if __name__ == "__main__":
    main()
