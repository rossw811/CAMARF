"""
Regression test for code-review finding D5 (2026-09-26): DataAligner.align_intraday classified missing grid rows
only by run length. On the 4h grid a weeknight close is exactly 4 missing bars (17:30, 21:30, 01:30, 05:30) --
within _MAX_FILL_BARS -- so every night was flagged FILL and forward-filled into correlation/EG as fake bars.
Fix: for non-crypto assets, a missing row at a time of day the asset NEVER trades is closed-market time ->
DATA_GAP (masked) regardless of run length; a missing bar at one of its normal trading times keeps the run rule.
Checks on a synthetic 4h equity (bars at 09:30 and 13:30 each weekday, one 13:30 bar genuinely missing):
  1. overnight rows (17:30/21:30/01:30/05:30) are DATA_GAP, not FILL;
  2. the missing 13:30 session bar is FILL;
  3. a crypto asset (trades 24/7) is unaffected: its short missing runs stay FILL.
Run: python debug/_verify_intraday_closed_market_gaps.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from data import DataAligner, GapFlag

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    days = pd.bdate_range("2026-03-02", periods=20)
    idx = pd.DatetimeIndex([d + pd.Timedelta(hours=h, minutes=30) for d in days for h in (9, 13)])
    idx = idx.drop(days[5] + pd.Timedelta(hours=13, minutes=30))     # one genuinely missing session bar
    c = 50 + np.cumsum(np.random.default_rng(0).normal(0, 0.1, len(idx)))
    eq = pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1e5}, index=idx)
    cidx = pd.date_range("2026-03-02", periods=120, freq="4h")
    cidx = cidx.delete([10, 11])                                         # 2 missing crypto bars
    cc = 30000 + np.cumsum(np.random.default_rng(1).normal(0, 10, len(cidx)))
    cr = pd.DataFrame({"open": cc, "high": cc, "low": cc, "close": cc, "volume": 1.0}, index=cidx)
    out = DataAligner.align_intraday({"EQTY": eq, "BTC": cr}, "4h")
    e = out["EQTY"]
    overnight = e[[t.strftime("%H:%M") in ("17:30", "21:30", "01:30", "05:30") for t in e.index]]
    weeknight = overnight[overnight.index.dayofweek < 4]
    check("overnight_rows_are_data_gap", len(weeknight) > 0 and (weeknight["gap_flag"] == GapFlag.DATA_GAP).all(),
          f"flags={weeknight['gap_flag'].value_counts().to_dict()}")
    miss = e.loc[days[5] + pd.Timedelta(hours=13, minutes=30), "gap_flag"]
    check("missing_session_bar_is_fill", miss == GapFlag.FILL, f"flag={miss}")
    b = out["BTC"]
    cm = b.loc[pd.date_range("2026-03-02", periods=120, freq="4h")[[10, 11]], "gap_flag"]
    check("crypto_short_gap_stays_fill", (cm == GapFlag.FILL).all(), f"{cm.tolist()}")
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
