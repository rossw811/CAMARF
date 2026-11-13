"""
Fetch the eight P2 share-class legs that have no content-verified WRDS file, by PERMNO (2026-11-13; Ross took the
recommendation to bring Berkshire A back). Two steps, so the cache only changes after checks:

  fetch   (Ross, interactive WRDS login; any machine):  python debug/_tmp_fetch_p2_missing_permnos_20261113.py fetch
          -> output/cache/_staging_p2_permnos_20261113/PERMNO<n>_1D.parquet (+ manifest.csv). Uses
             data_wrds.fetch_symbols_bulk (the cache's own split / total-return construction). Touches nothing else.
  install (CachyOS, no login):  python debug/_tmp_fetch_p2_missing_permnos_20261113.py install
          checks per file: (1) no existing file under that label in the cache or vault; (2) dates inside the PERMNO's
          CRSP listing life; (3) NOT the same series as the sibling class's verified file (the bug that dropped these
          pairs: two labels, one series); (4) >= 250 valid bars. Then seal.write_parquet into output/cache/wrds and
          rows appended to wrds_label_permno_final.parquet (source "fetched_by_permno_20261113"; a backup is kept).
          Any failed check stops before anything is written.
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))

# missing leg -> its verified sibling (debug/_tmp_p2_label_map_impact_20261113.py, CachyOS cache)
MISSING = {41217: 10294, 12254: 69201, 17778: 83443, 81073: 23505, 89303: 26710, 33340: 33321, 80169: 80168,
           85344: 85343}
STAGE = os.path.join(ROOT, "output", "cache", "_staging_p2_permnos_20261113")
CACHE = os.path.join(ROOT, "output", "cache", "wrds")
SOURCE = "fetched_by_permno_20261113"


def fetch():
    import data_wrds
    os.makedirs(STAGE, exist_ok=True)
    db = data_wrds._connect()
    try:
        rows = []
        for sym, df in data_wrds.fetch_symbols_bulk(db, {f"PERMNO{p}": p for p in MISSING}):
            df.to_parquet(os.path.join(STAGE, f"{sym}_1D.parquet"))
            c = df["close_total_return"].dropna()
            rows.append({"label": sym, "rows": len(df), "first": c.index.min(), "last": c.index.max()})
            print(sym, len(df), c.index.min(), c.index.max(), flush=True)
        pd.DataFrame(rows).to_csv(os.path.join(STAGE, "manifest.csv"), index=False)
        print(f"{len(rows)} of {len(MISSING)} PERMNOs fetched -> {STAGE}")
    finally:
        db.close()


def install():
    import parquet_io
    import seal
    from data_wrds import LABEL_PERMNO_MAP_PATH, label_permno_map
    from p2_share_class_family import leg_label, permno_labels
    names = parquet_io.read_parquet(os.path.join(CACHE, "crsp_stocknames_all.parquet"))
    by_p = permno_labels(CACHE)
    vmap = label_permno_map()
    ok, todo = True, []
    for p, sib in MISSING.items():
        lab = f"PERMNO{p}"
        f = os.path.join(STAGE, f"{lab}_1D.parquet")
        if not os.path.exists(f):
            print(f"{lab}: not fetched -- skipped"); continue
        df = pd.read_parquet(f)
        tr = df["close_total_return"].dropna()
        tr = tr[tr > 0]
        n = names[names["permno"] == p]
        life = (pd.Timestamp(n["namedt"].min()), pd.Timestamp(n["nameenddt"].max()) + pd.DateOffset(years=1))
        target = os.path.join(CACHE, f"{lab}_1D.parquet")
        free = not os.path.exists(target) and not os.path.exists(seal.vault_path(target)) and lab not in vmap
        inside = len(tr) and tr.index.min() >= life[0] and tr.index.max() <= life[1]
        sl = leg_label(CACHE, by_p[sib])
        s = pd.read_parquet(os.path.join(CACHE, f"{sl}_1D.parquet"))["close_total_return"]
        j = pd.concat([np.log(tr), np.log(s[s > 0])], axis=1, join="inner").dropna()
        same = len(j) > 30 and float((j.iloc[:, 0] - j.iloc[:, 1]).diff().abs().max()) < 1e-12
        enough = len(tr) >= 250
        print(f"{lab}: rows {len(df)} valid {len(tr)} {tr.index.min().date() if len(tr) else None}.."
              f"{tr.index.max().date() if len(tr) else None}; label free {free}; inside listing life {bool(inside)}; "
              f"identical to sibling {sl} {same} (overlap {len(j)}); >= 250 bars {enough}")
        if not (free and inside and not same and enough):
            ok = False
        todo.append((lab, p, df, target))
    if not ok:
        print("CHECK FAILED -- nothing written"); sys.exit(1)
    m = parquet_io.read_parquet(LABEL_PERMNO_MAP_PATH)
    m.to_parquet(LABEL_PERMNO_MAP_PATH.replace(".parquet", "_before_20261113.parquet"))
    for lab, p, df, target in todo:
        seal.write_parquet(df, target)
    add = pd.DataFrame({"label": [t[0] for t in todo], "permno": [float(t[1]) for t in todo], "source": SOURCE,
                        "return_scores": ""})
    pd.concat([m, add[m.columns]], ignore_index=True).to_parquet(LABEL_PERMNO_MAP_PATH, index=False)
    print(f"installed {len(todo)} files; label map {len(m)} -> {len(m) + len(add)} rows (backup *_before_20261113)")


if __name__ == "__main__":
    {"fetch": fetch, "install": install}[sys.argv[1]]()
