"""
Ad-hoc check (task #71 follow-up, 2026-07-14): what does IBKR's raw
reqHistoricalData response actually contain for a 1h-bar equity request,
BEFORE data_ibkr.py's merge_with_yfinance() truncates it to bars older
than yfinance's own window? Settles whether the "10 Y confirmed for 1h"
claim in data.py's IBKRFeed._MAX_DURATION holds for equities.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import IBKRFeed

feed = IBKRFeed()

def _on_error(reqId, errorCode, errorString, contract=None):
    print(f"IBKR ERROR EVENT: reqId={reqId} code={errorCode} msg={errorString!r}")

if not feed.connect():
    print("IBKR connect failed")
    sys.exit(1)
feed._ib.errorEvent += _on_error

import ib_insync as ibi

contract = feed._build_contract("LNT", "equity")
print("contract:", contract)
feed._ib.RequestTimeout = 20

tests = [
    ("10 D", "1 hour", "TRADES"),
    ("14 D", "1 hour", "TRADES"),
    ("21 D", "1 hour", "TRADES"),
]
for dur, bar_size, wts in tests:
    try:
        bars = feed._ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=dur,
            barSizeSetting=bar_size,
            whatToShow=wts,
            useRTH=False,
            formatDate=1,
            keepUpToDate=False,
        )
        n = len(bars) if bars else 0
        first = bars[0].date if bars else None
        last = bars[-1].date if bars else None
        print(f"dur={dur} bar={bar_size} wts={wts}: bars={n} first={first} last={last}")
    except Exception as e:
        print(f"dur={dur} bar={bar_size} wts={wts}: EXCEPTION {type(e).__name__}: {e!r}")

feed.disconnect() if hasattr(feed, "disconnect") else None
