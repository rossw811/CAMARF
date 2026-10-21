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
Amendment 5 (2026-10-21): moves are measured between consecutive VALID prices (a hole of NaN rows hid a 15x move), and
every label is rebuilt from its original (`rebuild_label`), pre-seal rows only; residual > 5x files are reported.
Usage: python research/split_level_breaks.py [--dry-run] [--factor 5]
Test: debug/_verify_split_level_breaks.py
"""
import argparse
import glob
import os
import shutil

import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import seal  # noqa: E402
from config import Config  # noqa: E402
_W = os.path.join(ROOT, "output", "cache", "wrds")
LEVEL_BREAK_FACTOR = 5.0   # the 2026-10-14 audit threshold; sensitivity at 3x and 10x (registry)
REVERT_DAYS = 5            # a bad print must revert within a trading week (registry)
REVERT_TOL = 0.5           # |log| tolerance for "reverted" (registry)
PRICE_COLS = ("open", "high", "low", "close", "close_usd", "close_total_return")


def _valid(px: pd.Series) -> pd.Series:
    """Valid prices only (finite, non-zero). Amendment 5 (2026-10-21): moves are measured between CONSECUTIVE VALID
    prices -- diff() over the raw column is NaN across NaN rows, so a jump behind a hole was never compared (real case
    GVKEY015736: 175.88 -> 11.56 across an 810-day hole)."""
    px = px.astype(float)
    return px[np.isfinite(px) & (px.abs() > 0)]


def find_breaks(px: pd.Series, factor: float = LEVEL_BREAK_FACTOR) -> dict:
    lr = np.log(_valid(px).abs()).diff()
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
    """[(label, frame)] with spikes masked and the series split at breaks; the last segment keeps `label`. A break is
    dated at the first valid bar after the jump; the hole's NaN rows stay in the earlier segment."""
    col = "close_total_return" if "close_total_return" in df.columns else "close"
    f = find_breaks(df[col], factor)
    out = df.copy()
    for t in f["spikes"]:
        v = _valid(out[col])
        i = v.index.get_loc(t)
        lr = np.log(v.abs()).diff().iloc[i:i + 1 + REVERT_DAYS]
        k = int(np.argmin(np.abs(lr.cumsum().to_numpy())))           # last masked day: where it has reverted
        days = v.index[i:i + k]
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


def rebuild_label(label: str, wdir: str = _W, dry_run: bool = False, factor: float = LEVEL_BREAK_FACTOR) -> dict:
    """Re-segment one label from its ORIGINAL series (the pre-split backup when one exists, else the current file):
    pre-seal rows only (sealed rows stay with the label in the vault, seal.py), stale `<label>_segN` files removed,
    pieces written through seal.write_parquet. Idempotent."""
    bak = os.path.join(wdir, "_pre_split_backup")
    cur = os.path.join(wdir, f"{label}_1D.parquet")
    src = os.path.join(bak, f"{label}_1D.parquet")
    src = src if os.path.exists(src) else cur
    df = pd.read_parquet(src)
    df.index = pd.to_datetime(df.index)
    df = df[df.index < pd.Timestamp(Config.DATA.SEALED_FROM)]
    segs = split_frame(df, label, factor)
    stale = sorted(glob.glob(os.path.join(wdir, f"{glob.escape(label)}_seg[0-9]*_1D.parquet")))
    plan = {"label": label, "source": "backup" if src != cur else "current", "n_segments": len(segs),
            "segment_rows": ";".join(str(len(x)) for _, x in segs), "stale_segments_removed": len(stale)}
    if dry_run:
        return plan
    if src == cur and (len(segs) > 1 or not segs[0][1].equals(df)):
        os.makedirs(bak, exist_ok=True)
        shutil.copy2(cur, os.path.join(bak, os.path.basename(cur)))
    for f in stale:
        os.remove(f)
    for name, x in segs:
        if len(x):
            seal.write_parquet(x, os.path.join(wdir, f"{name}_1D.parquet"))
    return plan


def residual_jumps(wdir: str = _W, factor: float = LEVEL_BREAK_FACTOR) -> pd.DataFrame:
    """Every GVKEY daily file (segments included) that still has a > factor move between consecutive valid prices."""
    rows = []
    for f in sorted(glob.glob(os.path.join(wdir, "GVKEY*_1D.parquet"))):
        d = pd.read_parquet(f)
        col = "close_total_return" if "close_total_return" in d.columns else "close"
        lr = np.log(_valid(d[col]).abs()).diff().abs()
        if len(lr) and lr.max() > np.log(factor):
            rows.append({"file": os.path.basename(f), "max_move": float(np.exp(lr.max())), "n_valid": int(lr.size + 1)})
    return pd.DataFrame(rows)


def quarantine_residuals(wdir: str, J: pd.DataFrame, qname: str = "_quarantine_d118_a5") -> int:
    """Files still holding a > factor move after splitting (Amendment 4 moved its 20 by hand) go to
    <wdir>/<qname>/ (never deleted); returns the number moved."""
    if J is None or not len(J):
        return 0
    q = os.path.join(wdir, qname)
    os.makedirs(q, exist_ok=True)
    for f in J["file"]:
        os.replace(os.path.join(wdir, f), os.path.join(q, f))
    return len(J)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--factor", type=float, default=LEVEL_BREAK_FACTOR)
    a = ap.parse_args()
    bak = os.path.join(_W, "_pre_split_backup")
    labels = {os.path.basename(f)[:-len("_1D.parquet")] for f in glob.glob(os.path.join(_W, "GVKEY*_1D.parquet"))}
    labels |= {os.path.basename(f)[:-len("_1D.parquet")] for f in glob.glob(os.path.join(bak, "GVKEY*_1D.parquet"))}
    labels = sorted(x for x in labels if "_seg" not in x)
    rows = [rebuild_label(x, _W, a.dry_run, a.factor) for x in labels]
    R = pd.DataFrame(rows)
    R.to_parquet(os.path.join(ROOT, "output", "research", f"split_level_breaks_report{'_dry' if a.dry_run else ''}.parquet"))
    print(f"labels: {len(R)}; split: {int((R['n_segments'] > 1).sum())}; segment files: "
          f"{int((R['n_segments'] - 1).sum())}; stale segment files removed: {int(R['stale_segments_removed'].sum())}")
    if not a.dry_run:
        J = residual_jumps(_W, a.factor)
        J.to_parquet(os.path.join(ROOT, "output", "research", "split_level_breaks_residual.parquet"))
        n_q = quarantine_residuals(_W, J)
        left = len(residual_jumps(_W, a.factor))
        print(f"residual files with a > {a.factor:g}x move between consecutive valid prices: {len(J)} "
              f"(quarantined to {_W}/_quarantine_d118_a5); after quarantine: {left}")
        if left:
            raise SystemExit(f"{left} files still hold a > {a.factor:g}x move -- STOP")


if __name__ == "__main__":
    main()
