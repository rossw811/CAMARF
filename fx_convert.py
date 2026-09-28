"""
fx_convert.py -- per-row USD conversion of Compustat Global prices (2026-09-27; Ross-approved; fixes code review
R1.1: Compustat Global `close` is in the listing's local currency, with no FX applied anywhere, so 498 of 929
confirmed pairs mixed currencies in cointegration tests and P&L).

Sources (both from WRDS, one consistent convention):
  * currency per listing per period: comp_global_daily.g_secd curcdd, aggregated to
    (gvkey, iid, curcdd, first_d, last_d) -> output/cache/wrds/_fx/gvkey_currency_periods.parquet;
  * daily exchange rates: comp_global_daily.g_exrt_dly, exratd = units of `tocurd` per 1 GBP (205 currencies,
    including legacy DEM/FRF/ITL/ESP/NLG/GRD from 1982 and TRL) -> output/cache/wrds/_fx/g_exrt_dly.parquet.

    usd_price(t) = local_price(t) * exratd[USD](t) / exratd[currency valid on date t](t)

The currency is taken per DATE (73 of the pool's 764 legs changed currency, e.g. FRF -> EUR in 1999). Rates are
as-of (last available at or before t) but never older than `max_stale_days`; a date with no currency period or
no fresh rate becomes NaN -- never guessed. Verified against hand-computed cases: debug/_verify_fx_convert.py.
"""
import numpy as np
import pandas as pd


def currency_on_dates(periods: pd.DataFrame, dates) -> pd.Series:
    """Currency code valid on each date from (curcdd, first_d, last_d) periods; None outside every period.
    If periods overlap (dual quotation), the one that started most recently wins."""
    idx = pd.DatetimeIndex(dates)
    out = pd.Series([None] * len(idx), index=idx, dtype=object)
    for r in periods.sort_values("first_d").itertuples():
        m = (idx >= pd.Timestamp(r.first_d)) & (idx <= pd.Timestamp(r.last_d))
        out[m] = r.curcdd
    return out


def _rate_asof(fx: pd.DataFrame, currency: str, dates: pd.DatetimeIndex, max_stale_days: int) -> np.ndarray:
    s = fx[fx["tocurd"] == currency][["datadate", "exratd"]].dropna()
    if s.empty:
        return np.full(len(dates), np.nan)
    s = s.assign(datadate=pd.to_datetime(s["datadate"])).sort_values("datadate").drop_duplicates("datadate", keep="last")
    left = pd.DataFrame({"t": dates}).sort_values("t")
    m = pd.merge_asof(left, s.rename(columns={"datadate": "rate_date"}), left_on="t", right_on="rate_date",
                      direction="backward", tolerance=pd.Timedelta(days=max_stale_days))
    m.index = left.index
    return m.sort_index()["exratd"].to_numpy(dtype=float)


def to_usd(price: pd.Series, currency: pd.Series, fx: pd.DataFrame, max_stale_days: int = 5) -> pd.Series:
    """Convert a local-currency price series to USD using the per-date currency and GBP-based Compustat rates."""
    dates = pd.DatetimeIndex(price.index)
    cur = currency.reindex(dates)
    out = np.full(len(dates), np.nan)
    usd_rate = _rate_asof(fx, "USD", dates, max_stale_days)
    for c in pd.unique(cur.dropna()):
        mask = (cur == c).to_numpy()
        if c == "USD":
            out[mask] = price.to_numpy(dtype=float)[mask]
            continue
        local = _rate_asof(fx, c, dates, max_stale_days)
        out[mask] = price.to_numpy(dtype=float)[mask] * usd_rate[mask] / local[mask]
    return pd.Series(out, index=price.index, name="close_usd")
