"""
D15 at load (Ross 2026-10-12; FIX 2026-10-20): the 85 CRSP-labelled WRDS files whose security could not be identified
(wrds_label_permno_final.parquet, permno NaN) were excluded only at the pool step; discovery still loaded them.
Checks (temp caches): load_full_universe drops an unresolved WRDS label and keeps resolved ones and Compustat Global
(GVKEY) files; load_symbol returns None for it (no other source).
"""
import os
import sys
import tempfile

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


import universe_loader as ul  # noqa: E402
from data_wrds import LABEL_PERMNO_MAP_PATH  # noqa: E402

idx = pd.bdate_range("2010-01-04", periods=300)
orig = ul._WRDS_CACHE_DIR
with tempfile.TemporaryDirectory() as td:
    for lab, lvl in (("GOOD", 10.0), ("BADX", 20.0), ("GVKEY000001_01W", 30.0)):
        pd.DataFrame({"close": np.linspace(lvl, lvl + 5, 300), "volume": 1e6,
                      "close_total_return": np.linspace(lvl, lvl + 6, 300)}, index=idx).to_parquet(
            os.path.join(td, f"{lab}_1D.parquet"))
    pd.DataFrame({"label": ["GOOD", "BADX"], "permno": [11111.0, np.nan]}).to_parquet(
        os.path.join(td, os.path.basename(LABEL_PERMNO_MAP_PATH)))
    ul._WRDS_CACHE_DIR = td
    try:
        u = ul.load_full_universe("1D", include_yfinance=False, include_binance=False, use_memo_cache=False,
                                  dedupe=False)
        check("unresolved label dropped at load", "BADX" not in u, f"{sorted(u)}")
        check("resolved and GVKEY labels kept", "GOOD" in u and "GVKEY000001_01W" in u, f"{sorted(u)}")
        s = ul.load_symbol("BADX", "1D", yf_load=lambda s_, t: None)
        check("load_symbol: unresolved label -> None", s is None)
        g = ul.load_symbol("GOOD", "1D", yf_load=lambda s_, t: None)
        check("load_symbol: resolved label loads", g is not None)
    finally:
        ul._WRDS_CACHE_DIR = orig
print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(1 if failed else 0)
