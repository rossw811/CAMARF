"""
Test for plan S35 (Ross 2026-10-10; written before the code): discovery (D18 exclude arm) masks CRSP no-trade days --
close NaN while close_total_return moved, i.e. a bid/ask-midpoint return -- but the pool spreads, built by
research/episodic_pairs_adapter._load_symbol from close_total_return, kept those midpoint values, so the traded hedge
ratio / half-life / z-score used days discovery threw out. Rule (one shared function, data_wrds.crsp_no_trade_mask,
used by both the scan and the adapter): for a non-Compustat (non-GVKEY) WRDS daily file, a day with close NaN and a
total-return value is masked to NaN. Compustat files are not masked (unchanged from the scan's rule).
Checks (temp WRDS dir): a CRSP file with 3 no-trade days -> the adapter's 1D close is NaN on exactly those days and
equal to close_total_return elsewhere; a GVKEY file with a missing close keeps its total-return value; the scan and
the adapter both call the shared function (source check).
Run: python debug/_verify_traded_series_no_trade_mask.py
"""
import os
import shutil
import sys
import tempfile

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    import data_wrds
    if not hasattr(data_wrds, "crsp_no_trade_mask"):
        check("shared_function_exists", False)
    import universe_loader as ul
    import episodic_pairs_adapter as ad
    d = tempfile.mkdtemp(prefix="notrade_")
    old = ul._WRDS_CACHE_DIR
    try:
        idx = pd.bdate_range("2020-01-01", periods=50)
        tr = 100 * np.exp(np.cumsum(np.full(50, 0.001)))
        crsp = pd.DataFrame({"close": tr.copy(), "close_total_return": tr, "volume": 1e6}, index=idx)
        no_trade = [5, 17, 30]
        crsp.iloc[no_trade, 0] = np.nan
        crsp.to_parquet(os.path.join(d, "TESTCRSP_1D.parquet"))
        gv = pd.DataFrame({"close": tr.copy(), "close_total_return": tr, "volume": 1e6}, index=idx)
        gv.iloc[[8], 0] = np.nan
        gv.to_parquet(os.path.join(d, "GVKEY999_01W_1D.parquet"))
        ul._WRDS_CACHE_DIR = d
        out = ad._load_symbol("TESTCRSP", "1D")
        c = out["close"] if out is not None else pd.Series(dtype=float)
        check("crsp_no_trade_days_masked", len(c) and c.iloc[no_trade].isna().all(), c.iloc[no_trade].tolist())
        others = [i for i in range(50) if i not in no_trade]
        check("crsp_other_days_total_return", len(c) and np.allclose(c.iloc[others].to_numpy(), tr[others]))
        g = ad._load_symbol("GVKEY999_01W", "1D")["close"]
        check("gvkey_not_masked", np.isfinite(g.iloc[8]))
    finally:
        ul._WRDS_CACHE_DIR = old
        shutil.rmtree(d, ignore_errors=True)
    for f in ("research/episodic_pairs_adapter.py", "research/wrds_deep_history_episodic_scan.py"):
        check(f"uses_shared_rule:{os.path.basename(f)}",
              "crsp_no_trade_mask(" in open(os.path.join(ROOT, f), encoding="utf-8").read())
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
