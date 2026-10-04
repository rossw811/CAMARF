"""
Regression test for code-review B10 (confirmed 2026-09-26, fixed 2026-10-03, bug recheck T14.4): research/
liquidity_bar_masking.liquid_bar_mask read ONLY the yfinance cache ({sym}_1day.parquet), so every WRDS-universe symbol
(output/cache/wrds/{sym}_1D.parquet) got an empty mask -> with --storm-liquidity-bar-filter every entry was blocked,
at 1D too. backtest.py also reindexed the daily mask onto intraday bar timestamps exactly, so every intraday bar
(09:30, 10:30, ...) missed its day and was blocked.
Fix: WRDS first (CLAUDE.md rule 2), yfinance as fallback; dollar volume in USD (close_usd for Compustat Global
listings); `mask_on_bars` maps each bar to its own trading day.
Checks (temp dirs):
  1. a WRDS-only symbol gets a real mask (liquid / illiquid days as constructed);
  2. WRDS wins over a yfinance file for the same symbol;
  3. a Compustat Global listing uses close_usd x volume, not local-currency close x volume;
  4. mask_on_bars: intraday bars take their day's value; a day with no data is False.
Run: python debug/_verify_liquid_bar_mask_sources.py
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import research.liquidity_bar_masking as lbm

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    wrds, yf = tempfile.mkdtemp(prefix="lbm_wrds_"), tempfile.mkdtemp(prefix="lbm_yf_")
    try:
        idx = pd.bdate_range("2024-01-02", periods=6)
        thr = 1_000_000.0
        # WRDS-only: days 0-2 liquid ($2M), 3-5 illiquid ($0.5M)
        pd.DataFrame({"close": 20.0, "volume": [100_000] * 3 + [25_000] * 3}, index=idx).to_parquet(
            os.path.join(wrds, "WONLY_1D.parquet"))
        # both sources: WRDS says illiquid, yfinance says liquid
        pd.DataFrame({"close": 10.0, "volume": 1_000}, index=idx).to_parquet(os.path.join(wrds, "BOTH_1D.parquet"))
        pd.DataFrame({"close": 10.0, "volume": 10_000_000}, index=idx).to_parquet(os.path.join(yf, "BOTH_1day.parquet"))
        # Compustat Global: local close 1,000 (yen), USD close 7: 7 x 100,000 = $0.7M -> illiquid; local would be $100M
        pd.DataFrame({"close": 1000.0, "close_usd": 7.0, "volume": 100_000}, index=idx).to_parquet(
            os.path.join(wrds, "GVKEY000001_01W_1D.parquet"))
        kw = dict(threshold=thr, cache_dir=yf, wrds_dir=wrds) if "wrds_dir" in lbm.liquid_bar_mask.__code__.co_varnames \
            else dict(threshold=thr, cache_dir=yf)
        m1 = lbm.liquid_bar_mask("WONLY", **kw)
        check("1.wrds_only_symbol_has_mask", len(m1) == 6 and m1.tolist() == [True] * 3 + [False] * 3, str(m1.tolist()))
        m2 = lbm.liquid_bar_mask("BOTH", **kw)
        check("2.wrds_wins", len(m2) == 6 and not m2.any(), str(m2.tolist()))
        m3 = lbm.liquid_bar_mask("GVKEY000001_01W", **kw)
        check("3.compustat_uses_usd", len(m3) == 6 and not m3.any(), str(m3.tolist()))
        if hasattr(lbm, "mask_on_bars"):
            bars = pd.DatetimeIndex([pd.Timestamp(f"{d.date()} {h}") for d in list(idx[[0, 4]]) +
                                     [pd.Timestamp("2024-02-01")] for h in ("09:30", "15:30")])
            mb = lbm.mask_on_bars(m1, bars)
            check("4.mask_on_bars", mb.tolist() == [True, True, False, False, False, False], str(mb.tolist()))
        else:
            check("4.mask_on_bars", False, "missing")
    finally:
        shutil.rmtree(wrds, ignore_errors=True); shutil.rmtree(yf, ignore_errors=True)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
