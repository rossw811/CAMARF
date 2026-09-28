"""
Regression test for code-review finding U4 (2026-09-26): universe_loader read WRDS price-only `close` (callers pass
columns=["close"]), while the discovery scan tested CRSP close_total_return -- so loader consumers saw ex-dividend
drops and a yield-sized drift between high- and low-dividend legs. Also normalises WRDS nullable dtypes (pd.NA),
which broke downstream numpy code (the squeeze/momentum feature failure found 2026-09-27).
Checks, through load_full_universe:
  1. WRDS file with close_total_return -> `close` IS the total-return series, with and without columns=["close"];
  2. WRDS file without that column -> plain close;
  3. output dtype float64, no pd.NA.
Run: python debug/_verify_loader_wrds_total_return.py
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import universe_loader as ul

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    root = tempfile.mkdtemp(prefix="verify_loader_tr_")
    d = {k: os.path.join(root, k) for k in ("yf", "wrds", "bin", "ibkr", "memo")}
    for v in d.values():
        os.makedirs(v)
    orig = (ul._YF_CACHE_DIR, ul._WRDS_CACHE_DIR, ul._BINANCE_CACHE_DIR, ul._IBKR_CACHE_DIR, ul._MEMO_CACHE_DIR)
    ul._YF_CACHE_DIR, ul._WRDS_CACHE_DIR, ul._BINANCE_CACHE_DIR, ul._IBKR_CACHE_DIR, ul._MEMO_CACHE_DIR = (
        d["yf"], d["wrds"], d["bin"], d["ibkr"], d["memo"])
    try:
        idx = pd.date_range("2024-01-01", periods=80, freq="D")
        pd.DataFrame({"close": pd.array([10.0] * 79 + [None], dtype="Float64"),
                      "close_total_return": pd.array([12.0 + i * 0.01 for i in range(80)], dtype="Float64"),
                      "volume": pd.array([1] * 80, dtype="Int64")}, index=idx).to_parquet(os.path.join(d["wrds"], "TR_1D.parquet"))
        pd.DataFrame({"close": [20.0 + i * 0.02 for i in range(80)], "volume": 1.0}, index=idx).to_parquet(
            os.path.join(d["wrds"], "NOTR_1D.parquet"))
        for cols in (None, ["close"]):
            m = ul.load_full_universe("1D", columns=cols, use_memo_cache=False, dedupe=False)
            check(f"total_return_used(columns={cols})", abs(float(m["TR"]["close"].iloc[0]) - 12.0) < 1e-12,
                  f"close={m['TR']['close'].iloc[0]}")
            check(f"no_tr_column_uses_close(columns={cols})", abs(float(m["NOTR"]["close"].iloc[0]) - 20.0) < 1e-12)
            check(f"float64(columns={cols})", str(m["TR"]["close"].dtype) == "float64", f"{m['TR']['close'].dtype}")
    finally:
        ul._YF_CACHE_DIR, ul._WRDS_CACHE_DIR, ul._BINANCE_CACHE_DIR, ul._IBKR_CACHE_DIR, ul._MEMO_CACHE_DIR = orig
        shutil.rmtree(root, ignore_errors=True)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
