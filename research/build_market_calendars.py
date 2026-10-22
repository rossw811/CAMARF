"""
research/build_market_calendars.py -- derived trading calendars for non-US markets (Ross 2026-10-22; market_calendar.py).

Groups: Compustat Global listings by exchange (comp.g_security.exchg, output/cache/wrds/global_security_exchange.parquet
from WRDS job 35; segments `_segN` belong to their label's exchange) and yfinance non-US daily listings by ticker
suffix (.T, .HK, .L, ...). Per group, market_calendar.derive_calendar on each listing's valid dates (close total return
where present, finite and > 0) from the live, pre-seal caches. US (NYSE), crypto (every day) and forex (weekdays) need
no build. Refuses to run without the exchange file (a missing one would silently leave every Compustat Global leg on
the weekday rule this replaces).
Output: output/research/market_calendars.parquet (market, date) + a printed per-market summary.
Usage: python research/build_market_calendars.py        Check: debug/_verify_market_calendar_holes.py
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import market_calendar as mc  # noqa: E402
from config import Config  # noqa: E402


def _valid_dates(path: str) -> pd.DatetimeIndex:
    d = pd.read_parquet(path)
    col = next((c for c in ("close_total_return", "close_usd", "close") if c in d.columns), None)
    if col is None:
        return pd.DatetimeIndex([])
    s = pd.to_numeric(d[col], errors="coerce")
    idx = pd.DatetimeIndex(d.index[np.isfinite(s.to_numpy()) & (s.to_numpy() > 0)])
    idx = idx.tz_localize(None) if idx.tz is not None else idx
    return idx.normalize().unique()


def main():
    if not os.path.exists(mc.EXCHANGE_PATH):
        raise SystemExit(f"{mc.EXCHANGE_PATH} missing -- run WRDS job 35 (output/wrds_jobs/queue/"
                         f"35_fetch_global_exchange_codes.py) first")
    ex = mc._exchange_by_label()
    groups = {}
    n_unknown = 0
    for f in glob.glob(os.path.join(Config.DATA.CACHE_DIR, "wrds", "GVKEY*_1D.parquet")):
        label = os.path.basename(f)[:-len("_1D.parquet")]
        m = mc.market_of(label, ex)
        if m == "UNKNOWN":
            n_unknown += 1
            continue
        groups.setdefault(m, {})[label] = _valid_dates(f)
    for f in glob.glob(os.path.join(Config.DATA.CACHE_DIR, "*_1day.parquet")):
        sym = os.path.basename(f)[:-len("_1day.parquet")]
        m = mc.market_of(sym, ex)
        if m.startswith("yf:"):
            groups.setdefault(m, {})[sym] = _valid_dates(f)
    rows, summ = [], []
    for m, members in sorted(groups.items()):
        cal = mc.derive_calendar(members, mc.MIN_GROUP)
        wd = pd.bdate_range(cal.min(), cal.max()) if len(cal) else pd.DatetimeIndex([])
        rows.append(pd.DataFrame({"market": m, "date": cal}))
        summ.append({"market": m, "n_listings": len(members), "first": cal.min() if len(cal) else None,
                     "last": cal.max() if len(cal) else None, "n_days": len(cal),
                     "weekdays_closed": int(len(wd) - len(cal))})
    out = pd.concat(rows, ignore_index=True)
    os.makedirs(os.path.dirname(mc.CALENDARS_PATH), exist_ok=True)
    out.to_parquet(mc.CALENDARS_PATH, index=False)
    S = pd.DataFrame(summ)
    print(S.to_string(index=False))
    print(f"{len(S)} markets, {len(out)} market-days -> {mc.CALENDARS_PATH}; Compustat Global labels with no exchange "
          f"code (weekday rule): {n_unknown}")


if __name__ == "__main__":
    main()
