"""
research/purity_pit_eligibility.py -- point-in-time eligibility for the Purity pair pool (2026-09-27, Design 2,
Ross-approved; fixes code review S3 and tightens R1.6).

S3: episodic_pairs_adapter.py assembled the pool from every FDR-rejected window up to the BUILD date, and
backtest.py then traded each pair over its whole history -- a pair-level selection lookahead (each window was
point-in-time; the pool was not). R1.6: 81% of confirmed pairs rest on a single rejected window, bounding the
pair-level FDR at ~9.1% rather than 5%.

For each pool pair this computes eligible_from = window_end_date of its k-th BH-rejected Tier-3 window (the
first date the pair could have been known to be confirmed k times), from the Tier-3 per-window files
(daily WRDS scan + intraday 1h/4h scans). backtest.py refuses entries before eligible_from. Two arms:
  k = 1 : current rule, now point-in-time;
  k = 2 : >= 2 rejected windows required (Ross-approved stricter arm).
Pool pairs with no rejected window in the Tier-3 files are REPORTED (not silently kept).

Outputs: output/research/purity_pairs_pit_k1.parquet, purity_pairs_pit_k2.parquet, and a coverage report.
Verified first: debug/_verify_purity_pit_eligibility.py.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config

_TIER3 = {
    "1D": os.path.join("output", "research", "wrds_deep_history_episodic_scan_tier3_windows.parquet"),
    "1h": os.path.join("output", "research", "intraday_episodic_scan_1h_tier3_windows.parquet"),
    "4h": os.path.join("output", "research", "intraday_episodic_scan_4h_tier3_windows.parquet"),
}


def kth_rejection_dates(windows: pd.DataFrame, k: int) -> pd.DataFrame:
    """Per unordered pair: the window_end_date of its k-th FDR-rejected window (chronological), plus the
    total number of rejected windows. Pairs with fewer than k rejections are absent from the result."""
    w = windows[windows["fdr_rejected"].astype(bool)].copy()
    w["window_end_date"] = pd.to_datetime(w["window_end_date"])
    a, b = w["symbol_a"].astype(str), w["symbol_b"].astype(str)
    w["key_a"], w["key_b"] = a.where(a <= b, b), b.where(a <= b, a)
    w = w.sort_values(["key_a", "key_b", "window_end_date"])
    w["rank"] = w.groupby(["key_a", "key_b"]).cumcount() + 1
    n = w.groupby(["key_a", "key_b"]).size().rename("n_rejected")
    kth = w[w["rank"] == k].set_index(["key_a", "key_b"])["window_end_date"].rename("eligible_from")
    return pd.concat([kth, n], axis=1).dropna(subset=["eligible_from"]).reset_index()


def _bh_cutoff(sorted_p: np.ndarray, alpha: float) -> float:
    """Benjamini-Hochberg step-up cutoff on ascending p-values: reject every p <= the returned value (-1 if none)."""
    m = sorted_p.size
    if m == 0:
        return -1.0
    ok = np.flatnonzero(sorted_p <= alpha * np.arange(1, m + 1) / m)
    return float(sorted_p[ok[-1]]) if ok.size else -1.0


def pit_kth_rejection_dates(windows: pd.DataFrame, k: int, alpha: float = None) -> pd.DataFrame:
    """Point-in-time eligibility (plan S32, Ross 2026-10-10). At each month-end T, BH over the windows concluded by T
    (window_end_date <= T); a pair's eligible_from is the first month-end at which >= k of its windows are rejected
    under that as-of family. The whole-history fdr_rejected flag used before let windows ending later decide whether
    an early window counted (lookahead). Month-end evaluation is conservative (up to a month late), never early.
    Returns key_a, key_b, eligible_from, n_rejected (as of the last month-end). debug/_verify_pit_bh_eligibility.py"""
    alpha = Config.STATS.FDR_ALPHA if alpha is None else alpha
    w = windows[["symbol_a", "symbol_b", "window_end_date", "pvalue"]].copy()
    w["window_end_date"] = pd.to_datetime(w["window_end_date"])
    w = w.dropna(subset=["window_end_date", "pvalue"]).sort_values("window_end_date").reset_index(drop=True)
    a, b = w["symbol_a"].astype(str), w["symbol_b"].astype(str)
    w["key_a"], w["key_b"] = a.where(a <= b, b), b.where(a <= b, a)
    codes, uniq = pd.factorize(pd.Series(list(zip(w["key_a"], w["key_b"]))))
    ends = w["window_end_date"].to_numpy()
    p = w["pvalue"].to_numpy(dtype=float)
    months = pd.date_range(w["window_end_date"].min(), w["window_end_date"].max() + pd.offsets.MonthEnd(0), freq="ME")
    first = np.full(len(uniq), np.datetime64("NaT"), dtype="datetime64[ns]")
    last_count = np.zeros(len(uniq), dtype=int)
    for T in months:
        n = int(np.searchsorted(ends, np.datetime64(T), side="right"))
        if n == 0:
            continue
        cut = _bh_cutoff(np.sort(p[:n]), alpha)
        rej = p[:n] <= cut
        counts = np.bincount(codes[:n][rej], minlength=len(uniq))
        new = (counts >= k) & np.isnat(first)
        first[new] = np.datetime64(T)
        last_count = counts
    keep = ~np.isnat(first)
    return pd.DataFrame({"key_a": [uniq[i][0] for i in np.flatnonzero(keep)],
                         "key_b": [uniq[i][1] for i in np.flatnonzero(keep)],
                         "eligible_from": pd.to_datetime(first[keep]),
                         "n_rejected": last_count[keep]})


def attach_eligibility(pool: pd.DataFrame, windows_by_tf: dict, k: int):
    out, missing = [], []
    for tf, g in pool.groupby("tf_label"):
        w = windows_by_tf.get(tf)
        if w is None:
            missing.append((tf, len(g), "no tier-3 file")); continue
        e = pit_kth_rejection_dates(w, k)   # S32 (2026-10-10): point-in-time BH family, not the whole-history flag
        g = g.copy()
        a, b = g["symbol_a"].astype(str), g["symbol_b"].astype(str)
        g["key_a"], g["key_b"] = a.where(a <= b, b), b.where(a <= b, a)
        m = g.merge(e, on=["key_a", "key_b"], how="left")
        n_miss = int(m["eligible_from"].isna().sum())
        if n_miss:
            missing.append((tf, n_miss, f"fewer than {k} rejected windows / not in tier-3 file"))
        out.append(m.dropna(subset=["eligible_from"]).drop(columns=["key_a", "key_b"]))
    res = pd.concat(out, ignore_index=True) if out else pool.iloc[0:0]
    return res, missing


def main():
    pool = pd.read_parquet(os.path.join("output", "research", "purity_pairs.parquet"))
    windows = {}
    for tf, path in _TIER3.items():
        if os.path.exists(path):
            windows[tf] = pd.read_parquet(path, columns=["symbol_a", "symbol_b", "window_end_date", "pvalue"])
    for k in (1, 2):
        res, missing = attach_eligibility(pool, windows, k)
        path = os.path.join("output", "research", f"purity_pairs_pit_k{k}.parquet")
        res.to_parquet(path)
        print(f"k={k}: {len(res)} of {len(pool)} pairs eligible -> {path}")
        for tf, n, why in missing:
            print(f"   excluded tf={tf}: {n} ({why})")
        if len(res):
            ef = pd.to_datetime(res["eligible_from"])
            print(f"   eligible_from range {ef.min().date()} .. {ef.max().date()}; median {ef.median().date()}; "
                  f"by year: {ef.dt.year.value_counts().sort_index().to_dict()}")


if __name__ == "__main__":
    main()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from pipeline_stages import stage
    stage("pit_eligibility").record()  # lineage (research/pipeline_stages.py)
