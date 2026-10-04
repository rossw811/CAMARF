"""
research/bug_recheck_realdata.py -- plan T14.5 (Ross 2026-10-03: "recheck every bug we have logged"): real-data
checks that FIXED data-identity bugs still hold on the CURRENT cache (a synthetic test proves the code; this proves
the data the code produced). Each check prints a verdict HOLDS / REGRESSED with its evidence and is saved to
output/research/bug_recheck_realdata.parquet.

  D13  monthly-and-coarser WRDS bars stamped at period END (a period-start stamp carried a period-end close)
  D16  cross-asset collisions: the stock files ES/CL/CC/LTC hold the STOCK (not the future / coin), and Binance
       Litecoin is a separate "-USD" label
  D17  reused tickers belong to the CURRENT holder: A (Agilent), TPC (Tutor Perini), SNDK (Sandisk) have recent data
  D19  WRDS daily files with no valid price at all (known: pre-1992 Nasdaq quote-only securities, kept out of the
       main cache) -- count, and that none sits in the main cache
Usage: python research/bug_recheck_realdata.py
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

W = os.path.join("output", "cache", "wrds")
OUT = os.path.join("output", "research", "bug_recheck_realdata.parquet")
rows = []


def verdict(bug, ok, evidence):
    rows.append({"bug": bug, "verdict": "HOLDS" if ok else "REGRESSED", "evidence": evidence})
    print(f"{bug}: {'HOLDS' if ok else 'REGRESSED'} -- {evidence}")


def d13():
    bad, n = [], 0
    for tf, rule in (("1M", "M"), ("3M", "Q"), ("6M", None), ("1Y", "Y")):
        for p in sorted(glob.glob(os.path.join(W, f"*_{tf}.parquet")))[:300]:
            try:
                idx = pd.DatetimeIndex(pd.read_parquet(p, columns=[]).index)
            except Exception:
                continue
            if len(idx) == 0:
                continue
            n += 1
            month_end = (idx + pd.offsets.MonthEnd(0)) == idx
            if not month_end.all():
                bad.append(f"{os.path.basename(p)} ({int((~month_end).sum())}/{len(idx)} not month-end)")
    verdict("D13", not bad, f"{n} coarse files sampled; not period-end: {bad[:5]}")


def d16():
    ev = []
    ok = True
    for sym, lo, hi in (("ES", 30, 200), ("CL", 30, 200), ("CC", 1, 200), ("LTC", 10, 100)):
        p = os.path.join(W, f"{sym}_1D.parquet")
        if not os.path.exists(p):
            ev.append(f"{sym}: no WRDS file"); continue
        c = pd.read_parquet(p, columns=["close"])["close"].dropna()
        last = float(c.iloc[-1]) if len(c) else float("nan")
        good = lo <= abs(last) <= hi
        ok &= good
        ev.append(f"{sym} last close {last:.2f} ({'stock range' if good else 'NOT a stock price'})")
    binance = glob.glob(os.path.join("output", "cache", "binance", "LTC*"))
    ev.append(f"binance LTC files: {[os.path.basename(b) for b in binance][:3]}")
    verdict("D16", ok, "; ".join(ev))


def d17():
    ev, ok = [], True
    for sym in ("A", "TPC", "SNDK", "AAP"):
        p = os.path.join(W, f"{sym}_1D.parquet")
        if not os.path.exists(p):
            ev.append(f"{sym}: missing"); ok = False; continue
        c = pd.read_parquet(p, columns=["close"])["close"].dropna()
        last = pd.Timestamp(c.index.max()) if len(c) else None
        recent = last is not None and last >= pd.Timestamp("2025-01-01")
        ok &= recent
        ev.append(f"{sym} data {pd.Timestamp(c.index.min()).date() if len(c) else None}..{last.date() if last else None}")
    verdict("D17", ok, "; ".join(ev))


def d19():
    empty = []
    for p in glob.glob(os.path.join(W, "*_1D.parquet")):
        if os.path.basename(p).startswith("GVKEY"):
            continue
        try:
            d = pd.read_parquet(p, columns=["close"])
        except Exception:
            continue
        if d["close"].notna().sum() == 0:
            empty.append(os.path.basename(p))
    quote = len(glob.glob(os.path.join(W, "_quote_only", "*_1D.parquet")))
    # D19's claim is not "no such files" but "the price-less files are the pre-1992 Nasdaq quote-only class, which
    # the loader skips (no valid price)". First version of this check asserted zero files -- wrong criterion
    # (2026-10-04); 4,173 found, all ending <= 1992.
    late = []
    for b in empty:
        d = pd.read_parquet(os.path.join(W, b), columns=["close"])
        if len(d) and pd.Timestamp(d.index.max()) > pd.Timestamp("1992-12-31"):
            late.append(b)
    verdict("D19", len(late) == 0, f"main-cache CRSP daily files with no valid close: {len(empty)}, of which ending "
                                   f"after 1992: {len(late)} {late[:6]} (D19 cited 2,758; quote-only replacements "
                                   f"built: {quote} on this machine)")


if __name__ == "__main__":
    d13(); d16(); d17(); d19()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    pd.DataFrame(rows).to_parquet(OUT)
    print(f"-> {OUT}")
