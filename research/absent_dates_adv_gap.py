"""
research/absent_dates_adv_gap.py -- BUG-D122 review open point (b): dates with NO row in a cache file are invisible to
the DATA_GAP rule in `rolling_adv`, which counts consecutive NaN rows, not missing trading days. A 252-row trailing
window can then reach back over a long hole without being voided. How much does that change the discovery ADV gate?

Per file, against the file's own market calendar (market_calendar.calendar_for; weekdays where the market is unknown):
  absent trading days, absent runs > data._MAX_FILL_BARS (the DATA_GAP size), longest run;
  at every pre-seal row with a price (a superset of the gate's dates: a window start is always a date on which both
  legs have a price), the gate verdict ADV >= Config.STATS.ADV_FILTER_USD as discovery computes it
  (`rolling_adv` on the file's rows, read with `adv_at`) against the same with the absent days inserted as empty rows
  (then the DATA_GAP rule sees them). Reports verdict flips both ways and the ADV level ratio where both are valid.
DESCRIPTIVE: changes nothing in discovery. Rows on/after Config.DATA.SEALED_FROM are dropped before anything is read.
Scope: every leg of the Amendment 7 PIT pools (k1, k2) + a seeded random sample of other 1D WRDS files, US and non-US.

Run (CachyOS, read-only):  python research/absent_dates_adv_gap.py [--n-sample 1000] [--seed 20261104]
Output: output/research/absent_dates_adv_gap.parquet (one row per file) + printed summary.
Check: debug/_verify_absent_dates_adv_gap.py
"""
import argparse
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "research")]

import numpy as np
import pandas as pd

import parquet_io
from config import Config
from data import _MAX_FILL_BARS
from market_calendar import calendar_for, market_of, missing_trading_days
from rolling_adv_comparison import adv_at, rolling_adv

CACHE = os.path.join(ROOT, "output", "cache", "wrds")
OUT = os.path.join(ROOT, "output", "research", "absent_dates_adv_gap.parquet")


def _base(sym: str) -> str:
    return str(sym).split("_seg")[0]


