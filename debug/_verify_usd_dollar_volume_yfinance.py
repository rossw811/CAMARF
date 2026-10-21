"""
W5.6b (2026-10-20): analysis.py's ADV gate (_compute_adv) and sensitivity.py multiplied yfinance `close` by volume and
compared it with a USD threshold. yfinance non-US equities are quoted in local currency (.T JPY, .HK HKD) and London in
pence (.L: GBp, 1/100 GBP) -- ~88 such symbols in the cache. Checks for dollar_volume.usd_dollar_volume(df, symbol):
  1. a US symbol is unchanged (|close| x volume);
  2. .T / .HK use the cached daily FX rate as of each date (backward as-of, never a later rate);
  3. .L converts pence to pounds, then GBP to USD;
  4. an unknown non-US suffix or a missing FX series -> NaN (excluded, never guessed);
  5. close_usd still wins when present (Compustat Global);
  6. analysis._compute_adv and sensitivity.py route through usd_dollar_volume with the symbol (source check).
"""
import inspect
import os
import sys

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


import dollar_volume as dv  # noqa: E402

idx = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])
df = pd.DataFrame({"close": [100.0, 200.0, 300.0], "volume": [10.0, 10.0, 10.0]}, index=idx)
fx = {"JPY": pd.Series([0.01, 0.02], index=pd.to_datetime(["2025-01-02", "2025-01-06"])),
      "HKD": pd.Series([0.1], index=pd.to_datetime(["2025-01-01"])),
      "GBP": pd.Series([1.25], index=pd.to_datetime(["2025-01-01"]))}
try:
    load = lambda c: fx.get(c)  # noqa: E731
    us = dv.usd_dollar_volume(df, "AAPL", fx_loader=load)
    check("1. US symbol unchanged", list(us) == [1000.0, 2000.0, 3000.0], str(list(us)))
    jp = dv.usd_dollar_volume(df, "7203.T", fx_loader=load)
    check("2a. .T as-of FX (01-03 uses 01-02's rate, not 01-06's)", np.allclose(jp, [10.0, 20.0, 60.0]), str(list(jp)))
    hk = dv.usd_dollar_volume(df, "0005.HK", fx_loader=load)
    check("2b. .HK", np.allclose(hk, [100.0, 200.0, 300.0]), str(list(hk)))
    uk = dv.usd_dollar_volume(df, "HSBA.L", fx_loader=load)
    check("3. .L pence -> GBP -> USD", np.allclose(uk, [12.5, 25.0, 37.5]), str(list(uk)))
    xx = dv.usd_dollar_volume(df, "FOO.ZZ", fx_loader=load)
    check("4a. unknown suffix -> NaN", xx.isna().all(), str(list(xx)))
    nofx = dv.usd_dollar_volume(df, "7203.T", fx_loader=lambda c: None)
    check("4b. missing FX -> NaN", nofx.isna().all(), str(list(nofx)))
    cu = dv.usd_dollar_volume(df.assign(close_usd=[1.0, 1.0, 1.0]), "GVKEY000001_01W", fx_loader=load)
    check("5. close_usd wins", list(cu) == [10.0, 10.0, 10.0], str(list(cu)))
    check("1b. crypto / FX-style tickers are not treated as non-US equities",
          list(dv.usd_dollar_volume(df, "BTC-USD", fx_loader=load)) == [1000.0, 2000.0, 3000.0])
except TypeError as e:
    check("usd_dollar_volume takes a symbol", False, f"{type(e).__name__}: {e}")

import analysis  # noqa: E402
src_a = inspect.getsource(analysis)
i = src_a.find("def _compute_adv(")
check("6a. analysis._compute_adv uses usd_dollar_volume(_df, sym)", i >= 0 and
      "usd_dollar_volume(_df, sym" in src_a[i:i + 1500], "")
src_s = open(os.path.join(ROOT, "sensitivity.py"), encoding="utf-8").read()
check("6b. sensitivity.py uses usd_dollar_volume(hr, sym)", "usd_dollar_volume(hr, sym" in src_s)

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(1 if failed else 0)
