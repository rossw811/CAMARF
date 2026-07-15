"""
Follow-up to _ibkr_depth_sweep.py (2026-07-14): IBM's 1h depth sweep just
found single-request success all the way to 1 Y (3906 bars), directly
contradicting task #71's earlier LNT sweep (21D max, everything from 1M up
timed out identically). Implausible vs. the prior finding — before writing
either up, test directly whether this is symbol-specific (real IBKR data-
availability/permission difference between IBM and the smaller/less-liquid
task #71 symbols) or something else (session/account state changed).

Single "1 hour", "1 Y" duration request per symbol, no pagination — matches
exactly the request that just succeeded for IBM, applied to a handful of the
9 non-DD formerly-confirmed-pair symbols from task #71.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import IBKRFeed

SYMBOLS = ["LNT", "VTR", "WELL", "CMS", "DUK", "IBM"]  # IBM as a same-session control


def _on_error(reqId, errorCode, errorString, contract=None):
    if errorCode not in (2104, 2106, 2107, 2108, 2158, 2174):
        print(f"    IBKR ERROR EVENT: reqId={reqId} code={errorCode} msg={errorString!r}")


feed = IBKRFeed()
if not feed.connect():
    print("IBKR connect failed")
    sys.exit(1)
feed._ib.errorEvent += _on_error

for sym in SYMBOLS:
    contract = feed._build_contract(sym, "equity")
    feed._wait_rate_limit("1 hour")
    feed._ib.RequestTimeout = 20
    try:
        bars = feed._ib.reqHistoricalData(
            contract, endDateTime="", durationStr="1 Y", barSizeSetting="1 hour",
            whatToShow="TRADES", useRTH=False, formatDate=1, keepUpToDate=False,
        )
        if bars:
            print(f"{sym:6s}: OK — {len(bars)} bars, {bars[0].date} to {bars[-1].date}")
        else:
            print(f"{sym:6s}: empty response")
    except Exception as e:
        print(f"{sym:6s}: EXCEPTION — {type(e).__name__}: {e!r}")

feed.disconnect() if hasattr(feed, "disconnect") else None
