# =============================================================================
# CAMARF — diagnose.py
# Diagnostic tool for IBKR historical data access.
# Tests intraday endDateTime formats and measures depth per timeframe.
# Run: python diagnose.py
# =============================================================================

import nest_asyncio

nest_asyncio.apply()

import ib_insync as ibi

ibi.util.startLoop()

from datetime import datetime, timezone
import time

ib = ibi.IB()
ib.connect("127.0.0.1", 4001, clientId=10, readonly=True, timeout=30)

contract = ibi.Stock("AAPL", "SMART", "USD")
ib.qualifyContracts(contract)

# =============================================================================
# TEST 1: Which endDateTime format works for intraday?
# =============================================================================
print("\n" + "=" * 60)
print("TEST 1 — 1h endDateTime format")
print("=" * 60)

end_formats = [
    ("UTC string", datetime.now(tz=timezone.utc).strftime("%Y%m%d %H:%M:%S UTC")),
    ("Empty string", ""),
    ("No timezone", datetime.now().strftime("%Y%m%d %H:%M:%S")),
    ("EST offset", datetime.now().strftime("%Y%m%d %H:%M:%S") + " US/Eastern"),
]

for label, end_dt in end_formats:
    time.sleep(3)
    try:
        ib.RequestTimeout = 30
        bars = ib.reqHistoricalData(
            contract,
            endDateTime=end_dt,
            durationStr="30 D",
            barSizeSetting="1 hour",
            whatToShow="TRADES",
            useRTH=False,
            formatDate=1,
            keepUpToDate=False,
        )
        n = len(bars) if bars else 0
        first = str(bars[0].date)[:19] if n > 0 else "N/A"
        status = f"bars={n:4d} | first={first}"
    except Exception as e:
        status = f"ERROR: {e}"
    print(f"  {label:20s} | {status}")

# =============================================================================
# TEST 2: Full depth calibration with correct endDateTime
# =============================================================================
print("\n" + "=" * 60)
print("TEST 2 — Depth calibration (TRADES, all TFs)")
print("=" * 60)

# Use whichever endDateTime worked above — default to UTC string
end_dt_intraday = datetime.now(tz=timezone.utc).strftime("%Y%m%d %H:%M:%S UTC")

TIMEFRAME_TESTS = [
    ("1 min", "1m", "30 D", end_dt_intraday),
    ("5 mins", "5m", "6 M", end_dt_intraday),
    ("15 mins", "15m", "1 Y", end_dt_intraday),
    ("30 mins", "30m", "2 Y", end_dt_intraday),
    ("1 hour", "1h", "5 Y", end_dt_intraday),
    ("4 hours", "4h", "10 Y", end_dt_intraday),
    ("1 day", "1D", "20 Y", ""),
    ("1W", "7D", "20 Y", ""),
    ("1M", "1M", "20 Y", ""),
]

print(f"\n{'TF':>6}  {'Bars':>6}  {'Earliest':>12}  {'Depth'}")
print("-" * 50)

for tf_ibkr, tf_label, duration, end_dt in TIMEFRAME_TESTS:
    time.sleep(3)
    try:
        ib.RequestTimeout = 60
        bars = ib.reqHistoricalData(
            contract,
            endDateTime=end_dt,
            durationStr=duration,
            barSizeSetting=tf_ibkr,
            whatToShow="TRADES",
            useRTH=False,
            formatDate=1,
            keepUpToDate=False,
        )
        n = len(bars) if bars else 0
        if n > 0:
            first = str(bars[0].date)[:10]
            try:
                from datetime import datetime as dt

                d1 = dt.strptime(first, "%Y-%m-%d")
                d2 = dt.now()
                days = (d2 - d1).days
                depth = (
                    f"~{days//365}Y {(days%365)//30}M" if days >= 365 else f"~{days}D"
                )
            except Exception:
                depth = "?"
        else:
            first = "N/A"
            depth = "NO DATA"
        print(f"{tf_label:>6}  {n:>6}  {first:>12}  {depth}")
    except Exception as e:
        print(f"{tf_label:>6}  ERROR: {e}")

print("=" * 50)
ib.disconnect()
print("\nDone. Paste full output to Claude.")
