"""
Regression test for the 2026-09-27 source-priority decision (Ross: "let's priority wrds over ibkr"; code
review U5/U6). load_full_universe() previously let IBKR override WRDS on a symbol collision (IBKR loaded last)
and loaded IBKR by default -- and IBKR deep history exists only for previously CONFIRMED pairs' symbols, so
data depth and source depended on earlier results. Now:
  1. on a collision WRDS wins over IBKR, Binance and yfinance;
  2. include_ibkr defaults to False (IBKR deep = a pre-declared side arm only);
  3. include_ibkr=True still loads IBKR-only symbols, but WRDS still wins collisions;
  4. the memo-cache key carries a loader-version token, so a memo built under the old priority is never
     served back.
Run: python debug/_verify_wrds_priority_over_ibkr.py
"""
import os
import sys
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import universe_loader as ul

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def _w(d, fn, close):
    os.makedirs(d, exist_ok=True)
    idx = pd.date_range("2024-01-01", periods=10, freq="D")
    pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": 1e6}, index=idx).to_parquet(os.path.join(d, fn))


def main():
    root = tempfile.mkdtemp(prefix="verify_wrds_priority_")
    dirs = {k: os.path.join(root, k) for k in ("yf", "wrds", "bin", "ibkr", "memo")}
    orig = (ul._YF_CACHE_DIR, ul._WRDS_CACHE_DIR, ul._BINANCE_CACHE_DIR, ul._IBKR_CACHE_DIR, ul._MEMO_CACHE_DIR)
    ul._YF_CACHE_DIR, ul._WRDS_CACHE_DIR, ul._BINANCE_CACHE_DIR, ul._IBKR_CACHE_DIR, ul._MEMO_CACHE_DIR = (
        dirs["yf"], dirs["wrds"], dirs["bin"], dirs["ibkr"], dirs["memo"])
    try:
        _w(dirs["yf"], "SHARED_1day.parquet", 1.0)
        _w(dirs["wrds"], "SHARED_1D.parquet", 2.0)
        _w(dirs["ibkr"], "SHARED_1day_deep.parquet", 3.0)
        _w(dirs["ibkr"], "IBKRONLY_1day_deep.parquet", 4.0)
        m = ul.load_full_universe("1D", use_memo_cache=False)
        check("default.wrds_wins_collision", float(m["SHARED"]["close"].iloc[0]) == 2.0, f"close={m['SHARED']['close'].iloc[0]}")
        check("default.ibkr_excluded", "IBKRONLY" not in m, f"keys={sorted(m)}")
        m2 = ul.load_full_universe("1D", include_ibkr=True, use_memo_cache=False)
        check("ibkr_arm.ibkr_only_symbol_loaded", "IBKRONLY" in m2)
        check("ibkr_arm.wrds_still_wins", float(m2["SHARED"]["close"].iloc[0]) == 2.0, f"close={m2['SHARED']['close'].iloc[0]}")
        p = ul._memo_cache_path("1D", True, True, True, False, None)
        check("memo_key_has_version", ul._LOADER_VERSION in repr(ul._memo_signature("1D", True, True, True, False, None)), p)
    finally:
        ul._YF_CACHE_DIR, ul._WRDS_CACHE_DIR, ul._BINANCE_CACHE_DIR, ul._IBKR_CACHE_DIR, ul._MEMO_CACHE_DIR = orig
        shutil.rmtree(root, ignore_errors=True)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
