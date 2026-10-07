"""
research/repair_coarse_identity.py -- coarse WRDS files that belong to a DIFFERENT security than their label's daily
file (found 2026-10-07 by rederive_coarse_volume.py's raw-volume guard: PAR_{7D,1M,3M,6M,1Y} carry another
security -- 1M closes ~$174 at 2025-12 -- while PAR_1D is PAR Technology, PERMNO 61146, the identity both label maps
give, closing ~$36; the daily file was rewritten by the 2026-10-03 full-market fetch, the coarse files are older).

Detection: a label is MISMATCHED when its 3M bar closes agree with the daily file's last close of the same quarter
(rtol 1e-3) on < 50% of overlapping bars. 3M is used because it is derived from daily at fetch time, so a genuine
file agrees ~100% (2857/2858 labels >= 99% on 2026-10-07; the 1M native file legitimately differs in months whose
last day had no trade -- the monthly price is then CRSP's bid/ask midpoint -- so 1M is not used to judge).
Repair: move the label's coarse files to output/cache/wrds/_quarantine_identity_<date>/ (never deleted); rebuild
7D/3M/6M/1Y from the daily file (data_wrds.resample_daily_to on raw volume, then rederive_coarse_volume.restate_coarse
-> same schema as every restated coarse file). 1M is NOT rebuilt: it is CRSP native monthly and needs a msf_v2
refetch for the right PERMNO (next WRDS session) -- until then the label has no 1M file.
Usage:  python research/repair_coarse_identity.py [--dry-run]
Synthetic check: debug/_verify_repair_coarse_identity.py
"""
import glob
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from period_bars import period_end_index, resample_to_period_end
from research.rederive_coarse_volume import restate_coarse

_WRDS = os.path.join("output", "cache", "wrds")
DERIVED = ("7D", "3M", "6M", "1Y")
COARSE = ("7D", "1M", "3M", "6M", "1Y")
AGREE_MIN = 0.5


def close_agreement(daily: pd.DataFrame, coarse: pd.DataFrame, tf: str) -> float:
    d = daily["close"].abs().dropna()
    last = d.groupby(period_end_index(d.index, tf)).last().reindex(pd.DatetimeIndex(coarse.index))
    c = coarse["close"]
    both = c.notna().to_numpy() & last.notna().to_numpy()
    if not both.any():
        return float("nan")
    return float(np.isclose(c.to_numpy()[both], last.to_numpy()[both], rtol=1e-3).mean())


def find_mismatched(root: str) -> list:
    out = []
    for p in sorted(glob.glob(os.path.join(root, "*_3M.parquet"))):
        label = os.path.basename(p)[:-len("_3M.parquet")]
        dp = os.path.join(root, f"{label}_1D.parquet")
        if not os.path.exists(dp):
            continue
        a = close_agreement(pd.read_parquet(dp, columns=["close"]), pd.read_parquet(p, columns=["close"]), "3M")
        if a < AGREE_MIN:
            out.append((label, a))
    return out


def rebuild(root: str, label: str, qdir: str) -> dict:
    os.makedirs(qdir, exist_ok=True)
    moved = []
    for tf in COARSE:
        p = os.path.join(root, f"{label}_{tf}.parquet")
        if os.path.exists(p):
            os.replace(p, os.path.join(qdir, os.path.basename(p)))
            moved.append(tf)
    daily = pd.read_parquet(os.path.join(root, f"{label}_1D.parquet"))
    raw_daily = daily.assign(volume=daily["volume_raw"]) if "volume_raw" in daily.columns else daily
    keep = [c for c in ("open", "high", "low", "close", "volume", "close_total_return", "close_usd") if c in raw_daily]
    built = []
    for tf in DERIVED:
        coarse = resample_to_period_end(raw_daily[keep], tf)
        if coarse.empty:
            continue
        if "volume_raw" in daily.columns:
            coarse, _ = restate_coarse(daily, coarse, tf)
        coarse.to_parquet(os.path.join(root, f"{label}_{tf}.parquet.tmp"))
        os.replace(os.path.join(root, f"{label}_{tf}.parquet.tmp"), os.path.join(root, f"{label}_{tf}.parquet"))
        built.append(tf)
    return {"label": label, "quarantined": moved, "rebuilt": built}


def main():
    bad = find_mismatched(_WRDS)
    print(f"labels whose 3M closes disagree with their daily file on >= {1 - AGREE_MIN:.0%} of bars: {bad}")
    if "--dry-run" in sys.argv or not bad:
        return
    qdir = os.path.join(_WRDS, f"_quarantine_identity_{time.strftime('%Y%m%d')}")
    for label, _ in bad:
        print(rebuild(_WRDS, label, qdir))
    print(f"quarantined files -> {qdir}; 1M not rebuilt (needs a CRSP msf_v2 refetch for the right PERMNO)")


if __name__ == "__main__":
    main()
