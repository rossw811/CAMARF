"""
Live-data companion to `debug/_verify_exchange_aware_session.py` (which used
synthetic timestamps). Development.md's second-pass triage item #7: the
exchange-aware `snap_timestamps()` fix (2026-07-11's Option A market-cap/
sector session-handling work) was built and synthetically verified but never
exercised on a REAL yfinance fetch for a real `.L`/`.T`/`.HK` symbol.

Calls the REAL `YFinanceFeed.get_intraday_fallback()` and `snap_timestamps()`
functions UNCHANGED, for real international tickers, at 1h. Compares row
counts WITH `symbol=` (exchange-aware session check) vs. WITHOUT (the
pre-fix NYSE-only behavior) on the SAME real fetched data.

Read-only: never calls `DataStore.append`, never writes to any cache file.
Safe to run alongside another data.py/analysis.py process, since it makes
its own independent yfinance calls and touches no shared on-disk state.

Expected (confirms the real-world bug this session's fix addresses): with
symbol=None (pre-fix), an LSE/JPX/HKEX-listed symbol's bars fall outside the
hardcoded NYSE 9:30-16:00 ET session and are mostly/entirely dropped. With
symbol= given, the exchange-aware branch activates and correctly retains the
bars using that exchange's own local session hours.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import YFinanceFeed, snap_timestamps

# Real, liquid tickers on each covered exchange
TEST_SYMBOLS = [
    ("VOD.L", "XLON"),    # Vodafone, London Stock Exchange
    ("7267.T", "JPX"),    # Honda, Tokyo (already a confirmed pair elsewhere in this project)
    ("0700.HK", "XHKG"),  # Tencent, Hong Kong
]

TF = "1h"


def main():
    results = []
    for symbol, expected_exchange in TEST_SYMBOLS:
        print(f"\n=== {symbol} (expected exchange: {expected_exchange}) ===")
        df = YFinanceFeed.get_intraday_fallback(symbol, "equity", TF)
        if df is None or df.empty:
            print(f"  SKIP: no data returned by yfinance for {symbol}@{TF} "
                  f"(network/availability issue, not a snap_timestamps question)")
            results.append((symbol, None, None))
            continue

        raw_rows = len(df)
        without_symbol = snap_timestamps(df.copy(), TF, source="yfinance", symbol=None)
        with_symbol = snap_timestamps(df.copy(), TF, source="yfinance", symbol=symbol)

        n_without = len(without_symbol)
        n_with = len(with_symbol)
        pct_without = n_without / raw_rows * 100 if raw_rows else 0
        pct_with = n_with / raw_rows * 100 if raw_rows else 0

        print(f"  raw fetched rows: {raw_rows}")
        print(f"  snap_timestamps(symbol=None)   [pre-fix NYSE-only]: {n_without} rows kept ({pct_without:.1f}%)")
        print(f"  snap_timestamps(symbol='{symbol}') [exchange-aware]: {n_with} rows kept ({pct_with:.1f}%)")
        results.append((symbol, pct_without, pct_with))

    print("\n=== Summary ===")
    any_data = False
    for symbol, pct_without, pct_with in results:
        if pct_without is None:
            print(f"  {symbol}: no data available this run (inconclusive, not a failure)")
            continue
        any_data = True
        verdict = "CONFIRMS the fix matters" if pct_with > pct_without + 10 else (
            "no meaningful difference this run" if abs(pct_with - pct_without) <= 10 else "UNEXPECTED: exchange-aware kept FEWER rows"
        )
        print(f"  {symbol}: NYSE-only retained {pct_without:.1f}%, exchange-aware retained {pct_with:.1f}% -- {verdict}")

    if not any_data:
        print("\n  No live data available for any test symbol this run (network/yfinance availability) "
              "-- re-run later, this is not evidence the fix doesn't work.")


if __name__ == "__main__":
    main()
