"""
period_bars.py -- one convention for every coarse (daily-derived) bar in the project (code review D13, 2026-09-27).

Each 7D/1M/3M/6M/1Y bar is stamped at the CALENDAR END of its period: Friday for 7D, then month end, quarter end,
Jun-30/Dec-31 for half-years, and Dec-31. The bar's close is the last daily close inside the period, so the stamp is
never earlier than the data it carries.

Why this convention:
  - Previously 1M/3M/6M/1Y were stamped at the period START ("MS"/"QS"/"2QS"/"YS", label="left") while carrying the
    period-end close. That is up to a full period of lookahead in any as-of join.
  - Stamping at the last actual trading date instead would give an equity and a 24/7 crypto series different
    stamps for the same month (Nov-28 vs Nov-30). A calendar period end is shared by every asset class.
  - "2QS"/"2QE" bins are anchored on the first observation, so a March start shifted the half-years. Explicit
    period keys fix the halves to Jan-Jun/Jul-Dec.
The current, incomplete period gets a stamp in the future (e.g. Sep-30 while it is still Sep-27). The bar carries
the latest close; the next refresh re-derives it from the merged daily history.
"""
from typing import Optional

import pandas as pd

TIMEFRAMES = ("7D", "1M", "3M", "6M", "1Y")
_AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
        "close_total_return": "last", "close_usd": "last"}


def period_end_index(index: pd.DatetimeIndex, tf_label: str) -> pd.DatetimeIndex:
    """Calendar period-end stamp (midnight) of each timestamp's period."""
    idx = pd.DatetimeIndex(index)
    if tf_label == "7D":
        return idx.to_period("W-FRI").end_time.normalize()
    if tf_label == "1M":
        return idx.to_period("M").end_time.normalize()
    if tf_label == "3M":
        return idx.to_period("Q-DEC").end_time.normalize()
    if tf_label == "6M":
        month = pd.Index(idx.month)
        return pd.DatetimeIndex([pd.Timestamp(y, 6, 30) if m <= 6 else pd.Timestamp(y, 12, 31)
                                 for y, m in zip(idx.year, month)])
    if tf_label == "1Y":
        return idx.to_period("Y").end_time.normalize()
    raise ValueError(f"period_end_index: unknown timeframe {tf_label!r} (known: {TIMEFRAMES})")


def resample_to_period_end(df: pd.DataFrame, tf_label: str, agg: Optional[dict] = None) -> pd.DataFrame:
    """Aggregate a daily OHLCV frame to tf_label bars stamped at calendar period end.
    Periods with no valid close, and non-positive closes, are dropped (same rule as the old resamplers)."""
    agg = {k: v for k, v in (agg or _AGG).items() if k in df.columns}
    keys = period_end_index(df.index, tf_label)
    out = df[list(agg)].groupby(keys).agg(agg)
    out.index = pd.DatetimeIndex(out.index)
    out.index.name = df.index.name
    out = out.dropna(subset=["close"])
    return out[out["close"] > 0]


def restamp_to_period_end(df: pd.DataFrame, tf_label: str) -> pd.DataFrame:
    """Move already-aggregated bars (e.g. WRDS native monthly, stamped on the last trading day) onto the calendar
    period end. Values are untouched; if two rows fall into one period the later one is kept."""
    out = df.copy()
    out.index = period_end_index(df.index, tf_label)
    return out[~out.index.duplicated(keep="last")]
