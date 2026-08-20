"""
debug/_verify_universe_loader_memo_cache.py -- synthetic proof for
universe_loader.load_full_universe(use_memo_cache=True), added 2026-08-20
(software optimization audit §6, item 3).

Verifies, against real temp cache directories (not the real project cache --
this test builds its own tiny yfinance-only fixture and monkeypatches
universe_loader's module-level cache-dir constants, same pattern already
used by the other _verify_ scripts that touch universe_loader in this repo):

1. First call with use_memo_cache=True builds and returns correct data, and
   writes a .pkl file under the memo cache dir.
2. Second call with identical arguments returns the SAME data without
   re-reading the source parquet files (proven by deleting a source file
   between calls -- if the second call still succeeds and returns the
   deleted symbol, it came from the memo cache, not a fresh disk read).
3. Changing a source directory (adding a new file) invalidates the cache --
   confirmed by a DIFFERENT cache key/file being written, and the new call
   picking up the added symbol rather than silently returning stale data.
4. use_memo_cache=False (the default) never touches the memo cache dir at
   all -- existing callers are provably unaffected.
"""
import os
import shutil
import sys
import tempfile

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import universe_loader


def _write_symbol(cache_dir, symbol, suffix, n_rows=5):
    os.makedirs(cache_dir, exist_ok=True)
    idx = pd.date_range("2026-01-01", periods=n_rows, freq="D")
    df = pd.DataFrame({"close": range(n_rows)}, index=idx)
    df.to_parquet(os.path.join(cache_dir, f"{symbol}_{suffix}.parquet"))


def main():
    tmp = tempfile.mkdtemp(prefix="camarf_memo_test_")
    passed = 0
    failed = 0
    try:
        yf_dir = os.path.join(tmp, "yf")
        memo_dir = os.path.join(tmp, "memo")
        _write_symbol(yf_dir, "AAA", "1day")
        _write_symbol(yf_dir, "BBB", "1day")

        # Monkeypatch module-level constants so this test never touches the real project cache.
        orig_yf_dir = universe_loader._YF_CACHE_DIR
        orig_memo_dir = universe_loader._MEMO_CACHE_DIR
        universe_loader._YF_CACHE_DIR = yf_dir
        universe_loader._MEMO_CACHE_DIR = memo_dir

        # --- Test 1: first call builds correct data + writes a cache file ---
        result1 = universe_loader.load_full_universe(
            tf_label="1D", include_wrds=False, include_binance=False, include_ibkr=False,
            use_memo_cache=True)
        if set(result1.keys()) == {"AAA", "BBB"}:
            print("PASS: first call returns correct symbols")
            passed += 1
        else:
            print(f"FAIL: first call returned {set(result1.keys())}, expected {{AAA, BBB}}")
            failed += 1

        cache_files = os.listdir(memo_dir) if os.path.isdir(memo_dir) else []
        if len(cache_files) == 1 and cache_files[0].endswith(".pkl"):
            print(f"PASS: exactly one memo cache file written ({cache_files[0]})")
            passed += 1
        else:
            print(f"FAIL: expected exactly one .pkl cache file, found {cache_files}")
            failed += 1

        # --- Test 2: second call (unchanged source dir) reuses the cache and never re-reads
        # disk -- proven by monkeypatching _load_dir to raise if it's called at all.
        def _load_dir_should_not_be_called(*args, **kwargs):
            raise AssertionError("_load_dir was called -- second call did NOT reuse the memo cache")
        orig_load_dir = universe_loader._load_dir
        universe_loader._load_dir = _load_dir_should_not_be_called
        try:
            result2 = universe_loader.load_full_universe(
                tf_label="1D", include_wrds=False, include_binance=False, include_ibkr=False,
                use_memo_cache=True)
            if set(result2.keys()) == {"AAA", "BBB"}:
                print("PASS: second call reused memo cache without touching disk (_load_dir never invoked)")
                passed += 1
            else:
                print(f"FAIL: second call returned {set(result2.keys())}, expected cache reuse with {{AAA, BBB}}")
                failed += 1
        except AssertionError as e:
            print(f"FAIL: {e}")
            failed += 1
        finally:
            universe_loader._load_dir = orig_load_dir

        # --- Test 3: adding a new source file invalidates the cache (different signature) ---
        _write_symbol(yf_dir, "CCC", "1day")
        result3 = universe_loader.load_full_universe(
            tf_label="1D", include_wrds=False, include_binance=False, include_ibkr=False,
            use_memo_cache=True)
        if "CCC" in result3:
            print("PASS: cache correctly invalidated and rebuilt after a new source file was added")
            passed += 1
        else:
            print(f"FAIL: new symbol CCC not picked up after source dir changed, got {set(result3.keys())}")
            failed += 1

        cache_files_after = [f for f in os.listdir(memo_dir) if f.endswith(".pkl")]
        if len(cache_files_after) == 2:
            print("PASS: a second, distinct cache file was written for the changed signature")
            passed += 1
        else:
            print(f"FAIL: expected 2 distinct cache files after signature change, found {len(cache_files_after)}")
            failed += 1

        # --- Test 4: use_memo_cache=False (default) never touches the memo cache dir ---
        shutil.rmtree(memo_dir, ignore_errors=True)
        _ = universe_loader.load_full_universe(
            tf_label="1D", include_wrds=False, include_binance=False, include_ibkr=False)
        if not os.path.isdir(memo_dir):
            print("PASS: default (use_memo_cache=False) never creates the memo cache dir")
            passed += 1
        else:
            print("FAIL: memo cache dir was created even though use_memo_cache defaulted to False")
            failed += 1

    finally:
        universe_loader._YF_CACHE_DIR = orig_yf_dir
        universe_loader._MEMO_CACHE_DIR = orig_memo_dir
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{passed}/{passed + failed} checks passed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
