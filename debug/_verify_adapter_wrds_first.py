"""
Regression test (2026-09-27, Ross: "prioritize wrds over yfinance"; code review R1.4): the episodic pairs
adapter's _load_symbol tried the yfinance cache FIRST for plain tickers, so the traded spread for US pairs was
built from yfinance adjusted closes while discovery (Tier-3 scan) tested CRSP close_total_return. Now, for
daily-and-coarser TFs, a WRDS file wins and its close_total_return is used as `close`; yfinance is only a
fallback for symbols WRDS does not cover.
Run: python debug/_verify_adapter_wrds_first.py
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import universe_loader as ul
from config import Config
from data import DataStore
from research import episodic_pairs_adapter as ad

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    root = tempfile.mkdtemp(prefix="verify_adapter_wrds_first_")
    wrds_dir, yf_dir = os.path.join(root, "wrds"), os.path.join(root, "yf")
    os.makedirs(wrds_dir); os.makedirs(yf_dir)
    orig = (ul._WRDS_CACHE_DIR, Config.DATA.CACHE_DIR)
    ul._WRDS_CACHE_DIR, Config.DATA.CACHE_DIR = wrds_dir, yf_dir
    try:
        idx = pd.date_range("2024-01-01", periods=80, freq="D")
        pd.DataFrame({"open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "close_total_return": 12.5,
                      "volume": 1e6}, index=idx).to_parquet(os.path.join(wrds_dir, "BOTH_1D.parquet"))
        yf = pd.DataFrame({"open": 9.0, "high": 9.0, "low": 9.0, "close": 9.0, "volume": 1e6}, index=idx)
        DataStore.save("BOTH", "1D", yf)
        DataStore.save("YFONLY", "1D", yf)
        a = ad._load_symbol("BOTH", "1D")
        check("wrds_first_total_return", a is not None and float(a["close"].iloc[0]) == 12.5,
              f"close={None if a is None else a['close'].iloc[0]}")
        # WRDS files use pandas NULLABLE dtypes (pd.NA): VolumeStructure raised "boolean value of NA is
        # ambiguous" on 1,670 real leg loads, so the squeeze/momentum gate silently failed closed (2026-09-27).
        nl = pd.DataFrame({"open": pd.array([10.0] * 79 + [None], dtype="Float64"),
                           "high": pd.array([10.0] * 80, dtype="Float64"), "low": pd.array([10.0] * 80, dtype="Float64"),
                           "close": pd.array([10.0] * 80, dtype="Float64"),
                           "close_total_return": pd.array([12.0] * 79 + [None], dtype="Float64"),
                           "volume": pd.array([1] * 80, dtype="Int64")}, index=idx)
        nl.to_parquet(os.path.join(wrds_dir, "NULLABLE_1D.parquet"))
        n = ad._load_symbol("NULLABLE", "1D")
        check("nullable_dtypes_become_float64", n is not None and all(str(d) == "float64" for d in n.dtypes)
              and not any(v is pd.NA for v in n["close"].tolist()), f"dtypes={None if n is None else n.dtypes.to_dict()}")
        pd.DataFrame({"open": 1500.0, "high": 1500.0, "low": 1500.0, "close": 1500.0, "close_usd": 10.0,
                      "volume": 1e6}, index=idx).to_parquet(os.path.join(wrds_dir, "GVKEY000009_01W_1D.parquet"))
        g = ad._load_symbol("GVKEY000009_01W", "1D")
        check("close_usd_used_for_global", g is not None and float(g["close"].iloc[0]) == 10.0,
              f"close={None if g is None else g['close'].iloc[0]}")
        b = ad._load_symbol("YFONLY", "1D")
        check("yfinance_fallback", b is not None and float(b["close"].iloc[0]) == 9.0,
              f"close={None if b is None else b['close'].iloc[0]}")
    finally:
        ul._WRDS_CACHE_DIR, Config.DATA.CACHE_DIR = orig
        shutil.rmtree(root, ignore_errors=True)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
