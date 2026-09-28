"""
research/apply_trfd_total_return.py -- USD total return for Compustat Global listings (2026-09-28).

CRSP legs carry close_total_return (dividends reinvested); Compustat Global legs were split-adjusted PRICE only, so
every pair with a Compustat leg ignored that leg's dividends (disclosed in the strategy-search prereg, Amendment 2).
Compustat's `trfd` (total return factor, comp_global_daily.g_secd) was verified on real data before use: the index
prccd/ajexdi*trfd adds exactly dividend/previous close on every ex-dividend day for HSBC London, Toyota and BP
(2024-25), equals the price return to 2e-16 on all other days, and captures HSBC's 2024-05 special dividend that
the divd field omits.

For each label in global_universe_manifest.parquet with a trfd file (output/cache/wrds/_trfd/<label>.parquet,
fetched through research/wrds_session_server.py job 11) and a close_usd column, writes
    close_total_return = close_usd * trfd   (trfd carried as-of to the price dates; rescaled to start at close_usd)
-- the SAME meaning as CRSP's column (USD total return), so universe_loader and pnl_dollar need no special case.
Atomic write; original columns untouched. Report: output/research/apply_trfd_total_return_report.parquet.
Usage: python research/apply_trfd_total_return.py [--limit N]
"""
import argparse
import os
import time

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_W = os.path.join(_ROOT, "output", "cache", "wrds")


def total_return_usd(close_usd: pd.Series, trfd: pd.Series) -> pd.Series:
    """close_usd * trfd (as-of, never a later factor), rescaled so the first valid value equals close_usd's."""
    f = trfd.sort_index().dropna()
    f = f[~f.index.duplicated(keep="last")].reindex(close_usd.index, method="ffill")
    tri = close_usd.astype(float) * f
    ok = tri.notna() & close_usd.notna()
    if not ok.any():
        return pd.Series(np.nan, index=close_usd.index)
    first = ok.idxmax()
    return tri * (float(close_usd.loc[first]) / float(tri.loc[first]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    man = pd.read_parquet(os.path.join(_W, "global_universe_manifest.parquet"))[["label"]].drop_duplicates()
    labels = man["label"].tolist()[: args.limit]
    rows, t0 = [], time.time()
    for i, lab in enumerate(labels, 1):
        f1, ft = os.path.join(_W, f"{lab}_1D.parquet"), os.path.join(_W, "_trfd", f"{lab}.parquet")
        if not (os.path.exists(f1) and os.path.exists(ft)):
            rows.append((lab, "missing_file", np.nan)); continue
        df = pd.read_parquet(f1)
        if "close_usd" not in df.columns or not df["close_usd"].notna().any():
            rows.append((lab, "no_close_usd", np.nan)); continue
        tr = total_return_usd(df["close_usd"].astype(float), pd.read_parquet(ft)["trfd"])
        df["close_total_return"] = tr.to_numpy()
        df.to_parquet(f1 + ".tmp")
        os.replace(f1 + ".tmp", f1)
        v, p = tr.dropna(), df["close_usd"].dropna()
        gap = float(v.iloc[-1] / v.iloc[0] / (p.iloc[-1] / p.iloc[0]) - 1) if len(v) > 1 and len(p) > 1 else np.nan
        rows.append((lab, "ok", gap))
        if i % 2000 == 0:
            print(f"{i}/{len(labels)} ({time.time() - t0:.0f}s)", flush=True)
    R = pd.DataFrame(rows, columns=["label", "status", "tr_over_price_total_gap"])
    R.to_parquet(os.path.join(_ROOT, "output", "research", "apply_trfd_total_return_report.parquet"))
    print(R["status"].value_counts().to_string())
    ok = R[R.status == "ok"]
    print(f"median lifetime TR-over-price gap: {ok.tr_over_price_total_gap.median():+.1%}; "
          f"negative gaps (dividends cannot make TR < price): {(ok.tr_over_price_total_gap < -1e-9).sum()}")


if __name__ == "__main__":
    main()
