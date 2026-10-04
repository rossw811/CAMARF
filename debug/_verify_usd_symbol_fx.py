"""
Regression test (2026-10-03, found while building intraday dollar marking): pnl_dollar.is_usd_symbol treated every
yfinance forex ticker as USD. yfinance quotes "EURUSD=X" in USD (dollars per euro) but "JPY=X" (= USD/JPY) and
"GBPJPY=X" in yen, so a dollar P&L computed from those prices was in the wrong currency. Rule: an "=X" ticker is USD
only when its quote currency (the last three letters before "=X") is USD.
Checks: EURUSD=X, GBPUSD=X USD; JPY=X, GBPJPY=X, EURGBP=X, CAD=X not USD; unchanged: AAPL, BRK.B, BTC-USD, ES=F USD;
7203.T and GVKEY... not USD.
Run: python debug/_verify_usd_symbol_fx.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pnl_dollar import is_usd_symbol

cases = {"EURUSD=X": True, "GBPUSD=X": True, "JPY=X": False, "GBPJPY=X": False, "EURGBP=X": False, "CAD=X": False,
         "AAPL": True, "BRK.B": True, "BTC-USD": True, "ES=F": True, "7203.T": False, "GVKEY001234_01W": False}
fails = [(s, exp, is_usd_symbol(s)) for s, exp in cases.items() if is_usd_symbol(s) != exp]
for s, exp in cases.items():
    print(f"[{'PASS' if is_usd_symbol(s) == exp else 'FAIL'}] {s}: expected usd={exp} got {is_usd_symbol(s)}")
print(); print(f"{len(cases) - len(fails)}/{len(cases)} checks passed")
if fails:
    print("FAILED:", fails); sys.exit(1)
