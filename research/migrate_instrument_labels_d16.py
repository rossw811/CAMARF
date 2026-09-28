"""
research/migrate_instrument_labels_d16.py -- one-off cache migration for code review D16 (2026-09-27).

data.py now labels crypto "<SYM>-USD" and futures/commodities "<SYM>=F" (instrument_labels.py). Existing DataStore
files (output/cache/{SYM}_{tf}.parquet) still use the bare root. This moves each crypto/futures/commodity file to its
namespaced name. For the four roots that are ALSO stock tickers (CL, ES, CC, LTC) a file may hold either instrument
(whichever wrote last), so each file is classified against the WRDS stock series for that ticker:
  stock  <- on the most recent 250 overlapping days, >= 80% of daily returns agree within 0.5% and the median
            level gap is < 15% (a loose sanity bound: yfinance auto_adjust's dividend adjustment alone puts a
            high-yield stock ~5-7% apart from WRDS's split-only close over a year) -- the file stays under the bare
            (equity) label. Two dry runs corrected the rule (level test on the full history: decades of dividend
            adjustment = 40-60% gap; Pearson corr dominated by a few glitch days).
Derived coarse files (7day/1mo/3mo/6mo) are built from the 1day file, so they follow its decision.
  other  <- otherwise -- the file moves to the namespaced label (it is the crypto / future).
Files with < 5 overlapping days are left in place and reported as "undetermined". Roots that are not equities in
the current universe cannot have been written as a stock under the bare label, so their files simply move.
Dry run by default (prints every decision); --apply moves files after copying each to
output/cache/_backup_d16_<date>/. Report: output/research/migrate_instrument_labels_d16_report.parquet.
Usage: python research/migrate_instrument_labels_d16.py [--apply]
"""
import argparse
import os
import re
import shutil
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from instrument_labels import instrument_label

_CACHE = Config.DATA.CACHE_DIR
_WRDS = os.path.join("output", "cache", "wrds")


def _daily_close(df):
    c = df["close"].astype(float).dropna()
    c = c[c > 0]
    return c.groupby(c.index.normalize()).last()


def _classify(path, stock):
    return _classify_series(_daily_close(pd.read_parquet(path, columns=["close"])), stock)


def _classify_series(d, stock):
    common = d.index.intersection(stock.index)
    if len(common) < 5:
        return "undetermined", len(common), np.nan, np.nan
    common = common[-250:]
    ratio = float(np.median(np.abs(d.loc[common] / stock.loc[common] - 1)))
    r1, r2 = np.log(d.loc[common]).diff(), np.log(stock.loc[common]).diff()
    ok = r1.notna() & r2.notna()
    agree = float((np.abs(r1[ok] - r2[ok]) < 0.005).mean()) if ok.sum() >= 3 else np.nan
    # a median level gap < 3% is decisive on its own (another instrument cannot track a stock's price level that
    # closely for weeks); illiquid minute bars' last print differs from the close, which lowers agreement.
    is_stock = ratio < 0.03 or (ratio < 0.15 and (np.isnan(agree) or agree >= 0.8))
    return ("stock" if is_stock else "other"), len(common), ratio, agree


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    backup = os.path.join(_CACHE, f"_backup_d16_{pd.Timestamp.now():%Y%m%d}")
    classes = [(s, "crypto") for s in Config.UNIVERSE.CRYPTO] + \
              [(s, "commodity") for s in Config.UNIVERSE.COMMODITIES] + [(s, "futures") for s in Config.UNIVERSE.FUTURES]
    from data import UniverseBuilder
    equity_roots = {s for s, c in UniverseBuilder()._build_raw_list() if c in ("equity", "etf", "equity_intl")}
    names = sorted(e.name for e in os.scandir(_CACHE) if e.is_file() and e.name.endswith(".parquet"))
    rows = []
    for root, cls in classes:
        label = instrument_label(root, cls)
        pat = re.compile(rf"^{re.escape(root)}_([0-9a-z]+)\.parquet$")
        files = [n for n in names if pat.match(n)]
        stock = None
        wp = os.path.join(_WRDS, f"{root}_1D.parquet")
        # Only roots that are ALSO equities in the current universe could have been written as a stock under the
        # bare label; other WRDS files with the same ticker are different (historical) companies never fetched here.
        if root in equity_roots and os.path.exists(wp):
            w = pd.read_parquet(wp)
            stock = _daily_close(w[["close"]])
            yfp = os.path.join(_CACHE, f"{root}_1day.parquet")   # extends the reference past WRDS's last date
            if os.path.exists(yfp):
                y = _daily_close(pd.read_parquet(yfp, columns=["close"]))
                common = y.index.intersection(stock.index)
                if _classify_series(y, stock)[0] == "stock":
                    stock = pd.concat([stock, y[y.index > stock.index.max()]])
        day_decision = None
        for n in sorted(files, key=lambda f: pat.match(f).group(1) != "1day"):   # 1day first
            tf = pat.match(n).group(1)
            if stock is not None and tf in ("7day", "1mo", "3mo", "6mo") and day_decision is not None:
                decision, nov, ratio, corr = day_decision, 0, np.nan, np.nan   # derived from the 1day file
            elif stock is None:
                decision, nov, ratio, corr = "other", 0, np.nan, np.nan   # no stock with this ticker: not a collision
            else:
                decision, nov, ratio, corr = _classify(os.path.join(_CACHE, n), stock)
            if tf == "1day":
                day_decision = decision
            dst = f"{label}_{tf}.parquet"
            rows.append({"root": root, "class": cls, "file": n, "decision": decision, "overlap_days": nov,
                         "median_level_dev": ratio, "return_agreement": corr,
                         "action": f"move -> {dst}" if decision == "other" else "keep (stock)" if decision == "stock"
                         else "leave (undetermined)"})
            if args.apply and decision == "other":
                src = os.path.join(_CACHE, n)
                if os.path.exists(os.path.join(_CACHE, dst)):
                    rows[-1]["action"] = f"SKIPPED: {dst} already exists"
                    continue
                os.makedirs(backup, exist_ok=True)
                shutil.copy2(src, os.path.join(backup, n))
                os.replace(src, os.path.join(_CACHE, dst))
    R = pd.DataFrame(rows)
    os.makedirs(os.path.join("output", "research"), exist_ok=True)
    R.to_parquet(os.path.join("output", "research", "migrate_instrument_labels_d16_report.parquet"))
    with pd.option_context("display.width", 200, "display.max_rows", 500):
        print(R[R["root"].isin(["CL", "ES", "CC", "LTC"])].to_string(index=False))
        print(R.groupby(["class", "decision"]).size().to_string())
    print("APPLIED" if args.apply else "dry run -- nothing moved (use --apply)")


if __name__ == "__main__":
    main()
