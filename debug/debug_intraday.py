# =============================================================================
# CAMARF — debug_intraday.py
# Tests intraday requests sequentially to find exact IBKR pacing threshold.
# Run: python debug_intraday.py
# =============================================================================

import nest_asyncio

nest_asyncio.apply()
import ib_insync as ibi

ibi.util.startLoop()
import time
from datetime import datetime, timezone

ib = ibi.IB()
ib.connect("127.0.0.1", 4001, clientId=12, readonly=True, timeout=30)

contract = ibi.Stock("ABT", "SMART", "USD")
ib.qualifyContracts(contract)

end_dt = datetime.now(tz=timezone.utc).strftime("%Y%m%d %H:%M:%S UTC")

tests = [
    ("4 hours", "4h", "10 Y", end_dt),
    ("1 hour", "1h", "5 Y", end_dt),
    ("30 mins", "30m", "2 Y", end_dt),
    ("5 mins", "5m", "6 M", end_dt),
]

print("\n" + "=" * 60)
print("Intraday sequential pacing test — ABT")
print("=" * 60)

for delay in [5, 10, 15, 20, 30]:
    print(f"\n--- Testing with {delay}s inter-request delay ---")
    for tf_ibkr, tf_label, dur, end in tests:
        time.sleep(delay)
        try:
            ib.RequestTimeout = 60
            bars = ib.reqHistoricalData(
                contract,
                endDateTime=end,
                durationStr=dur,
                barSizeSetting=tf_ibkr,
                whatToShow="TRADES",
                useRTH=False,
                formatDate=1,
                keepUpToDate=False,
            )
            n = len(bars) if bars else 0
            status = f"bars={n:5d}" if n > 0 else "EMPTY"
        except Exception as e:
            status = f"ERROR: {str(e)[:60]}"
        print(f"  {tf_label:5s} ({delay}s delay): {status}")
        if "EMPTY" in status or "ERROR" in status:
            print(f"  → Failed at {tf_label} with {delay}s delay")
            break
    else:
        print(f"  → ALL passed with {delay}s delay")
        break

ib.disconnect()
print("\nDone.")
