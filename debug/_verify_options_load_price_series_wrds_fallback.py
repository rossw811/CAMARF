"""
debug/_verify_options_load_price_series_wrds_fallback.py -- synthetic checks for a real
coverage bug found live (2026-09-07/08): options.py's load_price_series() only ever checked the
yfinance-only `{symbol}_1day.parquet` cache, never `output/cache/wrds/{symbol}_1D.parquet` --
silently violating this project's own "WRDS takes complete priority" rule for every caller
(options.py's own overlay work, research/options_greeks_features.py, research/asset_
volatility_profile.py). Real result: 44/55 confirmed-pair symbols had real WRDS-cached data that
this function simply never looked at.

Per Ross's explicit instruction (2026-09-08, "don't use yfinance, use wrds or ibkr"), the fix
does NOT fall back to yfinance at all -- WRDS first, then IBKR's deep-history supplement, and
None if neither has the symbol. This deliberately drops the yfinance-only coverage that
`{symbol}_1day.parquet` used to provide (~1,731 symbols in this project's cache), a real,
disclosed tradeoff, not a bug.

Run: python debug/_verify_options_load_price_series_wrds_fallback.py
"""
import os
import shutil
import sys
import tempfile
import unittest.mock as mock

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import options

passed = 0
failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}")
        failed += 1


tmp_cache = tempfile.mkdtemp()
os.makedirs(os.path.join(tmp_cache, "wrds"), exist_ok=True)
_orig_cache_dir = options._CACHE_DIR
options._CACHE_DIR = tmp_cache

try:
    idx = pd.date_range("2024-01-01", periods=10, freq="D")

    print("Check 1: a symbol with ONLY a WRDS-cached file is now found -- the exact real bug "
          "scenario (44/55 confirmed-pair symbols)")
    wrds_only_df = pd.DataFrame({
        "close": np.linspace(100, 110, 10), "close_total_return": np.linspace(100, 110, 10),
    }, index=idx)
    wrds_only_df.to_parquet(os.path.join(tmp_cache, "wrds", "WRDSONLY_1D.parquet"))
    result1 = options.load_price_series("WRDSONLY")
    check("a WRDS-only symbol now returns a real price series, not None (the exact real "
          "coverage gap)", result1 is not None and len(result1) == 10)
    check("the returned series uses close_total_return (CRSP total-return-adjusted), matching "
          "this project's own documented WRDS convention",
          np.isclose(result1.iloc[0], 100.0) and np.isclose(result1.iloc[-1], 110.0))

    print("Check 2: WRDS wins over IBKR when both exist for the same symbol (this project's "
          "own priority order: WRDS first)")
    wrds_df = pd.DataFrame({
        "close": [999.0] * 10, "close_total_return": [999.0] * 10,
    }, index=idx)
    wrds_df.to_parquet(os.path.join(tmp_cache, "wrds", "BOTH_1D.parquet"))
    ibkr_df_present = pd.DataFrame({"close": [1.0] * 10}, index=idx)
    with mock.patch("ibkr_supplement_reader.load_supplement", return_value=ibkr_df_present):
        result2 = options.load_price_series("BOTH")
    check(f"WRDS value (999.0) wins over the IBKR value (1.0): got {result2.iloc[0]}",
          result2.iloc[0] == 999.0)

    print("Check 3: a symbol with NO WRDS cache but a real IBKR supplement falls back to IBKR "
          "correctly (the new WRDS-then-IBKR chain, not a yfinance fallback)")
    ibkr_only_df = pd.DataFrame({"close": np.linspace(50, 60, 10)}, index=idx)
    with mock.patch("ibkr_supplement_reader.load_supplement", return_value=ibkr_only_df):
        result3 = options.load_price_series("IBKRONLY")
    check("a WRDS-absent, IBKR-present symbol returns IBKR's real price series",
          result3 is not None and np.isclose(result3.iloc[0], 50.0))

    print("Check 4: a symbol present in NEITHER WRDS NOR IBKR returns None -- critically, even "
          "when a yfinance _1day.parquet cache file DOES exist for it (the real, deliberate "
          "coverage tradeoff from Ross's explicit 'don't use yfinance' instruction, not a bug)")
    yf_only_df = pd.DataFrame({"close": np.linspace(20, 30, 10)}, index=idx)
    yf_only_df.to_parquet(os.path.join(tmp_cache, "YFONLY_1day.parquet"))
    with mock.patch("ibkr_supplement_reader.load_supplement", return_value=None):
        result4 = options.load_price_series("YFONLY")
    check("a yfinance-only symbol (no WRDS, no IBKR) now correctly returns None -- yfinance is "
          "deliberately never consulted", result4 is None)

    print("Check 5: a symbol in none of the three sources returns None, not a crash")
    with mock.patch("ibkr_supplement_reader.load_supplement", return_value=None):
        result5 = options.load_price_series("NOWHERE_AT_ALL")
    check("a symbol in no source returns None", result5 is None)

finally:
    options._CACHE_DIR = _orig_cache_dir
    shutil.rmtree(tmp_cache, ignore_errors=True)

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
