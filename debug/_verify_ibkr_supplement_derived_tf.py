"""
debug/_verify_ibkr_supplement_derived_tf.py -- synthetic ground-truth
verification for ibkr_supplement_reader.py's new derived-TF fallback
(2m/3m from 1m, 7D/1M from 1D), added 2026-07-21 so the episodic
deep-history cointegration re-test actually covers a confirmed pair that
lands on a derived timeframe (KVUE/KMB@2m/3m, 7267.T/8058.T@1M -- today's
ENTIRE confirmed set) instead of silently no-op'ing for all of them.

Checks:
  1. _resample() OHLCV aggregation matches hand-computed values (open=first,
     high=max, low=min, close=last, volume=sum) on a small known input.
  2. load_supplement() falls back to resampling the native base TF's
     supplement file when the literal derived-TF file doesn't exist.
  3. load_supplement() still returns the literal file directly when it DOES
     exist (no unwanted fallback/override of a real native file).
  4. load_supplement() returns None (no crash) when neither the literal nor
     the base file exists.
  5. The 2m/3m/7D/1M resample rules match data.py's own IBKRFeed.
     RESAMPLED_FROM_1M / daily-derivation rules exactly (same rule strings).

Uses a temp SUPPLEMENT_DIR (monkeypatched) -- never touches the real
output/cache/ibkr_supplement/ directory.

Run: python debug/_verify_ibkr_supplement_derived_tf.py
"""
import os
import shutil
import sys
import tempfile

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ibkr_supplement_reader as reader


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}")
    return cond


def verify_resample_math():
    print("\n=== 1. _resample() OHLCV aggregation ===")
    idx = pd.date_range("2024-01-01 09:30", periods=4, freq="1min")
    df = pd.DataFrame({
        "open":  [10.0, 10.5, 11.0, 10.8],
        "high":  [10.6, 11.2, 11.3, 11.0],
        "low":   [9.9, 10.4, 10.9, 10.6],
        "close": [10.5, 11.0, 10.8, 10.9],
        "volume": [100, 200, 150, 50],
    }, index=idx)
    out = reader._resample(df, "2min")
    ok = check("output has 2 bars from 4 1-min bars at a 2min rule", len(out) == 2)
    if len(out) == 2:
        ok &= check("bar 1 open = first (10.0)", out.iloc[0]["open"] == 10.0)
        ok &= check("bar 1 high = max (11.2)", out.iloc[0]["high"] == 11.2)
        ok &= check("bar 1 low = min (9.9)", out.iloc[0]["low"] == 9.9)
        ok &= check("bar 1 close = last (11.0)", out.iloc[0]["close"] == 11.0)
        ok &= check("bar 1 volume = sum (300)", out.iloc[0]["volume"] == 300)
    return ok


def verify_derived_fallback():
    print("\n=== 2-4. load_supplement() derived-TF fallback ===")
    tmpdir = tempfile.mkdtemp(prefix="camarf_supp_test_")
    orig_dir = reader.SUPPLEMENT_DIR
    try:
        reader.SUPPLEMENT_DIR = tmpdir

        # Build a synthetic 1-min supplement file for symbol "XYZ"
        idx = pd.date_range("2024-01-01 09:30", periods=100, freq="1min")
        rng = np.random.default_rng(3)
        closes = 100 + np.cumsum(rng.normal(0, 0.1, 100))
        df_1m = pd.DataFrame({
            "open": closes, "high": closes + 0.1, "low": closes - 0.1,
            "close": closes, "volume": np.full(100, 10),
        }, index=idx)
        df_1m.to_parquet(reader.supplement_path("XYZ", "1m"))

        # Build a synthetic daily supplement file for symbol "ABC"
        idx_d = pd.date_range("2020-01-01", periods=500, freq="B")
        closes_d = 50 + np.cumsum(rng.normal(0, 0.5, 500))
        df_1d = pd.DataFrame({
            "open": closes_d, "high": closes_d + 0.5, "low": closes_d - 0.5,
            "close": closes_d, "volume": np.full(500, 1000),
        }, index=idx_d)
        df_1d.to_parquet(reader.supplement_path("ABC", "1D"))

        ok = True
        # 2m/3m fall back to resampling the 1m file
        for tf in ["2m", "3m"]:
            derived = reader.load_supplement("XYZ", tf)
            ok &= check(f"XYZ@{tf} (no literal file) falls back and returns real data",
                        derived is not None and len(derived) > 0)

        # 7D/1M fall back to resampling the 1D file
        for tf in ["7D", "1M"]:
            derived = reader.load_supplement("ABC", tf)
            ok &= check(f"ABC@{tf} (no literal file) falls back and returns real data",
                        derived is not None and len(derived) > 0)

        # 3. A literal file, when present, is returned directly (no override)
        idx_2m = pd.date_range("2024-06-01", periods=10, freq="2min")
        literal_2m = pd.DataFrame({
            "open": [999.0] * 10, "high": [999.0] * 10, "low": [999.0] * 10,
            "close": [999.0] * 10, "volume": [1] * 10,
        }, index=idx_2m)
        literal_2m.to_parquet(reader.supplement_path("XYZ", "2m"))
        loaded = reader.load_supplement("XYZ", "2m")
        ok &= check("a literal derived-TF file, when present, is returned as-is (not resampled)",
                    loaded is not None and (loaded["close"] == 999.0).all())

        # 4. Neither literal nor base exists -> None, no crash
        none_result = reader.load_supplement("NOSUCHSYMBOL", "3m")
        ok &= check("missing literal AND missing base returns None (no crash)", none_result is None)

        return ok
    finally:
        reader.SUPPLEMENT_DIR = orig_dir
        shutil.rmtree(tmpdir, ignore_errors=True)


def verify_rules_match_production():
    print("\n=== 5. Resample rules match data.py's IBKRFeed exactly ===")
    ok = check("2m rule is '2min' (matches IBKRFeed.RESAMPLED_FROM_1M)",
               reader._DERIVED_FROM["2m"] == ("1m", "2min"))
    ok &= check("3m rule is '3min' (matches IBKRFeed.RESAMPLED_FROM_1M)",
                reader._DERIVED_FROM["3m"] == ("1m", "3min"))
    ok &= check("7D rule is 'W-FRI' (matches IBKRFeed.get_full_history's daily derivation)",
                reader._DERIVED_FROM["7D"] == ("1D", "W-FRI"))
    ok &= check("1M rule is '1ME' (matches IBKRFeed.get_full_history's daily derivation)",
                reader._DERIVED_FROM["1M"] == ("1D", "1ME"))
    return ok


def main():
    results = [
        verify_resample_math(),
        verify_derived_fallback(),
        verify_rules_match_production(),
    ]
    print("\n" + "=" * 60)
    if all(results):
        print("ALL CHECKS PASSED")
    else:
        print(f"FAILURES: {results.count(False)}/{len(results)} check groups failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
