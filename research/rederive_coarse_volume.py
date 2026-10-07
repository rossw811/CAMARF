"""
research/rederive_coarse_volume.py -- DEV-003 follow-up (2026-10-07): restate the volume of the coarse WRDS files
(output/cache/wrds/{label}_{7D,1M,3M,6M,1Y}.parquet) from the restated daily files.

Why: apply_crsp_volume_adjustment.py restated the DAILY files (volume in today's share units, raw kept in
volume_raw); the coarse files still carry raw share counts, so pre-split dollar volume there is understated the
same way. 7D/3M/6M/1Y were summed from raw daily volume at fetch time (data_wrds.resample_daily_to); 1M is CRSP's
native mthvol, which equals the summed raw daily volume (ratio 1.0000 p5..p95 on AAPL, MSFT, GE, NVDA, KO, XOM, F,
IBM). So a bar's restated volume = the sum of the restated daily volume over the same calendar period
(period_bars.period_end_index -- the stamp every coarse file uses).

Guard: a bar is restated only if its stored volume equals the summed RAW daily volume of its period (rtol 1e-6) --
proof it was built from these daily rows. Otherwise its volume becomes NaN and is counted as a mismatch, never a
guess. A period containing a day with an unknown factor (NaN daily volume) gets NaN, not a partial sum. The old
value stays in volume_raw; close and every other column are untouched. Idempotent (a file with volume_raw is
skipped); writes are atomic. Future fetches: data_wrds.py already restates at source.
Usage:  python research/rederive_coarse_volume.py
Report: output/research/rederive_coarse_volume_report.parquet
Synthetic check: debug/_verify_rederive_coarse_volume.py
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from period_bars import TIMEFRAMES, period_end_index

_WRDS = os.path.join("output", "cache", "wrds")
REPORT = os.path.join("output", "research", "rederive_coarse_volume_report.parquet")
COARSE_TFS = tuple(TIMEFRAMES)                                 # 7D/1M/3M/6M/1Y (1M: CRSP native monthly)


def restate_coarse(daily: pd.DataFrame, coarse: pd.DataFrame, tf: str):
    """daily: restated daily frame (volume, volume_raw). coarse: one coarse file. Returns (new_coarse, stats)."""
    if "volume_raw" in coarse.columns:
        return coarse, {"skipped": True}
    keys = period_end_index(daily.index, tf)
    vol = pd.to_numeric(daily["volume"], errors="coerce")
    raw = pd.to_numeric(daily["volume_raw"], errors="coerce")
    adj_sum = vol.groupby(keys).sum(min_count=1)
    n_unknown_days = vol.isna().groupby(keys).sum()
    raw_sum = raw.groupby(keys).sum(min_count=1)
    idx = pd.DatetimeIndex(coarse.index)
    adj_sum, n_unknown_days, raw_sum = (s.reindex(idx) for s in (adj_sum, n_unknown_days, raw_sum))
    stored = pd.to_numeric(coarse["volume"], errors="coerce").to_numpy()
    has = ~np.isnan(stored)
    match = has & np.isclose(stored, raw_sum.to_numpy(), rtol=1e-6, atol=0.5)
    unknown = match & (n_unknown_days.fillna(0).to_numpy() > 0)
    ok = match & ~unknown
    out = coarse.copy()
    out["volume"] = np.where(ok, adj_sum.to_numpy(), np.nan)
    out["volume_raw"] = coarse["volume"]
    stats = {"skipped": False, "bars": int(len(coarse)), "restated": int(ok.sum()),
             "unknown": int(unknown.sum()), "mismatch": int((has & ~match).sum()), "no_stored_volume": int((~has).sum())}
    return out, stats


def rederive(root: str) -> pd.DataFrame:
    rows = []
    for tf in COARSE_TFS:
        for path in sorted(glob.glob(os.path.join(root, f"*_{tf}.parquet"))):
            label = os.path.basename(path)[:-len(f"_{tf}.parquet")]
            rec = {"label": label, "tf": tf, "status": "", "bars": 0, "restated": 0, "unknown": 0, "mismatch": 0,
                   "no_stored_volume": 0}
            dpath = os.path.join(root, f"{label}_1D.parquet")
            try:
                coarse = pd.read_parquet(path)
                daily = pd.read_parquet(dpath, columns=["volume", "volume_raw"]) if os.path.exists(dpath) else None
            except Exception as e:
                rec["status"] = f"unreadable: {type(e).__name__}"; rows.append(rec); continue
            if "volume" not in coarse.columns:
                rec["status"] = "no_volume"; rows.append(rec); continue
            if daily is None:
                rec["status"] = "no_daily"; rows.append(rec); continue
            if "volume_raw" in coarse.columns:
                rec["status"] = "already_restated"; rows.append(rec); continue
            new, st = restate_coarse(daily, coarse, tf)
            rec.update({k: v for k, v in st.items() if k != "skipped"})
            rec["status"] = "restated"
            new.to_parquet(path + ".tmp")
            os.replace(path + ".tmp", path)
            rows.append(rec)
    return pd.DataFrame(rows)


def _daily_check(root: str) -> list:
    """Labels whose coarse files exist but whose daily file was never restated (no volume_raw) -- must be empty."""
    labels = {os.path.basename(p)[:-len("_1M.parquet")] for p in glob.glob(os.path.join(root, "*_1M.parquet"))}
    bad = []
    for lab in sorted(labels):
        p = os.path.join(root, f"{lab}_1D.parquet")
        if os.path.exists(p) and "volume_raw" not in pd.read_parquet(p).columns:
            bad.append(lab)
    return bad


def main():
    bad = _daily_check(_WRDS)
    if bad:
        raise SystemExit(f"{len(bad)} daily files not yet restated (run apply_crsp_volume_adjustment.py first): {bad[:10]}")
    rep = rederive(_WRDS)
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    rep.to_parquet(REPORT)
    print(rep.groupby(["tf", "status"]).size().to_string())
    s = rep[rep.status == "restated"]
    print(s.groupby("tf")[["bars", "restated", "unknown", "mismatch", "no_stored_volume"]].sum().to_string())
    print(f"-> {REPORT}")


if __name__ == "__main__":
    main()
