"""
research/apply_crsp_volume_adjustment.py -- DEV-003 applied to the existing WRDS cache (Ross 2026-10-03: stop the
discovery run, fix the volume, restart).

Compustat Global (GVKEY*) files: volume = cshtrd x ajexdi from _trfd/ (T14.7 review, 2026-10-04 -- see
_apply_compustat). For every CRSP daily file (output/cache/wrds/{label}_1D.parquet, plus _quote_only/): `volume` is restated
in today's share units -- raw x the cumulative CRSP price factor of later events (research/crsp_volume_split_
adjustment.cumulative_factor, matching CRSP's dlycumfacpr on 307/307 securities) -- so dollar volume = close x volume
is right before every split and reverse split. The raw values stay in `volume_raw`, the factor in
`volume_adj_factor`; close and every other column are untouched. Days with an UNKNOWN factor (cash-payment /
partial-liquidation events, 40 securities) get NaN volume. Files whose label maps to no PERMNO are left untouched and
listed. Idempotent: a file that already has `volume_raw` is skipped. Writes are atomic (tmp + replace).
Future fetches do this at source (data_wrds.py: dlyvol x dlycumfacpr).
Not covered here (follow-up): the coarser 7D/1M/3M/6M/1Y files (a split inside a month makes an aggregated raw
volume ambiguous) -- re-derive them from the adjusted daily files before using their volume.

Usage:  python research/apply_crsp_volume_adjustment.py
Report: output/research/apply_crsp_volume_adjustment_report.parquet
Synthetic check: debug/_verify_apply_crsp_volume_adjustment.py
"""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from research.crsp_volume_split_adjustment import FACPR_PATH, LABEL_MAP_PATH, cumulative_factor

_WRDS = os.path.join("output", "cache", "wrds")
REPORT = os.path.join("output", "research", "apply_crsp_volume_adjustment_report.parquet")


def _permno_of(label: str, permno_by_label: dict):
    m = re.fullmatch(r"PERMNO(\d+)", label)
    if m:
        return int(m.group(1))
    p = permno_by_label.get(label)
    return int(p) if p is not None and pd.notna(p) else None


def _apply_compustat(path: str, label: str, root: str, rec: dict) -> dict:
    """Compustat Global (T14.7 review, 2026-10-04 -- the same bias, never fixed): files store close = prccd/ajexdi but
    volume = raw cshtrd, so pre-split dollar volume was understated (Toyota 5:1, 2021-09-29: volume 7.6M -> 34.9M on
    a continuous close). Restated volume = cshtrd x ajexdi as of each date (dollar volume = prccd x cshtrd, exact).
    ajexdi comes from the trfd fetch (output/cache/wrds/_trfd/{label}.parquet, columns trfd, ajexdi)."""
    fpath = os.path.join(root, "_trfd", f"{label}.parquet")
    if not os.path.exists(fpath):
        rec["status"] = "no_ajexdi"; return rec
    try:
        df = pd.read_parquet(path)
        fac = pd.read_parquet(fpath, columns=["ajexdi"])["ajexdi"].astype(float)
    except Exception as e:
        rec["status"] = f"unreadable: {type(e).__name__}"; return rec
    if "volume_raw" in df.columns:
        rec["status"] = "already_adjusted"; return rec
    if "volume" not in df.columns:
        rec["status"] = "no_volume"; return rec
    fac.index = pd.to_datetime(fac.index)
    fac = fac[~fac.index.duplicated(keep="last")].sort_index().replace(0, np.nan)
    f = fac.reindex(pd.to_datetime(df.index), method="ffill").to_numpy()
    raw = pd.to_numeric(df["volume"], errors="coerce")
    df["volume_raw"] = raw
    df["volume_adj_factor"] = f
    df["volume"] = raw * f
    rec["unknown_days"] = int(np.isnan(f).sum())
    rec["status"] = "adjusted_ajexdi"
    df.to_parquet(path + ".tmp")
    os.replace(path + ".tmp", path)
    return rec


def apply(root: str, events: pd.DataFrame, label_map: pd.DataFrame, extra_maps=None) -> pd.DataFrame:
    """extra_maps: further {label, permno, identity_ok} tables for labels the security master lacks (ETFs, ADRs,
    REITs -- output/cache/wrds/extra_permno_map_*.parquet, resolved by ticker as of the file's last date and VERIFIED
    by matching CRSP's adjusted close on that date); only identity_ok rows are used."""
    by_permno = {int(p): g for p, g in events.groupby("permno")}
    permno_by_label = dict(zip(label_map["label"], label_map["permno"]))
    for m in extra_maps or []:
        ok = m[m["identity_ok"].astype(bool) & m["permno"].notna()]
        permno_by_label.update(dict(zip(ok["label"], ok["permno"].astype(int))))
    paths = sorted(glob.glob(os.path.join(root, "*_1D.parquet")) + glob.glob(os.path.join(root, "_quote_only", "*_1D.parquet")))
    rows = []
    for path in paths:
        label = os.path.basename(path)[:-len("_1D.parquet")]
        rec = {"label": label, "path": os.path.relpath(path, root), "permno": None, "status": "", "unknown_days": 0}
        if label.startswith("GVKEY"):
            rows.append(_apply_compustat(path, label, root, rec)); continue
        p = _permno_of(label, permno_by_label)
        if p is None:
            rec["status"] = "unmapped"; rows.append(rec); continue
        rec["permno"] = p
        try:
            df = pd.read_parquet(path)
        except Exception as e:
            rec["status"] = f"unreadable: {type(e).__name__}"; rows.append(rec); continue
        if "volume_raw" in df.columns:
            rec["status"] = "already_adjusted"; rows.append(rec); continue
        if "volume" not in df.columns:
            rec["status"] = "no_volume"; rows.append(rec); continue
        f = cumulative_factor(pd.DatetimeIndex(pd.to_datetime(df.index)), by_permno.get(p))
        raw = pd.to_numeric(df["volume"], errors="coerce")
        df["volume_raw"] = raw
        df["volume_adj_factor"] = f
        df["volume"] = raw * f
        rec["unknown_days"] = int(np.isnan(f).sum())
        rec["status"] = "adjusted" if p in by_permno else "adjusted_no_events"
        df.to_parquet(path + ".tmp")
        os.replace(path + ".tmp", path)
        rows.append(rec)
    return pd.DataFrame(rows, columns=["label", "path", "permno", "status", "unknown_days"])


def main():
    events = pd.read_parquet(FACPR_PATH)
    label_map = pd.read_parquet(LABEL_MAP_PATH)
    extras = [pd.read_parquet(p) for p in sorted(glob.glob(os.path.join(_WRDS, "extra_permno_map_*.parquet")))]
    rep = apply(_WRDS, events, label_map, extra_maps=extras)
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    rep.to_parquet(REPORT)
    print(rep["status"].value_counts().to_string())
    print(f"days with unknown factor (volume NaN): {rep['unknown_days'].sum():,}")
    print("unmapped labels:", rep.loc[rep.status == "unmapped", "label"].tolist()[:80])
    print(f"-> {REPORT}")


if __name__ == "__main__":
    main()
