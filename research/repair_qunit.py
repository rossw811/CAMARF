"""
research/repair_qunit.py -- BUG-D118 repair of the existing Compustat Global cache (2026-10-15).

Compustat Global prices are quoted per `qunit` shares (comp_global_daily.g_secd.qunit). data_wrds built
close = prccd / ajexdi without dividing by qunit, so a change of quotation unit (e.g. Brazil's per-1,000-share quotes
ending) shows up as a ~1000x one-day jump. data_wrds now divides by qunit at fetch; this script repairs the files
already on disk instead of refetching 15,094 histories:
  for each GVKEY<g>_<iid>_1D.parquet with a qunit run != 1 (output/cache/wrds/compustat_global_qunit_runs.parquet,
  WRDS job 31), every price column (open, high, low, close, close_usd, close_total_return) is divided by the qunit in
  force on each date; volume is untouched (shares traded are per share). The file is marked `qunit_applied` (the
  repair is idempotent) and the original is kept in output/cache/wrds/_pre_qunit_backup/ (never deleted).
close_total_return stays consistent: it is close_usd x trfd rescaled to the first close_usd, and dividing both by
the same per-date qunit keeps that relation (re-verified per file after the repair: max |dlog| at former jump dates).
Coarser files (7D..1Y) are re-derived from the repaired daily files afterwards (research/rederive_coarse_volume.py path).
Usage: python research/repair_qunit.py [--dry-run]
Test: debug/_verify_repair_qunit.py
"""
import argparse
import os
import shutil
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_W = os.path.join(ROOT, "output", "cache", "wrds")
PRICE_COLS = ("open", "high", "low", "close", "close_usd", "close_total_return")


def qunit_asof(runs: pd.DataFrame, dates) -> pd.Series:
    """Quotation unit in force on each date from runs (qunit, first_date, last_date); 1 outside every run."""
    idx = pd.DatetimeIndex(pd.to_datetime(dates))
    q = pd.Series(1.0, index=idx)
    for r in runs.sort_values("first_date").itertuples():
        q[(idx >= pd.Timestamp(r.first_date)) & (idx <= pd.Timestamp(r.last_date))] = float(r.qunit or 1.0)
    return q


def repair_frame(df: pd.DataFrame, runs: pd.DataFrame) -> pd.DataFrame:
    if "qunit_applied" in df.columns and bool(df["qunit_applied"].all()):
        return df
    out = df.copy()
    q = qunit_asof(runs, out.index).replace(0, 1.0).to_numpy()
    for c in PRICE_COLS:
        if c in out.columns:
            out[c] = out[c].astype(float) / q
    out["qunit_applied"] = True
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    runs = pd.read_parquet(os.path.join(_W, "compustat_global_qunit_runs.parquet"))
    runs["gvkey"] = runs["gvkey"].astype(str).str.zfill(6)
    man = pd.read_parquet(os.path.join(_W, "global_universe_manifest.parquet"))
    man["gvkey"] = man["gvkey"].astype(str).str.zfill(6)
    lab = {(g, i): l for l, g, i in zip(man["label"], man["gvkey"], man["iid"])}
    bak = os.path.join(_W, "_pre_qunit_backup")
    os.makedirs(bak, exist_ok=True)
    rows = []
    for (g, i), rr in runs.groupby(["gvkey", "iid"]):
        if (rr["qunit"].fillna(1.0) == 1.0).all():
            rows.append({"label": lab.get((g, i)), "status": "qunit_one"}); continue
        l = lab.get((g, i))
        f = os.path.join(_W, f"{l}_1D.parquet") if l else None
        if not f or not os.path.exists(f):
            rows.append({"label": l, "status": "no_file"}); continue
        df = pd.read_parquet(f); df.index = pd.to_datetime(df.index)
        before = float(np.log(df["close_total_return"].astype(float).abs()).diff().abs().max()) if "close_total_return" in df else np.nan
        fixed = repair_frame(df, rr)
        after = float(np.log(fixed["close_total_return"].astype(float).abs()).diff().abs().max()) if "close_total_return" in fixed else np.nan
        rows.append({"label": l, "status": "repaired" if not a.dry_run else "would_repair", "max_abs_dlog_before": before,
                     "max_abs_dlog_after": after})
        if not a.dry_run:
            if not os.path.exists(os.path.join(bak, os.path.basename(f))):
                shutil.copy2(f, os.path.join(bak, os.path.basename(f)))
            fixed.to_parquet(f + ".tmp"); os.replace(f + ".tmp", f)
    R = pd.DataFrame(rows)
    R.to_parquet(os.path.join(ROOT, "output", "research", "repair_qunit_report.parquet"))
    print(R["status"].value_counts().to_string())
    rp = R[R["status"].isin(["repaired", "would_repair"])]
    if len(rp):
        print(f"max |dlog| before: median {rp['max_abs_dlog_before'].median():.2f}; after: median "
              f"{rp['max_abs_dlog_after'].median():.2f}; still > ln 5 after: {int((rp['max_abs_dlog_after'] > np.log(5)).sum())}")


if __name__ == "__main__":
    main()