def file_effect(df: pd.DataFrame, cal, thr: float, sealed_from=Config.DATA.SEALED_FROM) -> dict:
    """Absent-date counts and gate-verdict changes for one file (see module docstring). `cal` None -> weekdays."""
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    df.index = df.index.normalize()
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df[df.index < pd.Timestamp(sealed_from)]
    px = pd.to_numeric(df["close"], errors="coerce")
    priced = df.index[px.notna().to_numpy()]
    out = dict(n_rows=len(df), n_priced=len(priced), n_absent=0, n_runs_gt=0, max_run=0, n_eval=0,
               pass_now=0, pass_cal=0, flip_close=0, flip_open=0, close_gap=0, ratio_med=np.nan, ratio_p10=np.nan,
               ratio_p90=np.nan)
    if len(priced) < 2:
        return out
    miss = missing_trading_days(df.index.values.astype("datetime64[D]"), cal)
    out.update(n_absent=int(miss.sum()), n_runs_gt=int((miss > _MAX_FILL_BARS).sum()), max_run=int(miss.max()))
    lo, hi = df.index[0], df.index[-1]
    days = (cal[(cal >= lo) & (cal <= hi)] if cal is not None else pd.bdate_range(lo, hi))
    full = df.index.union(days)
    adv_now = rolling_adv(df)
    adv_cal = rolling_adv(df.reindex(full))
    a = np.array([adv_at(adv_now, d) for d in priced])
    b = np.array([adv_at(adv_cal, d) for d in priced])
    pa = np.isfinite(a) & (a >= thr)
    pb = np.isfinite(b) & (b >= thr)
    both = np.isfinite(a) & np.isfinite(b) & (a > 0)
    r = b[both] / a[both]
    out.update(n_eval=len(priced), pass_now=int(pa.sum()), pass_cal=int(pb.sum()),
               flip_close=int((pa & ~pb).sum()), flip_open=int((~pa & pb).sum()),
               close_gap=int((pa & ~np.isfinite(b)).sum()))
    if len(r):
        out.update(ratio_med=float(np.median(r)), ratio_p10=float(np.quantile(r, 0.1)),
                   ratio_p90=float(np.quantile(r, 0.9)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-sample", type=int, default=1000, help="random non-pool files per group (US, non-US)")
    ap.add_argument("--seed", type=int, default=20261104)
    args = ap.parse_args()
    thr = Config.STATS.ADV_FILTER_USD
    pool = set()
    for k in (1, 2):
        P = parquet_io.read_parquet(os.path.join(ROOT, "output", "research", f"purity_pairs_pit_k{k}_clean.parquet"))
        P = P[P["tf_label"] == "1D"] if "tf_label" in P.columns else P
        pool |= {_base(s) for s in pd.concat([P["symbol_a"], P["symbol_b"]])}
    files = {os.path.basename(f)[:-len("_1D.parquet")]: f for f in glob.glob(os.path.join(CACHE, "*_1D.parquet"))}
    rest = sorted(set(files) - pool)
    rng = np.random.default_rng(args.seed)
    us = [s for s in rest if market_of(s) == "US"]
    intl = [s for s in rest if market_of(s) != "US"]
    pick = lambda xs: list(rng.choice(xs, size=min(args.n_sample, len(xs)), replace=False)) if xs else []
    todo = [(s, "pool") for s in sorted(pool) if s in files] + [(s, "sample_us") for s in pick(us)] \
        + [(s, "sample_intl") for s in pick(intl)]
    print(f"pool legs {len(pool)} ({sum(g == 'pool' for _, g in todo)} with a 1D file); sample US {len(us)} -> "
          f"{sum(g == 'sample_us' for _, g in todo)}, non-US {len(intl)} -> {sum(g == 'sample_intl' for _, g in todo)}",
          flush=True)
    rows = []
    for i, (s, g) in enumerate(todo):
        try:
            d = parquet_io.read_parquet(files[s])
            if not {"close", "volume"} <= set(d.columns):
                continue
            cal = calendar_for(s)
            rows.append(dict(symbol=s, group=g, market=market_of(s), cal_known=cal is not None,
                             **file_effect(d, cal, thr)))
        except Exception as e:                      # one bad file is reported, never silently dropped
            rows.append(dict(symbol=s, group=g, market=market_of(s), error=repr(e)[:200]))
        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{len(todo)}", flush=True)
    R = pd.DataFrame(rows)
    R.to_parquet(OUT, index=False)
    R["intl"] = R["market"] != "US"
    print(f"\nwrote {OUT} ({len(R)} files; errors {int(R.get('error', pd.Series(dtype=object)).notna().sum())})")
    for (g, intl), x in R.groupby(["group", "intl"]):
        x = x[x["n_eval"] > 0]
        if not len(x):
            continue
        ev, pn = x["n_eval"].sum(), x["pass_now"].sum()
        print(f"{g:12s} {'non-US' if intl else 'US':6s} files {len(x):5d} | any absent run > {_MAX_FILL_BARS}: "
              f"{(x['n_runs_gt'] > 0).mean():.1%}, absent days / priced rows {x['n_absent'].sum() / x['n_priced'].sum():.2%}"
              f", max run {x['max_run'].max()} | gate rows {ev:,}: pass now {pn / ev:.1%}, with absent days seen "
              f"{x['pass_cal'].sum() / ev:.1%}; flips pass->fail {x['flip_close'].sum() / max(pn, 1):.2%} of passes "
              f"({x['close_gap'].sum():,} by a gap), fail->pass {x['flip_open'].sum():,}; ADV ratio median of file medians "
              f"{x['ratio_med'].median():.4f}", flush=True)


if __name__ == "__main__":
    main()
