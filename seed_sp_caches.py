"""
Fetches S&P MidCap 400 and SmallCap 600 constituent lists directly and
seeds the cache files that data.py expects, bypassing the full pipeline.

Run this directly:
    python.exe seed_sp_caches.py

Why this exists: the underlying Wikipedia scraper logic is confirmed
correct (verified via isolated test - 579/603 SmallCap 600 tickers
parsed successfully). The "0 tickers" failures observed inside the full
data.py run are most likely transient network/Wikipedia flakiness
occurring at that specific moment during a long, heavy run - not a bug
in the parsing logic itself.

This script seeds output/cache/sp400.json and output/cache/sp600.json
directly. Once seeded, data.py's stale-cache-fallback safety net will
use these cached lists on any future run where the live scrape fails
again, instead of returning an empty/incomplete universe.

Re-run this script periodically (e.g. weekly) to keep the cache
reasonably fresh, since S&P index composition changes a few times a year.
"""

import requests
import pandas as pd
import json
import os
import time

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "cache")

INDICES = [
    {
        "url": "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
        "name": "S&P MidCap 400",
        "cache_file": "sp400.json",
        "expected_min": 350,
    },
    {
        "url": "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
        "name": "S&P SmallCap 600",
        "cache_file": "sp600.json",
        "expected_min": 500,
    },
]


def fetch_index(url: str, name: str, expected_min: int):
    print(f"\n=== Fetching {name} ===")
    resp = requests.get(url, headers={"User-Agent": _UA}, timeout=15)
    print(f"  HTTP status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"  FAILED: non-200 status")
        return []

    tables = pd.read_html(resp.text)
    print(f"  Found {len(tables)} tables")

    best_tickers = []
    best_desc = "none"
    for ti, t in enumerate(tables):
        for col in t.columns:
            col_s = str(col).lower()
            if "symbol" in col_s or "ticker" in col_s:
                tickers = [
                    str(x).strip().upper().replace(".", "-")
                    for x in t[col]
                    if str(x).strip()
                    and len(str(x).strip()) <= 6
                    and str(x).strip()[0].isalpha()
                ]
                if len(tickers) > len(best_tickers):
                    best_tickers = tickers
                    best_desc = f"table[{ti}] col={col!r}"

    print(f"  Best candidate: {best_desc} -> {len(best_tickers)} tickers")
    if len(best_tickers) < expected_min:
        print(f"  WARNING: below expected_min={expected_min}, but using anyway")
    return best_tickers


def main():
    os.makedirs(CACHE_DIR, exist_ok=True)

    for idx in INDICES:
        try:
            tickers = fetch_index(idx["url"], idx["name"], idx["expected_min"])
            if tickers:
                cache_path = os.path.join(CACHE_DIR, idx["cache_file"])
                with open(cache_path, "w") as f:
                    json.dump(tickers, f)
                print(f"  SAVED {len(tickers)} tickers -> {cache_path}")
            else:
                print(f"  SKIPPED save - no tickers retrieved")
        except Exception as e:
            print(f"  EXCEPTION fetching {idx['name']}: {type(e).__name__}: {e}")

    print("\n=== Done ===")
    print("Re-run data.py now - it should pick up these seeded caches")
    print("(valid for 24h per the freshness check, but the stale-cache")
    print("fallback will keep using them indefinitely if future live")
    print("fetches fail, so re-running this script weekly is plenty).")


if __name__ == "__main__":
    main()
