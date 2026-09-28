"""
Regression test for code-review finding D17 (loader part, 2026-09-27): CRSP data ends 2025-12-31, so a company listed
after that (VSNT = Versant's 2026 spin) is only in yfinance, while WRDS's VSNT label legitimately holds the old Versant
(1996-2012). load_full_universe merges WRDS last and WRDS wins every label collision, so the dead company replaced the
live one. Fix: when the WRDS series for a label ENDS before the yfinance series under the same label BEGINS, they are
different securities -- yfinance keeps the label, the WRDS series is kept under its PERMNO<n> label (label map), so
neither is lost. Overlapping series are unchanged (WRDS priority, as before).
Checks (temp cache dirs + temp label map):
  1. time-disjoint: "VSNT" is the yfinance series and "PERMNO83808" the WRDS one;
  2. overlapping same-label series: WRDS still wins (unchanged priority);
  3. a WRDS label with no yfinance twin is untouched;
  4. a delisted WRDS series that OVERLAPS a current yfinance series in time but ends > 1 year before it (e.g. P =
     Pandora to 2019 vs today's P) is also split -- a delisted security cannot still be trading.
Run: python debug/_verify_loader_disjoint_sources.py
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
    root = tempfile.mkdtemp(prefix="verify_d17_loader_")
    d = {k: os.path.join(root, k) for k in ("yf", "wrds", "bin", "ibkr", "memo")}
    for v in d.values():
        os.makedirs(v)
    orig = (ul._YF_CACHE_DIR, ul._WRDS_CACHE_DIR, ul._BINANCE_CACHE_DIR, ul._IBKR_CACHE_DIR, ul._MEMO_CACHE_DIR)
    ul._YF_CACHE_DIR, ul._WRDS_CACHE_DIR, ul._BINANCE_CACHE_DIR, ul._IBKR_CACHE_DIR, ul._MEMO_CACHE_DIR = (
        d["yf"], d["wrds"], d["bin"], d["ibkr"], d["memo"])
    try:
        old = pd.bdate_range("2010-01-04", periods=300)
        new = pd.bdate_range("2026-01-05", periods=150)
        pd.DataFrame({"close": 50.0, "volume": 1.0}, index=new).to_parquet(os.path.join(d["yf"], "VSNT_1day.parquet"))
        pd.DataFrame({"close": 7.0, "volume": 1.0}, index=old).to_parquet(os.path.join(d["wrds"], "VSNT_1D.parquet"))
        both = pd.bdate_range("2024-01-02", periods=200)
        pd.DataFrame({"close": 10.0, "volume": 1.0}, index=both).to_parquet(os.path.join(d["yf"], "OVL_1day.parquet"))
        pd.DataFrame({"close": 11.0, "volume": 1.0}, index=both).to_parquet(os.path.join(d["wrds"], "OVL_1D.parquet"))
        pd.DataFrame({"close": 3.0, "volume": 1.0}, index=old).to_parquet(os.path.join(d["wrds"], "ONLY_1D.parquet"))
        dead = pd.bdate_range("2011-06-15", "2019-01-31")
        live = pd.bdate_range("2015-01-02", "2026-09-25")
        pd.DataFrame({"close": 4.0, "volume": 1.0}, index=dead).to_parquet(os.path.join(d["wrds"], "P_1D.parquet"))
        pd.DataFrame({"close": 40.0, "volume": 1.0}, index=live).to_parquet(os.path.join(d["yf"], "P_1day.parquet"))
        pd.DataFrame({"label": ["VSNT", "OVL", "ONLY", "P"], "permno": [83808, 11111, 22222, 12873]}).to_parquet(
            os.path.join(d["wrds"], "full_us_market_label_map.parquet"))
        m = ul.load_full_universe("1D", use_memo_cache=False, dedupe=False)
        check("disjoint_split", "VSNT" in m and float(m["VSNT"]["close"].dropna().iloc[0]) == 50.0
              and "PERMNO83808" in m and float(m["PERMNO83808"]["close"].dropna().iloc[0]) == 7.0, f"keys={sorted(m)}")
        check("overlap_wrds_priority", float(m["OVL"]["close"].dropna().iloc[0]) == 11.0 and "PERMNO11111" not in m)
        check("wrds_only_untouched", "ONLY" in m and "PERMNO22222" not in m)
        check("overlapping_dead_split", float(m["P"]["close"].dropna().iloc[-1]) == 40.0 and "PERMNO12873" in m,
              f"P last={m['P']['close'].dropna().iloc[-1]} keys={sorted(m)}")
    finally:
        ul._YF_CACHE_DIR, ul._WRDS_CACHE_DIR, ul._BINANCE_CACHE_DIR, ul._IBKR_CACHE_DIR, ul._MEMO_CACHE_DIR = orig
        shutil.rmtree(root, ignore_errors=True)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
