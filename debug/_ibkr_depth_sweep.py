"""
Quick live sweep (2026-07-14, Ross's request): what is IBKR's real single-
request historical-data depth ceiling for IBM, PER TIMEFRAME? Task #71 only
swept this for 1h equity bars (ceiling: 21-30 days, not the "10 Y confirmed"
_MAX_DURATION claims). This generalizes that same escalating-duration sweep
across every IBKR bar size this project uses, on one liquid, well-covered
symbol (IBM), to see whether the same account/subscription-tier limitation
applies uniformly or varies by bar size.

Method: for each TF, issue single reqHistoricalData calls with an escalating
durationStr ladder, stop at the first failure/timeout (that boundary is what
matters — no need to keep pushing once it's found, matching the existing 1h
sweep's own stopping logic), report the last successful duration + actual
bar count + real date range returned.

Read-only, no cache writes. Uses whatToShow via IBKRFeed._what_to_show()
(ADJUSTED_LAST for equity 1 day, TRADES otherwise) — the same convention
production uses.
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import IBKRFeed
import ib_insync as ibi

SYMBOL = "IBM"
ASSET_CLASS = "equity"

INTRADAY_LADDER = ["5 D", "10 D", "14 D", "21 D", "1 M", "3 M", "6 M", "1 Y", "2 Y", "5 Y", "10 Y"]
DAILY_LADDER = ["1 Y", "2 Y", "5 Y", "10 Y", "15 Y", "20 Y", "30 Y"]

TF_LADDERS = {
    "1 min": INTRADAY_LADDER,
    "2 mins": INTRADAY_LADDER,
    "3 mins": INTRADAY_LADDER,
    "5 mins": INTRADAY_LADDER,
    "15 mins": INTRADAY_LADDER,
    "30 mins": INTRADAY_LADDER,
    "1 hour": INTRADAY_LADDER,
    "4 hours": INTRADAY_LADDER,
    "1 day": DAILY_LADDER,
    "1W": DAILY_LADDER,
    "1M": DAILY_LADDER,
}


def _on_error(reqId, errorCode, errorString, contract=None):
    if errorCode not in (2104, 2106, 2107, 2108, 2158, 2174):  # routine farm-status/warning noise
        print(f"    IBKR ERROR EVENT: reqId={reqId} code={errorCode} msg={errorString!r}")


def main():
    feed = IBKRFeed()
    if not feed.connect():
        print("IBKR connect failed")
        sys.exit(1)
    feed._ib.errorEvent += _on_error

    contract = feed._build_contract(SYMBOL, ASSET_CLASS)
    print(f"contract: {contract}\n")

    results = {}
    for tf, ladder in TF_LADDERS.items():
        print(f"=== {tf} ===")
        last_good = None
        for dur in ladder:
            feed._wait_rate_limit(tf)
            feed._ib.RequestTimeout = 20
            wts = IBKRFeed._what_to_show(ASSET_CLASS, tf)
            t0 = time.time()
            try:
                bars = feed._ib.reqHistoricalData(
                    contract,
                    endDateTime="",
                    durationStr=dur,
                    barSizeSetting=tf,
                    whatToShow=wts,
                    useRTH=False,
                    formatDate=1,
                    keepUpToDate=False,
                )
            except Exception as e:
                elapsed = time.time() - t0
                print(f"  {dur:6s}: EXCEPTION after {elapsed:.1f}s — {type(e).__name__}: {e!r}")
                break
            elapsed = time.time() - t0
            if not bars:
                print(f"  {dur:6s}: empty response after {elapsed:.1f}s — treating as boundary")
                break
            n = len(bars)
            first, last = bars[0].date, bars[-1].date
            print(f"  {dur:6s}: OK ({elapsed:.1f}s) — {n} bars, {first} to {last}")
            last_good = (dur, n, first, last)
        results[tf] = last_good

    print("\n" + "=" * 70)
    print(f"SUMMARY — IBM max single-request depth per timeframe:")
    print("=" * 70)
    for tf, res in results.items():
        if res is None:
            print(f"  {tf:8s}: NOTHING succeeded (even the shortest duration failed)")
        else:
            dur, n, first, last = res
            print(f"  {tf:8s}: max confirmed duration={dur:6s}  {n:6d} bars  {first} -> {last}")

    feed.disconnect() if hasattr(feed, "disconnect") else None


if __name__ == "__main__":
    main()
