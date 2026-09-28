"""
research/relabel_wrds_by_recency_d17.py -- one-off WRDS cache relabel for code review D17 (2026-09-27).

The full-US-market label map gave a reused ticker to its OLDEST holder (see full_us_market_price_fetch.py). Files on
disk were written by two paths (data_wrds.py's S&P path resolves the ACTIVE permno; the full-market fetch used the
bad map and skipped labels already on disk), and files do not record their permno. So each file's security is
IDENTIFIED from its content: its first..last date must lie inside the listing span (first namedt .. last
nameenddt, +-10 days) of exactly ONE permno that ever used that ticker (crsp_full_security_master.parquet); holders
of a reused ticker occupy disjoint periods, so containment is unambiguous. PERMNO<n> labels identify themselves.
(A first dry run used span intersection-over-union >= 0.9: it left 6,651 files -- incl. AAPL -- unidentified,
because a fetch that starts after the listing date covers only part of the span.)
Each identified file (1D plus its derived 7D/1M/3M/6M/1Y files) is moved to its permno's label under the corrected
recency map (current holder first). Moves are two-phase (all movers to a staging dir, then placed) so label swaps
cannot overwrite each other; a second file for the same permno (duplicate) goes to the backup dir, never deleted.
Unidentified files are left in place and reported. The corrected label map is written next to the old one; the old
one is kept as full_us_market_label_map_pre_d17.parquet.
Dry run by default. Report: output/research/relabel_wrds_by_recency_d17_report.parquet.
Usage: python research/relabel_wrds_by_recency_d17.py [--apply]
"""
import argparse
import os
import shutil
import sys

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "research"))

from full_us_market_price_fetch import build_full_market_label_map

_W = os.path.join(_ROOT, "output", "cache", "wrds")
_TFS = ("1D", "7D", "1M", "3M", "6M", "1Y")


