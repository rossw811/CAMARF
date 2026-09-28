"""
Synthetic check for research/apply_trfd_total_return.py (2026-09-28). Compustat Global legs were price-only while CRSP
legs are total return -- an accounting asymmetry in every mixed pair. Compustat's `trfd` was verified on real data
(HSBC/Toyota/BP 2024-25: prccd/ajexdi*trfd adds exactly div/prev_close on every ex-dividend day, identical to the
price return to 2e-16 on all other days, and includes HSBC's 2024-05 special dividend the divd field omits).
Checks:
  1. on the ex-dividend day the TR return = price return + dividend / previous close (USD, FX constant);
  2. identical to the price return on every other day; level starts equal to close_usd;
  3. trfd dates missing from the price file are carried as-of (never looked up forward);
  4. pnl_dollar.load_daily_prices uses close_usd as the price level and close_total_return for RETURNS
     (it used close_usd for both before, so a Compustat leg's dividends never reached the P&L).
Run: python debug/_verify_trfd_total_return.py
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

import numpy as np
import pandas as pd

from apply_trfd_total_return import total_return_usd

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    idx = pd.bdate_range("2024-01-01", periods=30)
    px = pd.Series(np.linspace(10.0, 11.0, 30), index=idx)
    k, div = 15, 0.30
    px.iloc[k:] -= div
    usd = px * 1.25
    trfd = pd.Series(1.0, index=idx)
    trfd.iloc[k:] = 1.0 + div / px.iloc[k]
    tr = total_return_usd(usd, trfd.drop(idx[[3, 20]]))
    rp, rt = usd.pct_change(), tr.pct_change()
    exp = rp.iloc[k] + div / px.iloc[k - 1]
    check("exdiv_extra_return", abs(rt.iloc[k] - exp) < 1e-12, f"tr_ret={rt.iloc[k]:.6f} expected={exp:.6f}")
    others = (rt - rp).drop(idx[[0, k]])
    check("other_days_identical", float(others.abs().max()) < 1e-12 and abs(tr.iloc[0] - usd.iloc[0]) < 1e-12)
    check("missing_trfd_carried_asof", bool(tr.notna().all()))

    import pnl_dollar
    root = tempfile.mkdtemp(prefix="verify_trfd_")
    orig = pnl_dollar._WRDS_DIR
    pnl_dollar._WRDS_DIR = root
    pnl_dollar._cache.clear()
    try:
        pd.DataFrame({"close": px, "close_usd": usd, "close_total_return": tr}).to_parquet(
            os.path.join(root, "GVKEY000001_01W_1D.parquet"))
        P = pnl_dollar.load_daily_prices("GVKEY000001_01W")
        check("pnl_dollar_uses_tr_for_returns", P is not None and np.allclose(P["close"], usd)
              and np.allclose(P["tr"], tr) and P.attrs.get("usd") is True,
              "" if P is None else f"tr==close_usd? {np.allclose(P['tr'], usd)}")
    finally:
        pnl_dollar._WRDS_DIR = orig
        pnl_dollar._cache.clear()
        shutil.rmtree(root, ignore_errors=True)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
