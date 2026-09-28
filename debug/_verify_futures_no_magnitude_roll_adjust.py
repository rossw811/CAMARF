"""
Regression test for code-review finding D9 (2026-09-26): DataCleaner._roll_adjust treated ANY >5% close-to-close move
in a futures/commodity series as a contract roll and back-adjusted all earlier prices to erase it. On real raw
yfinance continuous series (measured 2026-09-27) that rewrote 41 ES days (incl. 2008-10-13 +14%, 2020-03-16 -10%),
311 CL days and 894 NG days of genuine market moves; ZN had 0 such days, and a real equity-index/bond roll gap is
well under 1%, so the rule never caught an actual roll there. A return-magnitude threshold cannot tell a roll from a
crash.
Fix: DataCleaner.clean no longer rewrites futures/commodity prices (same principle as D1: cleaning never
fabricates or rewrites observed prices). Roll handling from real contract calendars is an open methodology item.
Checks (synthetic futures daily series, DataCleaner.clean end to end):
  1. a genuine +12% day is preserved (was erased by back-adjusting every earlier price);
  2. prices before that day are unchanged;
  3. the report records no roll dates.
Run: python debug/_verify_futures_no_magnitude_roll_adjust.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from data import DataCleaner

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    idx = pd.bdate_range("2019-01-01", periods=400)
    c = 3000 * np.exp(np.cumsum(np.random.default_rng(0).normal(0, 0.005, len(idx))))
    shock = 250
    c[shock:] *= 1.12
    raw = pd.DataFrame({"open": c, "high": c * 1.001, "low": c * 0.999, "close": c, "volume": 1e5}, index=idx)
    out, rep = DataCleaner.clean(raw, "ES", "futures", "1D", "1D", source="yfinance")
    r = out["close"].pct_change()
    d = idx[shock]
    check("real_12pct_day_preserved", abs(r.loc[d] - (c[shock] / c[shock - 1] - 1)) < 1e-9, f"r={r.loc[d]:.4f}")
    check("earlier_prices_unchanged", np.allclose(out["close"].loc[:idx[shock - 1]].to_numpy(), c[:shock]))
    check("no_roll_dates_reported", len(rep.roll_dates) == 0, f"{rep.roll_dates}")
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
