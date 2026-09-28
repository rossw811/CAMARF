"""
research/apply_fx_to_wrds_global.py -- add a USD close to every Compustat Global WRDS file (2026-09-27; fixes code
review R1.1 with fx_convert.py; Ross-approved USD conversion).

For each label in output/cache/wrds/global_universe_manifest.parquet (label -> gvkey, iid), reads
output/cache/wrds/{label}_1D.parquet, determines the currency valid on each date from
output/cache/wrds/_fx/gvkey_currency_periods.parquet, converts `close` with the Compustat daily exchange rates
(output/cache/wrds/_fx/g_exrt_dly.parquet) and writes a `close_usd` column back (atomic tmp + replace). The
original columns are never modified. Files with no currency periods are left unchanged and reported.

Usage: python research/apply_fx_to_wrds_global.py [--limit N]
"""
import argparse
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fx_convert import currency_on_dates, to_usd

_WRDS = os.path.join("output", "cache", "wrds")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    man = pd.read_parquet(os.path.join(_WRDS, "global_universe_manifest.parquet"))
    per = pd.read_parquet(os.path.join(_WRDS, "_fx", "gvkey_currency_periods.parquet"))
    fx = pd.read_parquet(os.path.join(_WRDS, "_fx", "g_exrt_dly.parquet"))
    per["gvkey"] = per["gvkey"].astype(str)
    groups = {k: g for k, g in per.groupby(["gvkey", "iid"])}
    rows = man[["label", "gvkey", "iid"]].drop_duplicates("label")
    if args.limit:
        rows = rows.head(args.limit)
    t0, stats = time.time(), []
    for i, r in enumerate(rows.itertuples(), 1):
        path = os.path.join(_WRDS, f"{r.label}_1D.parquet")
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            stats.append((r.label, "no_file", np.nan, "")); continue
        g = groups.get((str(r.gvkey), str(r.iid)))
        if g is None:
            stats.append((r.label, "no_currency_periods", np.nan, "")); continue
        df = pd.read_parquet(path)
        close = df["close"].astype(float)
        cur = currency_on_dates(g, close.index)
        usd = to_usd(close, cur, fx)
        df["close_usd"] = usd.to_numpy()
        df.to_parquet(path + ".tmp")
        os.replace(path + ".tmp", path)
        stats.append((r.label, "ok", float(usd.notna().mean()), ",".join(sorted(g["curcdd"].dropna().astype(str).unique()))))
        if i % 1000 == 0:
            print(f"{i}/{len(rows)} ({time.time() - t0:.0f}s)", flush=True)
    S = pd.DataFrame(stats, columns=["label", "status", "usd_coverage", "currencies"])
    S.to_parquet(os.path.join("output", "research", "apply_fx_to_wrds_global_report.parquet"))
    print(S["status"].value_counts().to_string())
    ok = S[S["status"] == "ok"]
    print(f"median USD coverage of rows: {ok['usd_coverage'].median():.3f}; files <90% covered: {(ok['usd_coverage'] < 0.9).sum()}")


if __name__ == "__main__":
    main()
