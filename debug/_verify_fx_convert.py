"""
Synthetic checks for fx_convert.py (2026-09-27; code review R1.1 -- Compustat Global prices are in each listing's
local currency; 73 of the pool's 764 GVKEY legs changed currency, e.g. FRF -> EUR in 1999).

Compustat daily exchange rates (comp_global_daily.g_exrt_dly) quote exratd = units of `tocurd` per 1 GBP, so
    usd_price(t) = local_price(t) * exratd[USD](t) / exratd[local currency on date t](t).
Checks (hand-computed):
  1. currency_on_dates assigns each date the currency of the period containing it (FRF then EUR);
  2. conversion uses the currency valid ON THAT DATE (FRF before the switch, EUR after);
  3. rates are as-of (last rate at or before the date), and a rate staler than max_stale_days -> NaN;
  4. a date with no currency period -> NaN (never guessed);
  5. a USD listing is unchanged.
Run: python debug/_verify_fx_convert.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from fx_convert import currency_on_dates, to_usd

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    periods = pd.DataFrame({"curcdd": ["FRF", "EUR"],
                            "first_d": pd.to_datetime(["1998-12-28", "1999-01-04"]),
                            "last_d": pd.to_datetime(["1998-12-31", "1999-01-08"])})
    dates = pd.to_datetime(["1998-12-28", "1998-12-30", "1999-01-04", "1999-01-07", "1999-01-20"])
    cur = currency_on_dates(periods, dates)
    check("currency_by_period", list(cur) == ["FRF", "FRF", "EUR", "EUR", None], f"{list(cur)}")

    # GBP-based rates: USD 1.60/GBP throughout; FRF 9.60/GBP (1 FRF = 1/6 USD); EUR 1.40/GBP (1 EUR = 1.142857 USD).
    fx = pd.DataFrame({
        "datadate": pd.to_datetime(["1998-12-28"] * 2 + ["1999-01-04"] * 2 + ["1998-12-29", "1999-01-05"]),
        "tocurd": ["USD", "FRF", "USD", "EUR", "FRF", "EUR"],
        "exratd": [1.60, 9.60, 1.60, 1.40, 9.60, 1.40],
    })
    price = pd.Series([60.0, 60.0, 10.0, 10.0, 10.0], index=dates)
    usd = to_usd(price, cur, fx, max_stale_days=5)
    check("frf_converted", abs(usd.iloc[0] - 10.0) < 1e-9, f"{usd.iloc[0]}")                  # 60 FRF * 1.6/9.6
    check("frf_asof_rate", abs(usd.iloc[1] - 10.0) < 1e-9, f"{usd.iloc[1]}")                  # uses 12-29 FRF rate
    check("eur_converted", abs(usd.iloc[2] - 10.0 * 1.60 / 1.40) < 1e-9, f"{usd.iloc[2]}")
    check("eur_asof_within_limit", abs(usd.iloc[3] - 10.0 * 1.60 / 1.40) < 1e-9, f"{usd.iloc[3]}")  # 3 days stale
    check("no_currency_period_nan", np.isnan(usd.iloc[4]), f"{usd.iloc[4]}")
    usd_stale = to_usd(pd.Series([10.0], index=pd.to_datetime(["1999-01-07"])), pd.Series(["EUR"], index=pd.to_datetime(["1999-01-07"])),
                       fx, max_stale_days=1)
    check("stale_rate_nan", np.isnan(usd_stale.iloc[0]), f"{usd_stale.iloc[0]}")
    u = to_usd(pd.Series([5.0], index=pd.to_datetime(["1999-01-04"])), pd.Series(["USD"], index=pd.to_datetime(["1999-01-04"])), fx)
    check("usd_unchanged", abs(u.iloc[0] - 5.0) < 1e-12, f"{u.iloc[0]}")
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
