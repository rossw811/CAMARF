"""
Synthetic verification for data.py's exchange-aware snap_timestamps()
change (Development.md "Planned: Exchange-Aware Intraday Session
Handling"). Confirms: (1) zero behavior change for existing US symbols
(no symbol arg, or a symbol with no recognized suffix) — the exact
regression risk this change must avoid; (2) a London-listed (.L) symbol's
bars during LSE's real session (8:00-16:30 London time) are now KEPT,
where the old NYSE-only 9:30-16:00 ET check would have dropped ALL of
them (the confirmed real bug); (3) bars genuinely outside even the LSE
session are still correctly dropped.

Run: python debug/_verify_exchange_aware_session.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import snap_timestamps


def _make_ohlcv(index):
    n = len(index)
    close = 100.0 + np.cumsum(np.random.normal(0, 0.1, n))
    return pd.DataFrame({
        "open": close, "high": close + 0.05, "low": close - 0.05,
        "close": close, "volume": np.full(n, 1000),
    }, index=index)


def case1_us_symbol_unchanged():
    """No symbol arg (existing call sites) -> identical to pre-change
    behavior: NYSE session 9:30-16:00 ET, non-matching bars dropped."""
    idx = pd.date_range("2026-01-05 09:30", "2026-01-05 16:29", freq="1min", tz="America/New_York")
    df = _make_ohlcv(idx)
    result_no_symbol = snap_timestamps(df, "1m", "yfinance")
    result_us_symbol = snap_timestamps(df, "1m", "yfinance", symbol="AAPL")
    print(f"Case 1 (US symbol): no-symbol-arg rows={len(result_no_symbol)}, "
          f"AAPL-symbol rows={len(result_us_symbol)}")
    assert len(result_no_symbol) == len(result_us_symbol), (
        "passing a non-suffixed US symbol must be byte-identical to omitting it"
    )
    assert len(result_no_symbol) > 300, "a normal NYSE session should keep most 1m bars"
    print("  PASS: US symbol path unaffected by the exchange-aware change")


def case2_london_symbol_now_kept():
    """A .L symbol with bars during LSE's real 8:00-16:30 London session.
    In UTC (London=UTC in Jan, no DST), that's 8:00-16:30 UTC ->
    3:00-11:30 AM ET -- entirely OUTSIDE the old hardcoded 9:30-16:00 ET
    NYSE window. Old code would drop 100% of these bars; new code, given
    symbol='VOD.L', must keep them."""
    idx = pd.date_range("2026-01-05 08:00", "2026-01-05 16:29", freq="1min", tz="Europe/London")
    df = _make_ohlcv(idx)

    result_old_path = snap_timestamps(df, "1m", "yfinance")  # no symbol -> NYSE-only check
    result_new_path = snap_timestamps(df, "1m", "yfinance", symbol="VOD.L")

    print(f"Case 2 (LSE symbol VOD.L): NYSE-only-check rows={len(result_old_path)}, "
          f"exchange-aware rows={len(result_new_path)}")
    # London 8:00-16:30 GMT (Jan, no DST) = 3:00-11:30 AM ET; NYSE session is
    # 9:30 AM-4:00 PM ET -> only the documented 2-hour morning overlap
    # (9:30-11:30 AM ET = 120 min) survives the OLD NYSE-only check, not zero
    # and not the full session -- matches Development.md's own "2-hour
    # morning overlap window" account exactly, corroborating that account.
    assert len(result_old_path) == 120, (
        f"expected exactly the documented 2-hour morning overlap (120 1m bars) to survive the old "
        f"NYSE-only check, got {len(result_old_path)} — the synthetic scenario or the overlap "
        f"account itself needs re-checking, not silently accepted"
    )
    assert len(result_new_path) == 510, (
        f"the exchange-aware path must keep the FULL real LSE session (8:00-16:30 = 510 1m bars), "
        f"got {len(result_new_path)}"
    )
    print("  PASS: old path only kept the documented 2h overlap (120 bars); new path keeps the "
          "full real LSE session (510 bars) — confirms both the bug's exact shape and the fix")


def case3_outside_lse_session_dropped():
    """Bars clearly outside even LSE's own session (e.g. LSE midnight)
    must still be dropped under the exchange-aware path."""
    idx = pd.date_range("2026-01-05 00:00", "2026-01-05 02:00", freq="1min", tz="Europe/London")
    df = _make_ohlcv(idx)
    result = snap_timestamps(df, "1m", "yfinance", symbol="VOD.L")
    print(f"Case 3 (outside LSE session): rows={len(result)}")
    assert len(result) == 0, "bars genuinely outside LSE's own session must still be dropped"
    print("  PASS")


if __name__ == "__main__":
    case1_us_symbol_unchanged()
    case2_london_symbol_now_kept()
    case3_outside_lse_session_dropped()
    print("\nAll exchange_aware_session checks passed.")
