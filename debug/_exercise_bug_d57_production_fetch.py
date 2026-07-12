"""
Real production-equivalent exercise of the BUG-D57 fix (Development.md, 2026-07-12): runs the
EXACT same call sequence data.py's own main loop uses for an intraday yfinance fallback fetch --
YFinanceFeed.get_intraday_fallback() -> snap_timestamps(symbol=...) -> DataStore.append() -- for
real international-suffixed symbols, writing to the REAL production cache
(output/cache/{symbol}_1hr.parquet), not just a read-only verification.

Distinct from debug/_verify_exchange_aware_live_fetch.py (which checked the row-count effect in
isolation, read-only) -- this confirms the fix works end-to-end through the full pipeline
including the final cache write, and that the persisted cache is genuinely usable (a
DataStore.load() round-trip after the write).

Not a permanent addition to the production universe -- these symbols are NOT added to any
config/universe list here. This is a targeted exercise of the FIX, not a universe-expansion
decision (that's a separate, larger topic already tracked as pending Ross's direction).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import YFinanceFeed, DataCleaner, DataStore, snap_timestamps

TF = "1h"
TEST_SYMBOLS = ["VOD.L", "7267.T", "0700.HK"]


def main():
    for symbol in TEST_SYMBOLS:
        print(f"\n=== {symbol} ===")

        # 1. Real fetch (unmodified production function).
        raw = YFinanceFeed.get_intraday_fallback(symbol, "equity", TF)
        if raw is None or raw.empty:
            print(f"  SKIP: no data returned (network/availability)")
            continue
        print(f"  Fetched + DataCleaner.clean()'d: {len(raw)} rows")

        # 2. Real exchange-aware snap (the BUG-D57 fix, applied exactly as data.py's main loop does).
        snapped = snap_timestamps(raw, TF, source="yfinance", symbol=symbol)
        print(f"  After snap_timestamps(symbol='{symbol}'): {len(snapped)} rows "
              f"({len(snapped)/len(raw)*100:.1f}% retained)")

        if snapped.empty:
            print(f"  SKIP: zero rows survived snapping, nothing to cache")
            continue

        # 3. Real cache write (the piece the earlier read-only verification never exercised).
        DataStore.append(symbol, TF, snapped)
        cache_path = DataStore._path(symbol, TF)
        print(f"  Written to real cache: {cache_path}")

        # 4. Round-trip confirm: load it back exactly as any downstream consumer would.
        reloaded = DataStore.load(symbol, TF)
        if reloaded is None or len(reloaded) != len(snapped):
            print(f"  FAIL: round-trip mismatch (wrote {len(snapped)}, "
                  f"loaded back {0 if reloaded is None else len(reloaded)})")
        else:
            print(f"  Round-trip confirmed: {len(reloaded)} rows load back correctly, "
                  f"index range {reloaded.index.min()} to {reloaded.index.max()}")


if __name__ == "__main__":
    main()
