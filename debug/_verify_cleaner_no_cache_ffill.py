"""
Regression test for code-review finding D8 (2026-09-26), DataCleaner._fill_gaps:
  (a) for IBKR "1 day" bars it reindexed onto NYSE sessions and FORWARD-FILLED before the cache write -- fabricated
      bars of any run length were stored as if real (GapFlag can never see them downstream, CLAUDE.md rule 3), and
      a crypto series lost every weekend bar (not an NYSE session);
  (b) yfinance/WRDS pass tf_ibkr = tf_label ("1D"), which matched neither the "1 day" nor the intraday branch, so
      missing_pct was always 0 and Config.DATA.MAX_MISSING_PCT never applied to them.
Fix: cleaning never adds rows; the missing share is MEASURED (not filled) against the asset's own calendar --
every calendar day for crypto, weekdays otherwise (US holidays ~3.6%, as config.py's MAX_MISSING_PCT note assumes)
-- for "1 day" and "1D" alike.
Checks (DataCleaner.clean end to end):
  1. IBKR equity daily with a 10-weekday hole: no rows are created inside the hole;
  2. IBKR crypto daily: weekend bars survive;
  3. yfinance "1D" with 30% of weekdays missing: rejected on missing_pct;
  4. yfinance "1D" equity missing only NYSE holidays: passes, missing_pct < 5%, nothing trimmed;
  5. a series with a sparse OLD stretch (50% missing, like PL=F's 2006-2009 Yahoo hole) and complete recent years
     is kept from one bar after the START of its last unreliable 252-bar window -- not rejected whole; every 252-bar
     window of the kept span meets MAX_MISSING_PCT (so at most ~2.5 months of the 50%-sparse tail remains).
Run: python debug/_verify_cleaner_no_cache_ffill.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal

from data import DataCleaner

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def _ohlcv(idx):
    c = 100 + np.cumsum(np.random.default_rng(len(idx)).normal(0, 1, len(idx)))
    return pd.DataFrame({"open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1e6}, index=idx)


def main():
    nyse = mcal.get_calendar("NYSE").valid_days("2022-01-03", "2024-12-31").tz_localize(None)
    hole = nyse[300:310]
    eq = _ohlcv(nyse.difference(hole))
    out, rep = DataCleaner.clean(eq, "EQ", "equity", "1D", "1 day", source="ibkr")
    inside = 0 if out is None else int(out.index.isin(hole).sum())
    check("ibkr_daily_no_rows_in_hole", out is not None and inside == 0, f"rows created inside hole={inside}")

    cr = _ohlcv(pd.date_range("2022-01-01", "2024-12-31"))
    out, rep = DataCleaner.clean(cr, "BTC", "crypto", "1D", "1 day", source="ibkr")
    wk = 0 if out is None else int((out.index.dayofweek >= 5).sum())
    check("ibkr_crypto_weekends_kept", wk == int((cr.index.dayofweek >= 5).sum()), f"weekend rows={wk}")

    rng = np.random.default_rng(1)
    sparse = _ohlcv(nyse[np.sort(rng.choice(len(nyse), int(len(nyse) * 0.7), replace=False))])
    out, rep = DataCleaner.clean(sparse, "SPARSE", "equity", "1D", "1D", source="yfinance")
    check("yf_30pct_missing_rejected", out is None and "missing_pct" in (rep.fail_reason or ""),
          f"passed={rep.passed} missing_pct={rep.missing_pct:.3f} reason={rep.fail_reason}")

    out, rep = DataCleaner.clean(_ohlcv(nyse), "FULL", "equity", "1D", "1D", source="yfinance")
    check("yf_holidays_only_passes", out is not None and rep.missing_pct < 0.05 and len(out) == len(nyse),
          f"missing_pct={rep.missing_pct:.3f} rows={0 if out is None else len(out)}/{len(nyse)}")

    long_cal = mcal.get_calendar("NYSE").valid_days("2004-01-02", "2016-12-30").tz_localize(None)
    sparse_old = long_cal[(long_cal < "2010-01-01") & (np.arange(len(long_cal)) % 2 == 0)]   # 50% missing to 2009
    series = _ohlcv(sparse_old.append(long_cal[long_cal >= "2010-01-01"]))
    out, rep = DataCleaner.clean(series, "PLLIKE", "commodity", "1D", "1D", source="yfinance")
    first = None if out is None else out.index.min()
    ok = out is not None and pd.Timestamp("2009-08-01") < first <= pd.Timestamp("2010-01-04") and rep.missing_pct < 0.10
    if ok:
        kept_cal = pd.bdate_range(first, out.index.max())
        m = pd.Series(~kept_cal.isin(out.index.normalize()), index=kept_cal, dtype=float).rolling(252).mean()
        ok = bool((m.dropna() <= 0.10).all())
    check("sparse_prefix_trimmed_not_rejected", ok,
          f"first kept={first} missing_pct={rep.missing_pct:.3f} reason={rep.fail_reason}")
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