def _iou(a0, a1, b0, b1):
    inter = (min(a1, b1) - max(a0, b0)).days
    union = (max(a1, b1) - min(a0, b0)).days
    return max(inter, 0) / union if union > 0 else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    # CIZ v2 master (stksecurityinfohist, current to 2025-12-31) when present: the legacy stocknames master is frozen at
    # 2024-12-31 and lacks 2025 listings (e.g. SanDisk's 2025 spin-off holds SNDK today, not the 1995-2016 SanDisk).
    _v2 = os.path.join(_W, "crsp_full_security_master_v2.parquet")
    master = pd.read_parquet(_v2 if os.path.exists(_v2) else os.path.join(_W, "crsp_full_security_master.parquet"))
    old_map = pd.read_parquet(os.path.join(_W, "full_us_market_label_map.parquet"))
    new_map = build_full_market_label_map(master)                      # {label: permno}
    new_label = {p: l for l, p in new_map.items()}
    span = master.groupby("permno").agg(s=("namedt", "min"), e=("nameenddt", "max"), cur=("is_current", "max"))
    # A currently-listed security's open spell has nameenddt = NaT, which max() skips (AAPL's span "ended" 2007):
    # current securities' spans run to today.
    span.loc[span["cur"].astype(bool) | span["e"].isna(), "e"] = pd.Timestamp.now().normalize()
    by_ticker = master.dropna(subset=["ticker"]).groupby("ticker")["permno"].apply(lambda x: sorted(set(x))).to_dict()

    names = {e.name for e in os.scandir(_W) if e.is_file()}
    labels = sorted(n[:-len("_1D.parquet")] for n in names if n.endswith("_1D.parquet")
                    and not n.startswith("GVKEY") and n[:-len("_1D.parquet")] not in ())
    rows = []
    file_end = {}
    for lab in labels:
        if lab.startswith("GVKEY"):
            continue
        if lab.startswith("PERMNO") and lab[6:].isdigit():
            p = int(lab[6:])
            if p in span.index:
                rows.append((lab, p, 1.0, np.nan, "self"))
            continue
        cands = by_ticker.get(lab)
        if not cands:
            continue                      # not a CRSP ticker label (e.g. international/other source) -- untouched
        idx = pd.read_parquet(os.path.join(_W, f"{lab}_1D.parquet"), columns=["close"]).dropna().index
        if len(idx) == 0:
            rows.append((lab, None, np.nan, np.nan, "empty")); continue
        f0, f1 = idx.min(), idx.max()
        tol = pd.Timedelta(days=10)
        inside = [c for c in cands if c in span.index and f0 >= span.at[c, "s"] - tol and f1 <= span.at[c, "e"] + tol]
        best = max(((_iou(f0, f1, span.at[c, "s"], span.at[c, "e"]), c) for c in cands if c in span.index),
                   default=(np.nan, None))
        if len(inside) > 1:
            # A current company's permno span can also contain a dead company's period (it traded under another
            # ticker then, e.g. TPC). Tie-break on the span during which each candidate used THIS ticker.
            tsp = master[(master["ticker"] == lab) & master["permno"].isin(inside)].groupby("permno").agg(
                s=("namedt", "min"), e=("nameenddt", "max"))
            tsp["e"] = tsp["e"].fillna(pd.Timestamp.now().normalize())
            sc = sorted(((_iou(f0, f1, r.s, r.e), p) for p, r in tsp.iterrows()), reverse=True)
            if len(sc) >= 1 and sc[0][0] >= 0.5 and (len(sc) == 1 or sc[0][0] - sc[1][0] >= 0.25):
                inside = [sc[0][1]]
        if len(inside) == 1:
            rows.append((lab, int(inside[0]), best[0], np.nan, "matched"))
        else:
            rows.append((lab, None, best[0], float(len(inside)), "unidentified"))
        file_end[lab] = f1
    R = pd.DataFrame(rows, columns=["label", "permno", "iou", "n_containing", "how"])
    R["target"] = [new_label.get(p) if p is not None and not pd.isna(p) else None for p in R["permno"]]
    R["action"] = np.where(R["target"].isna(), "leave",
                           np.where(R["target"] == R["label"], "keep", "move"))
    # An unidentified file under a ticker whose new owner is CURRENTLY listed, but which ends > 1 year before the data
    # end, cannot be that owner's history (TPC: a 1992-2000 file; the owner is Tutor Perini): set aside as stale so
    # the owner can be fetched under its label.
    data_end = span["e"][~span["cur"].astype(bool)].max() if (~span["cur"].astype(bool)).any() else pd.Timestamp.now()
    cur_owner = {l: p for l, p in new_map.items() if p in span.index and bool(span.at[p, "cur"])}
    stale = (R["how"] == "unidentified") & R["label"].isin(list(cur_owner)) &         R["label"].map(lambda l: l in file_end and file_end[l] < pd.Timestamp("2025-12-31") - pd.Timedelta(days=365))
    R.loc[stale, "action"] = "stale"
    dup = R[R["permno"].notna()].duplicated("permno", keep=False)
    R.loc[dup[dup].index, "dup_permno"] = True
    os.makedirs(os.path.join(_ROOT, "output", "research"), exist_ok=True)
    R.to_parquet(os.path.join(_ROOT, "output", "research", "relabel_wrds_by_recency_d17_report.parquet"))
    print(R["how"].value_counts().to_string()); print(R["action"].value_counts().to_string())
    print("files sharing a permno with another file:", int(R.get("dup_permno", pd.Series(dtype=bool)).fillna(False).sum()))
    for t in ("A", "AAP", "TPC", "SNDK", "VSNT", "WSO", "BBBY", "P", "BLD", "KW", "CL", "ES", "AAPL", "MSFT"):
        r = R[R["label"] == t]
        print(f"  {t}: " + (r[["permno", "iou", "n_containing", "how", "target", "action"]].to_dict("records").__str__() if len(r) else "no file"))
    cur_missing = [l for l, p in new_map.items() if not l.startswith("PERMNO") and f"{l}_1D.parquet" not in names
                   and not (R["target"] == l).any()]
    print(f"new-map ticker labels with no file after relabel (never fetched): {len(cur_missing)}")

    if not args.apply:
        print("dry run -- nothing moved (use --apply)"); return
    stage = os.path.join(_W, "_stage_d17"); backup = os.path.join(_W, f"_backup_d17_{pd.Timestamp.now():%Y%m%d}")
    os.makedirs(stage, exist_ok=True); os.makedirs(backup, exist_ok=True)
    for lab in R.loc[R["action"] == "stale", "label"]:                   # stale: set aside, never deleted
        for tf in _TFS:
            f = f"{lab}_{tf}.parquet"
            if f in names:
                os.replace(os.path.join(_W, f), os.path.join(backup, f"stale_{f}"))
    movers = R[R["action"] == "move"]
    for lab in movers["label"]:                                           # phase 1: out of the way
        for tf in _TFS:
            f = f"{lab}_{tf}.parquet"
            if f in names:
                shutil.copy2(os.path.join(_W, f), os.path.join(backup, f))
                os.replace(os.path.join(_W, f), os.path.join(stage, f))
    n_dup = 0
    for lab, tgt in movers[["label", "target"]].itertuples(index=False):  # phase 2: place
        for tf in _TFS:
            f = os.path.join(stage, f"{lab}_{tf}.parquet")
            if not os.path.exists(f):
                continue
            dst = os.path.join(_W, f"{tgt}_{tf}.parquet")
            if os.path.exists(dst):                                       # same permno already under target
                os.replace(f, os.path.join(backup, f"dup_{lab}_{tf}.parquet")); n_dup += 1
            else:
                os.replace(f, dst)
    os.rmdir(stage) if not os.listdir(stage) else None
    shutil.copy2(os.path.join(_W, "full_us_market_label_map.parquet"), os.path.join(_W, "full_us_market_label_map_pre_d17.parquet"))
    pd.DataFrame([{"label": k, "permno": v} for k, v in new_map.items()]).to_parquet(
        os.path.join(_W, "full_us_market_label_map.parquet"), index=False)
    print(f"APPLIED: {len(movers)} labels moved, {n_dup} duplicate files to backup ({backup})")


if __name__ == "__main__":
    main()
