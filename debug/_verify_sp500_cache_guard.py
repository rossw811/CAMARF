"""
Regression test for code-review finding D14 (2026-09-26): the Wikipedia S&P 500 path called
UniverseBuilder._save_sp500_cache(tickers) with no size check (the iShares path and both cache
readers require > 400), so an empty/truncated scrape could overwrite the last good cache --
violating CLAUDE.md's "never cache an empty constituent-fetch result". The guard now lives inside
_save_sp500_cache itself, so no caller can bypass it.

Run: python debug/_verify_sp500_cache_guard.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import UniverseBuilder

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    orig = UniverseBuilder._SP500_CACHE
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "sp500.json")
        UniverseBuilder._SP500_CACHE = path
        try:
            good = [f"T{i}" for i in range(503)]
            UniverseBuilder._save_sp500_cache(good)
            check("full_list_written", json.load(open(path)) == good)
            UniverseBuilder._save_sp500_cache([])
            check("empty_list_does_not_overwrite", json.load(open(path)) == good)
            UniverseBuilder._save_sp500_cache([f"T{i}" for i in range(37)])
            check("truncated_list_does_not_overwrite", json.load(open(path)) == good)
        finally:
            UniverseBuilder._SP500_CACHE = orig
    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
