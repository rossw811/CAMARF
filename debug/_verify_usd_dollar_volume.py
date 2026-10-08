"""
Regression test for code review R1.2 (verified 2026-10-07 on real files, fixed the same day): the episodic scan's
rolling-ADV liquidity gate (research/rolling_adv_comparison.rolling_adv / flat_adv) and data_wrds' recent-ADV helper
multiplied Compustat Global `close` -- LOCAL currency (GVKEY246959_01W: close 1694 JPY, close_usd 10.66) -- by
volume and compared it with a USD threshold: ~159x too liquid for yen listings, so the gate was effectively off for
the 15,093 international listings. Fix: one helper, dollar_volume.usd_dollar_volume(df): price = close_usd where the
file has it, else |close| (CRSP is USD; a negative close is a bid/ask midpoint). Same rule research/liquidity_bar_
masking already used, now shared.
Checks: a Compustat-style frame uses close_usd; a CRSP-style frame uses |close|; rolling_adv / flat_adv /
data_wrds.compute_symbol_adv_wrds all follow it (gate verdict flips for the yen listing at a $25M threshold);
liquidity_bar_masking gives the same mask as before.
Run: python debug/_verify_usd_dollar_volume.py
"""
import os
import shutil
import sys
import tempfile

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    idx = pd.bdate_range("2023-01-02", periods=400)
    jp = pd.DataFrame({"close": 1694.0, "close_usd": 10.66, "volume": 311_600.0}, index=idx)    # ~$3.3M/day USD
    us = pd.DataFrame({"close": 50.0, "volume": 1_000_000.0}, index=idx)                         # $50M/day
    us.iloc[5, 0] = -50.0                                                                         # midpoint day
    try:
        from dollar_volume import usd_dollar_volume
    except ImportError as e:
        check("helper_exists", False, str(e)); usd_dollar_volume = None
    if usd_dollar_volume:
        check("compustat_uses_close_usd", np.allclose(usd_dollar_volume(jp), 10.66 * 311_600.0))
        check("crsp_uses_abs_close", np.allclose(usd_dollar_volume(us), 50.0 * 1_000_000.0))
    from research.rolling_adv_comparison import rolling_adv, flat_adv
    thr = 25_000_000.0
    r = rolling_adv(jp).dropna()
    check("rolling_adv_jp_usd", len(r) > 0 and np.allclose(r, 10.66 * 311_600.0), r.iloc[-1] if len(r) else None)
    check("rolling_adv_jp_fails_gate", len(r) > 0 and bool((r < thr).all()))
    check("flat_adv_jp_usd", np.isclose(flat_adv(jp), 10.66 * 311_600.0), flat_adv(jp))
    check("flat_adv_us_abs", np.isclose(flat_adv(us), 50.0 * 1_000_000.0), flat_adv(us))
    import data_wrds
    d = tempfile.mkdtemp(prefix="usd_dv_")
    try:
        jp.to_parquet(os.path.join(d, "GVKEYTEST_01W_1D.parquet"))
        old = data_wrds._OUT_DIR
        data_wrds._OUT_DIR = d
        try:
            v = data_wrds.compute_symbol_adv_wrds("GVKEYTEST_01W")
        finally:
            data_wrds._OUT_DIR = old
        check("data_wrds_compute_symbol_adv_usd", np.isclose(v, 10.66 * 311_600.0), v)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    from research.liquidity_bar_masking import liquid_bar_mask
    d = tempfile.mkdtemp(prefix="usd_dv_mask_")
    try:
        jp.to_parquet(os.path.join(d, "JP_1D.parquet"))
        m = liquid_bar_mask("JP", threshold=thr, cache_dir=d, wrds_dir=d)
        check("bar_mask_unchanged", len(m) == 400 and not m.any())
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
