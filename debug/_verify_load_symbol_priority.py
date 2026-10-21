"""
Synthetic check for universe_loader.load_symbol and research/aligned_pair_loader (N15, 2026-10-20).

aligned_pair_loader read the yfinance cache first and fell back to WRDS only when yfinance had nothing, and tried the
IBKR supplement by default -- both against CLAUDE.md rule 2 (WRDS wins every daily-and-coarser collision; IBKR off by
default). load_symbol must apply the same priority and D17 rule as load_full_universe:
  1. 1D label in both caches -> the WRDS total-return series;
  2. Compustat Global file -> close_usd, never the local-currency close;
  3. D17: the WRDS series ended > 1 year before the same-label yfinance series -> the label keeps yfinance, and the
     WRDS series is reachable as PERMNO<n>;
  4. intraday label -> yfinance; IBKR is never read unless include_ibkr=True;
  5. aligned_pair_loader.load_aligned_pair routes through load_symbol.
Run: python debug/_verify_load_symbol_priority.py
"""
import os
import sys
import tempfile

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def frame(start, n, level, extra=None):
    idx = pd.bdate_range(start, periods=n)
    d = {"close": np.full(n, level, float)}
    d.update({k: np.full(n, v, float) for k, v in (extra or {}).items()})
    return pd.DataFrame(d, index=idx)


try:
    import universe_loader as ul
    load_symbol = ul.load_symbol
except Exception as e:  # noqa: BLE001
    print(f"[FAIL] import load_symbol: {type(e).__name__}: {e}\n\n0/1 checks passed")
    sys.exit(1)

with tempfile.TemporaryDirectory() as td:
    wdir = os.path.join(td, "wrds")
    os.makedirs(wdir)
    frame("2010-01-01", 300, 10.0, {"close_total_return": 11.0}).to_parquet(os.path.join(wdir, "AAA_1D.parquet"))
    frame("2010-01-01", 300, 900.0, {"close_usd": 6.0}).to_parquet(os.path.join(wdir, "GVKEY000001_01W_1D.parquet"))
    frame("1996-01-01", 300, 20.0, {"close_total_return": 21.0}).to_parquet(os.path.join(wdir, "VSNT_1D.parquet"))
    yf = {("AAA", "1D"): frame("2010-01-01", 300, 99.0), ("VSNT", "1D"): frame("2025-01-01", 200, 50.0),
          ("BBB", "1h"): frame("2025-01-01", 50, 7.0)}
    ibkr_calls = []

    def yf_load(sym, tf):
        return yf.get((sym, tf))

    def ibkr_load(sym, tf):
        ibkr_calls.append(sym)
        return frame("2025-01-01", 50, 3.0)

    kw = dict(wrds_dir=wdir, permno_of={"AAA": 1, "VSNT": 777}, yf_load=yf_load, ibkr_load=ibkr_load)
    a = load_symbol("AAA", "1D", **kw)
    check("1. WRDS total return wins over yfinance", a is not None and float(a["close"].iloc[0]) == 11.0,
          "" if a is None else str(a["close"].iloc[0]))
    g = load_symbol("GVKEY000001_01W", "1D", **kw)
    check("2. Compustat Global -> close_usd", g is not None and float(g["close"].iloc[0]) == 6.0,
          "" if g is None else str(g["close"].iloc[0]))
    v = load_symbol("VSNT", "1D", **kw)
    check("3a. D17: label keeps the newer yfinance listing", v is not None and float(v["close"].iloc[0]) == 50.0,
          "" if v is None else str(v["close"].iloc[0]))
    p = load_symbol("PERMNO777", "1D", **kw)
    check("3b. D17: old WRDS series reachable as PERMNO<n>", p is not None and float(p["close"].iloc[0]) == 21.0,
          "" if p is None else str(p["close"].iloc[0]))
    b = load_symbol("BBB", "1h", **kw)
    check("4a. intraday -> yfinance", b is not None and float(b["close"].iloc[0]) == 7.0)
    z = load_symbol("ZZZ", "1h", **kw)
    check("4b. IBKR not read by default", z is None and ibkr_calls == [], f"{ibkr_calls}")
    z2 = load_symbol("ZZZ", "1h", include_ibkr=True, **kw)
    check("4c. IBKR only when asked", z2 is not None and ibkr_calls == ["ZZZ"], f"{ibkr_calls}")

import inspect  # noqa: E402

import aligned_pair_loader as apl  # noqa: E402
routes = (hasattr(apl, "_load_one") and "load_symbol(" in inspect.getsource(apl._load_one)
          and "_load_one(" in inspect.getsource(apl.load_aligned_pair)
          and "_load_one(" in inspect.getsource(apl.load_aligned_symbols))
check("5. aligned_pair_loader routes through load_symbol, no direct DataStore/IBKR read",
      routes and not hasattr(apl, "DataStore") and not hasattr(apl, "_load_wrds_or_ibkr"))

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(1 if failed else 0)
