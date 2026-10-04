"""
research/crsp_volume_split_adjustment.py -- DEV-003 (open since 2026-07-27; resolved 2026-10-03, bug recheck T14).

The problem
-----------
The WRDS cache stores CRSP `close` split-adjusted (dlyclose / dlycumfacpr) but `volume` RAW (dlyvol, pre-split share
counts). Dollar volume = close x volume therefore understates real dollar volume before every later split by the
cumulative split factor (AAPL 2020-08-28: $5.8B computed vs ~$23B real). Every ADV gate that multiplies them
(the discovery scan's rolling-ADV gate, the liquidity bar mask, sqrt-impact costs) treats a stock that LATER SPLIT
as less liquid in its earlier years -- a bias that leans against past winners, not random noise.

The fix, verified
-----------------
adjusted volume_t = raw volume_t x prod over price-factor events with ex-date > t of (1 + disfacpr)
(CRSP crsp_a_stock.stkdistributions, fetched to output/cache/wrds/crsp_stock_distributions_facpr.parquet: 65,141
events, 25,673 permnos). Direction checked against yfinance's split-adjusted volume on AAPL across its 2014 7:1 and
2020 4:1 splits: 187,288,160 vs 187,630,000 (2020-08-28), 350,517,804 vs 349,938,400 (2014-06-06), 301,743,428 vs
301,660,000 (2014-06-09) -- within 0.2%; 2010-01-04 within 3.5% (consolidated-volume differences).
Factor rebuild verified against CRSP's own dlycumfacpr (fetched for 307 securities stratified across every event
type, output/cache/wrds/crsp_cumfac_sample.parquet): 307/307 match on every day with a known factor, after two
corrections found by that comparison -- same-date events add (1 + sum), and terminal -1 events are excluded. The 40
securities (of 30,256) with cash-payment / partial-liquidation events get an UNKNOWN factor before those events.
A first impact run that zeroed whole histories (terminal events multiplied in) was discarded.

Usage:  python research/crsp_volume_split_adjustment.py impact   # how many rolling-ADV gate decisions flip
Synthetic check: debug/_verify_crsp_volume_split_adjustment.py
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from config import Config

_WRDS = os.path.join("output", "cache", "wrds")
FACPR_PATH = os.path.join(_WRDS, "crsp_stock_distributions_facpr.parquet")
LABEL_MAP_PATH = os.path.join(_WRDS, "full_us_market_label_map.parquet")


def cumulative_factor(dates: pd.DatetimeIndex, events: pd.DataFrame) -> np.ndarray:
    """CRSP's cumulative price factor, rebuilt from the distribution events and matched against CRSP's own
    dlycumfacpr on 307 securities covering every event type (2026-10-03):
      * events on the SAME ex-date combine additively: 1 + sum(disfacpr) (multiplying them mismatched CRSP);
      * across ex-dates the factors multiply; a date's factor covers events with ex-date STRICTLY after it (the
        ex-date itself already trades in post-event units);
      * normalised to the LAST date given (= the security's last trading day when `dates` is its history), so
        terminal events after the last trade (disfacpr -1: merger, liquidation, exchange) cancel out -- an
        un-normalised first impact run multiplied whole histories by 0."""
    dates = pd.DatetimeIndex(dates)
    if events is None or len(events) == 0 or len(dates) == 0:
        return np.ones(len(dates))
    ev = events.assign(_ex=pd.to_datetime(events["disexdt"]), _f=events["disfacpr"].astype(float))
    # terminal events (disfacpr -1: merger / liquidation / exchange) are NOT part of CRSP's dlycumfacpr -- a security
    # delisted on its event date keeps factor 1.0 (permno 10552) -- so they are dropped, not just normalised away
    ev = ev[ev["_f"] > -1.0]
    if len(ev) == 0:
        return np.ones(len(dates))
    # cash-payment / partial-liquidation events (factor between -1 and 0 that is not a reverse split) follow a CRSP
    # convention this rebuild does not reproduce (CRSP's jump != 1 + disfacpr; 40 of 30,256 labelled securities) ->
    # the factor is UNKNOWN (NaN) before the last such event, never a guess
    split_like = ev["distype"].eq("FRS") if "distype" in ev.columns else pd.Series(True, index=ev.index)
    odd = ev[(ev["_f"] < 0) & ~split_like]
    unknown_before = odd["_ex"].max() if len(odd) else None
    e = ev.groupby("_ex")["_f"].sum().sort_index()
    ex = e.index.to_numpy(dtype="datetime64[ns]")
    f = (1.0 + e.to_numpy())
    suffix = np.concatenate([np.cumprod(f[::-1])[::-1], [1.0]])     # suffix[k] = prod f[k:]
    k = np.searchsorted(ex, dates.to_numpy(dtype="datetime64[ns]"), side="right")
    out = suffix[k].astype(float)
    last = out[-1]
    if last != 0.0 and np.isfinite(last):
        out = out / last
    if unknown_before is not None:
        out[dates.to_numpy(dtype="datetime64[ns]") < np.datetime64(unknown_before, "ns")] = np.nan
    return out


def adjusted_volume(df: pd.DataFrame, events: pd.DataFrame) -> pd.Series:
    """Raw CRSP volume restated in today's share units (consistent with the split-adjusted `close`)."""
    return pd.to_numeric(df["volume"], errors="coerce") * cumulative_factor(pd.DatetimeIndex(df.index), events)


def impact(threshold: float = None, window: int = None):
    """Rolling-ADV gate (the discovery scan's Tier 2/3 gate) with raw vs split-adjusted volume, every CRSP-labelled
    WRDS file: symbol-days that flip from 'below threshold' to 'at/above', and symbols affected."""
    from research.rolling_adv_comparison import ROLLING_ADV_WINDOW
    thr = threshold if threshold is not None else Config.STATS.ADV_FILTER_USD
    win = window or ROLLING_ADV_WINDOW
    ev = pd.read_parquet(FACPR_PATH)
    by_permno = {p: g for p, g in ev.groupby("permno")}
    lm = pd.read_parquet(LABEL_MAP_PATH)
    permno_of = dict(zip(lm["label"], lm["permno"].astype(int)))
    rows = []
    for path in glob.glob(os.path.join(_WRDS, "*_1D.parquet")):
        sym = os.path.basename(path)[:-len("_1D.parquet")]
        p = permno_of.get(sym)
        if p is None:
            continue
        try:
            d = pd.read_parquet(path, columns=["close", "volume"])
        except Exception:
            continue
        d.index = pd.to_datetime(d.index)
        px = pd.to_numeric(d["close"], errors="coerce").abs()
        raw = (px * pd.to_numeric(d["volume"], errors="coerce")).rolling(win, min_periods=win).mean()
        adj = (px * adjusted_volume(d, by_permno.get(p))).rolling(win, min_periods=win).mean()
        ok = raw.notna() & adj.notna()
        flips = int(((raw < thr) & (adj >= thr) & ok).sum())
        false_liquid = int(((raw >= thr) & (adj < thr) & ok).sum())
        rows.append({"symbol": sym, "permno": p, "days": int(ok.sum()), "flip_days": flips,
                     "false_liquid_days": false_liquid, "unknown_factor_days": int((raw.notna() & adj.isna()).sum()),
                     "raw_pass_days": int(((raw >= thr) & ok).sum()), "adj_pass_days": int(((adj >= thr) & ok).sum())})
    r = pd.DataFrame(rows)
    out = os.path.join("output", "research", "crsp_volume_split_adjustment_impact.parquet")
    r.to_parquet(out)
    tot = r["days"].sum()
    print(f"threshold ${thr:,.0f}, window {win}: {len(r):,} CRSP symbols; symbols with >=1 flipped day: "
          f"{int((r['flip_days'] > 0).sum()):,}; flipped symbol-days {r['flip_days'].sum():,} of {tot:,} "
          f"({r['flip_days'].sum() / max(tot, 1):.2%}); wrongly PASSED (reverse splits) {r['false_liquid_days'].sum():,} "
          f"symbol-days in {int((r['false_liquid_days'] > 0).sum()):,} symbols; unknown-factor days "
          f"{r['unknown_factor_days'].sum():,}; gate passes raw {r['raw_pass_days'].sum():,} -> "
          f"adjusted {r['adj_pass_days'].sum():,} -> {out}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "impact":
        impact()
    else:
        print(__doc__)
