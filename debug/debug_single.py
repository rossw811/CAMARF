# =============================================================================
# CAMARF — debug_single.py
# Tests a single equity (AMD) and prints exactly what IBKR returns raw
# before any cleaning logic touches it.
# Run: python debug_single.py
# =============================================================================

import nest_asyncio

nest_asyncio.apply()

import ib_insync as ibi

ibi.util.startLoop()
from datetime import datetime

ib = ibi.IB()
ib.connect("127.0.0.1", 4001, clientId=11, readonly=True, timeout=30)

contract = ibi.Stock("AMD", "SMART", "USD")
qualified = ib.qualifyContracts(contract)
print(f"\nQualified contract: {qualified}")

print("\n" + "=" * 60)
print("RAW IBKR RESPONSE — AMD daily ADJUSTED_LAST")
print("=" * 60)

ib.RequestTimeout = 60
bars = ib.reqHistoricalData(
    contract,
    endDateTime="",
    durationStr="20 Y",
    barSizeSetting="1 day",
    whatToShow="ADJUSTED_LAST",
    useRTH=False,
    formatDate=1,
    keepUpToDate=False,
)

print(f"Bars returned: {len(bars) if bars else 0}")
if bars:
    df = ibi.util.df(bars)
    print(f"Columns: {list(df.columns)}")
    print(f"Index type: {type(df.index)}")
    print(f"\nFirst 3 rows:\n{df.head(3)}")
    print(f"\nLast 3 rows:\n{df.tail(3)}")
else:
    print("NO BARS RETURNED")

print("\n" + "=" * 60)
print("RAW IBKR RESPONSE — AMD daily TRADES")
print("=" * 60)

bars2 = ib.reqHistoricalData(
    contract,
    endDateTime="",
    durationStr="20 Y",
    barSizeSetting="1 day",
    whatToShow="TRADES",
    useRTH=False,
    formatDate=1,
    keepUpToDate=False,
)

print(f"Bars returned: {len(bars2) if bars2 else 0}")
if bars2:
    df2 = ibi.util.df(bars2)
    print(f"Columns: {list(df2.columns)}")
    print(f"\nFirst 3 rows:\n{df2.head(3)}")

ib.disconnect()
