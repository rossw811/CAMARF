"""
research/split_level_breaks.py -- BUG-D118 part 2 (Ross 2026-10-15, approved): split Compustat Global daily series at
data breaks so no cointegration window or spread can span one.

After the qunit repair (research/repair_qunit.py), a one-day move larger than LEVEL_BREAK_FACTOR (5x) in a Compustat
Global total-return series is either a data error (a stitched listing -- e.g. LTCB 1998 / Shinsei 2004 under one
GVKEY -- an unadjusted odd-ratio split, a currency redenomination) or a near-wipeout; either way no equilibrium
relationship spans it. 2026-10-15 audit of the 698 jumping series: 103 explained by a qunit change; of the rest,
268 events revert within 5 days (bad prints), 181 are exact powers of 10, 958 are other permanent shifts.
  spike  (the jump and the next REVERT_DAYS days' moves sum to |x| < REVERT_TOL) -> those days' prices set to NaN
  break  (anything else)                                                         -> series split there
The pieces become separate series: the LAST segment keeps the original label (pools and identity maps point at the
current listing); earlier ones are written as <label>_seg1, _seg2, ... (they still parse to the same GVKEY, so the
same-company rule never pairs one segment with another). No rescaling of levels: that would erase a genuine -99% day.
For daily data the gap rule cannot do this (data.is_genuine_data_gap is False for daily bars unless DAILY_GAP_BREAKS).
Originals kept in output/cache/wrds/_pre_split_backup/ (never deleted). Coarser files (7D..1Y) are re-derived after.
Usage: python research/split_level_breaks.py [--dry-run] [--factor 5]
Test: debug/_verify_split_level_breaks.py
"""
import argparse
import glob
import os
import shutil

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_W = os.path.join(ROOT, "output", "cache", "wrds")
LEVEL_BREAK_FACTOR = 5.0   # the 2026-10-14 audit threshold; sensitivity at 3x and 10x (registry)
REVERT_DAYS = 5            # a bad print must revert within a trading week (registry)
REVERT_TOL = 0.5           # |log| tolerance for "reverted" (registry)
PRICE_COLS = ("open", "high", "low", "close", "close_usd", "close_total_return")


def find_breaks(px: pd.Series, factor: float = LEVEL_BREAK_FACTOR) -> dict:
    lr = np.log(px.astype(float).abs()).diff()
    lim = np.log(factor)
    breaks, spikes = [], []
    for t in lr[lr.abs() > lim].index:
        i = lr.index.get_loc(t)
        nxt = lr.iloc[i + 1:i + 1 + REVERT_DAYS]
        if len(nxt) and abs(lr.loc[t] + nxt.cumsum()).min() < REVERT_TOL:
            spikes.append(t)
        elif not any(abs((t - s).days) <= 7 for s in spikes):   # the reversal day of a spike is not a new break
            breaks.append(t)
    return {"breaks": breaks, "spikes": spikes}


def split_frame(df: pd.DataFrame, label: str, factor: float = LEVEL_BREAK_FACTOR):
    """[(label, frame)] with spikes masked and the series split at breaks; the last segment keeps `label`."""
    col = "close_total_return" if "close_total_return" in df.columns else "close"
    f = find_breaks(df[col], factor)
    out = df.copy()
    for t in f["spikes"]:
        i = out.index.get_loc(t)
        lr = np.log(out[col].astype(float).abs()).diff().iloc[i:i + 1 + REVERT_DAYS]
        k = int(np.argmin(np.abs(lr.cumsum().to_numpy())))           # last masked day: where it has reverted
        days = out.index[i:i + k]
        for c in PRICE_COLS:
            if c in out.columns:
                out.loc[days, c] = np.nan
    if not f["breaks"]:
        return [(label, out)]
    edges = [out.index[0]] + sorted(f["breaks"]) + [None]
    segs = []
    for a, b in zip(edges[:-1], edges[1:]):
        segs.append(out[(out.index >= a) & ((out.index < b) if b is not None else True)])
    n = len(segs)
    return [(f"{label}_seg{i + 1}" if i < n - 1 else label, s) for i, s in enumerate(segs)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--factor", type=float, default=LEVEL_BREAK_FACTOR)
    a = ap.parse_args()
    bak = os.path.join(_W, "_pre_split_backup")
    os.makedirs(bak, exist_ok=True)
    rows = []
    for f in sorted(glob.glob(os.path.join(_W, "GVKEY*_1D.parquet"))):
        label = os.path.basename(f)[:-len("_1D.parquet")]
        if "_seg" in label:
            continue
        df = pd.read_parquet(f); df.index = pd.to_datetime(df.index)
        segs = split_frame(df, label, a.factor)
        if len(segs) == 1 and segs[0][1].equals(df):
            continue
        rows.append({"label": label, "n_segments": len(segs), "segment_rows": ";".join(str(len(s)) for _, s in segs)})
        if a.dry_run:
            continue
        if not os.path.exists(os.path.join(bak, os.path.basename(f))):
            shutil.copy2(f, os.path.join(bak, os.path.basename(f)))
        for name, s in segs:
            out = os.path.join(_W, f"{name}_1D.parquet")
            s.to_parquet(out + ".tmp"); os.replace(out + ".tmp", out)
    R = pd.DataFrame(rows)
    R.to_parquet(os.path.join(ROOT, "output", "research", f"split_level_breaks_report{'_dry' if a.dry_run else ''}.parquet"))
    print(f"files changed: {len(R)}; split: {int((R['n_segments'] > 1).sum()) if len(R) else 0}; "
          f"new segment files: {int((R['n_segments'] - 1).sum()) if len(R) else 0}; spike-masked only: "
          f"{int((R['n_segments'] == 1).sum()) if len(R) else 0}")


if __name__ == "__main__":
    main()
