"""
Fetches S&P MidCap 400 and SmallCap 600 constituent lists and seeds the
cache files data.py expects. Includes retry logic: the underlying fetch
logic is confirmed correct (isolated test succeeded with 579/603 tickers),
but Wikipedia/network conditions have proven intermittently flaky across
multiple attempts today - works sometimes, fails other times, with no
code-level bug found despite extensive verification. Retrying within one
run gives it multiple chances instead of one-shot.

Run this directly:
    python.exe seed_sp_caches.py

Re-run periodically (weekly is plenty) to keep the cache reasonably
fresh, since S&P index composition changes a few times a year.
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
MAX_ATTEMPTS = 5
RETRY_DELAY_SEC = 8

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


def fetch_index_once(url: str, name: str, expected_min: int):
    """Single attempt. Returns (tickers, status_summary_string)."""
    resp = requests.get(url, headers={"User-Agent": _UA}, timeout=15)
    if resp.status_code != 200:
        return [], f"HTTP {resp.status_code}"

    tables = pd.read_html(resp.text)
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

    status = f"HTTP 200, {len(tables)} tables, best={best_desc} ({len(best_tickers)} tickers)"
    return best_tickers, status


def fetch_index_with_retry(url: str, name: str, expected_min: int):
    print(f"\n=== Fetching {name} ===")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            tickers, status = fetch_index_once(url, name, expected_min)
            print(f"  Attempt {attempt}/{MAX_ATTEMPTS}: {status}")
            if len(tickers) >= expected_min:
                print(f"  SUCCESS on attempt {attempt}")
                return tickers
            if attempt < MAX_ATTEMPTS:
                print(
                    f"  Below expected_min={expected_min}, retrying in {RETRY_DELAY_SEC}s..."
                )
                time.sleep(RETRY_DELAY_SEC)
        except Exception as e:
            print(
                f"  Attempt {attempt}/{MAX_ATTEMPTS} EXCEPTION: {type(e).__name__}: {e}"
            )
            if attempt < MAX_ATTEMPTS:
                print(f"  Retrying in {RETRY_DELAY_SEC}s...")
                time.sleep(RETRY_DELAY_SEC)

    print(f"  FAILED after {MAX_ATTEMPTS} attempts")
    return []


def main():
    os.makedirs(CACHE_DIR, exist_ok=True)

    for idx in INDICES:
        tickers = fetch_index_with_retry(idx["url"], idx["name"], idx["expected_min"])
        if tickers:
            cache_path = os.path.join(CACHE_DIR, idx["cache_file"])
            with open(cache_path, "w") as f:
                json.dump(tickers, f)
            print(f"  SAVED {len(tickers)} tickers -> {cache_path}")
        else:
            print(f"  GAVE UP - no cache file written for {idx['name']}")

    print("\n=== Done ===")
    print("Check above for SAVED vs GAVE UP for each index before running data.py.")


if __name__ == "__main__":
    main()
