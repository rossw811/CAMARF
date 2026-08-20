"""
Synthetic verification of universe_loader.py::load_full_universe -- run
BEFORE trusting it to feed any real candidate-discovery script.

Uses ISOLATED SCRATCH directories, not the real cache directories -- an
earlier version of this test wrote into the real dirs and called
load_full_universe() unmodified, which then scanned the REAL WRDS cache
(44,693 files) on top of the 3 test files, turning a quick synthetic check
into a multi-minute full disk scan (caught directly: the test hung past a
120s timeout with zero output). Monkeypatches the module's cache-directory
constants to point at temp scratch dirs instead, so only the deliberately-
written test files are ever scanned.

REVISED 2026-08-14 (Ross: "i'm fine with using IBKR for the intraday
data") -- IBKR is now a real, included source (default on), not excluded.
Check 5 below tests the CURRENT correct behavior (IBKR symbols ARE loaded,
using its distinct "{symbol}_{suffix}_deep.parquet" filename convention),
not the prior (now superseded) exclusion guarantee.

Checks:
  1. A symbol present ONLY in the yfinance cache is loaded.
  2. A symbol present ONLY in the WRDS cache is loaded.
  3. A symbol present ONLY in the Binance cache is loaded (1D maps to
     Binance's own "1d" suffix).
  4. include_wrds=False / include_binance=False correctly excludes those
     sources' symbols while still including yfinance's.
  5. A symbol present ONLY in the IBKR cache is loaded, using its distinct
     "_deep" filename suffix convention -- AND include_ibkr=False correctly
     excludes it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import shutil
import tempfile

import pandas as pd

import universe_loader
from universe_loader import load_full_universe


def _write(cache_dir, filename, close=100.0):
    os.makedirs(cache_dir, exist_ok=True)
    idx = pd.date_range("2024-01-01", periods=10, freq="D")
    df = pd.DataFrame({"open": close, "high": close, "low": close,
                        "close": close, "volume": 1_000_000}, index=idx)
    path = os.path.join(cache_dir, filename)
    df.to_parquet(path)
    return path


def main():
    failures = []
    scratch_root = tempfile.mkdtemp(prefix="verify_universe_loader_")
    scratch_yf = os.path.join(scratch_root, "yf")
    scratch_wrds = os.path.join(scratch_root, "wrds")
    scratch_binance = os.path.join(scratch_root, "binance")
    scratch_ibkr = os.path.join(scratch_root, "ibkr")

    # Monkeypatch the module's cache-dir constants so load_full_universe only
    # ever sees these isolated scratch dirs, never the real multi-thousand-
    # file caches -- restored in the finally block regardless of outcome.
    orig = (
        universe_loader._YF_CACHE_DIR, universe_loader._WRDS_CACHE_DIR,
        universe_loader._BINANCE_CACHE_DIR, universe_loader._IBKR_CACHE_DIR,
    )
    universe_loader._YF_CACHE_DIR = scratch_yf
    universe_loader._WRDS_CACHE_DIR = scratch_wrds
    universe_loader._BINANCE_CACHE_DIR = scratch_binance
    universe_loader._IBKR_CACHE_DIR = scratch_ibkr

    try:
        _write(scratch_yf, "VERIFYYF_1day.parquet")
        _write(scratch_wrds, "VERIFYWRDS_1D.parquet")
        _write(scratch_binance, "VERIFYBIN_1d.parquet")
        _write(scratch_ibkr, "VERIFYIBKR_1day_deep.parquet")  # real IBKR "_deep" convention

        # --- Checks 1-3: each source's symbol is loaded ---
        merged = load_full_universe("1D")
        if "VERIFYYF" not in merged:
            failures.append("Check 1: yfinance-only symbol VERIFYYF not found in merged universe")
        if "VERIFYWRDS" not in merged:
            failures.append("Check 2: WRDS-only symbol VERIFYWRDS not found in merged universe")
        if "VERIFYBIN" not in merged:
            failures.append("Check 3: Binance-only symbol VERIFYBIN not found in merged universe")

        # --- Check 4: selective source exclusion ---
        yf_only = load_full_universe("1D", include_wrds=False, include_binance=False,
                                      include_ibkr=False)
        if "VERIFYYF" not in yf_only:
            failures.append("Check 4: yfinance symbol should still be present with other sources off")
        if "VERIFYWRDS" in yf_only or "VERIFYBIN" in yf_only or "VERIFYIBKR" in yf_only:
            failures.append(f"Check 4: WRDS/Binance/IBKR symbols should be EXCLUDED when their "
                             f"flags are False, got keys: {list(yf_only.keys())}")

        # --- Check 5: IBKR symbol loaded by default, correctly using its "_deep" filename
        # convention (a different naming pattern from every other source) ---
        if "VERIFYIBKR" not in merged:
            failures.append(f"Check 5: IBKR-only symbol VERIFYIBKR not found in merged universe "
                             f"(default include_ibkr=True) -- got keys: {list(merged.keys())}")
        ibkr_off = load_full_universe("1D", include_ibkr=False)
        if "VERIFYIBKR" in ibkr_off:
            failures.append("Check 5b: include_ibkr=False should exclude the IBKR symbol, "
                             "but it was still present")
    finally:
        universe_loader._YF_CACHE_DIR, universe_loader._WRDS_CACHE_DIR, \
            universe_loader._BINANCE_CACHE_DIR, universe_loader._IBKR_CACHE_DIR = orig
        shutil.rmtree(scratch_root, ignore_errors=True)

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All universe_loader checks passed.")
    print(f"  Checks 1-3: yfinance/WRDS/Binance symbols all correctly merged")
    print(f"  Check 4: selective source exclusion works")
    print(f"  Check 5: IBKR symbol loaded by default (correct '_deep' filename handling), "
          f"correctly excluded with include_ibkr=False")


if __name__ == "__main__":
    main()
