"""
Regression test for code-review findings D3/D4 (2026-09-26): snap_timestamps() snapped each bar to the
NEAREST grid slot (Python banker's round) and clamped to the last FULL-length slot, so
  * IBKR on-the-hour 1h bars (10:00, 11:00, ...) collided pairwise and were dropped (6 in -> 4 out);
  * yfinance's 15:30 1h bar was moved onto 14:30 and overwrote it (up to 90 min lookahead);
  * 4h allowed one slot per session, so the 13:30 bar overwrote 09:30 (a 4h lookahead on every bar).

Invariants now required:
  1. NO LOOKAHEAD: every snapped label >= the bar's original open time (a bar may be labelled later
     than it started, never earlier).
  2. No bar silently lost: distinct source bars that land in distinct slots all survive; the final
     partial session slot (15:30 for 1h, 13:30 for 4h) is valid.
  3. If two bars do share a slot, they are MERGED (first open, max high, min low, last close,
     summed volume), not dropped.

Run: python debug/_verify_snap_timestamps_no_lookahead.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from data import snap_timestamps

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def mk(times, day="2026-03-02"):
    idx = pd.DatetimeIndex([pd.Timestamp(f"{day} {t}") for t in times])
    c = np.arange(1, len(idx) + 1, dtype=float)
    return pd.DataFrame({"open": c, "high": c + 0.5, "low": c - 0.5, "close": c, "volume": 10.0}, index=idx)


def run(name, times, tf, src, expect_n):
    df = mk(times)
    out = snap_timestamps(df, tf, source=src)
    # map each output row back to the source rows it came from via close value (unique per input)
    no_look = True
    for ts, row in out.iterrows():
        src_rows = df[df["close"] == row["close"]]
        if len(src_rows) and ts < src_rows.index.max():
            no_look = False
    check(f"{name}.no_lookahead", no_look, f"out={[t.strftime('%H:%M') for t in out.index]}")
    check(f"{name}.bars_kept_{expect_n}", len(out) == expect_n, f"in={len(df)} out={len(out)}")
    return out


def main():
    run("ibkr_1h_on_hour", ["10:00", "11:00", "12:00", "13:00", "14:00", "15:00"], "1h", "ibkr", 6)
    run("yf_1h_930_grid", ["09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30"], "1h", "yfinance", 7)
    run("4h_two_per_session", ["09:30", "13:30"], "4h", "ibkr", 2)
    # Merge on collision: 09:45 and 10:15 both snap UP to the 10:30 1h slot -> merged, not dropped.
    # (First draft used 09:30/09:45, which encoded the old round-to-nearest semantics: under the
    # ceiling rule 09:30 stays 09:30 and 09:45 goes to 10:30 -- no collision. Corrected.)
    df = mk(["09:45", "10:15"])
    out = snap_timestamps(df, "1h", source="ibkr")
    ok = len(out) == 1 and out.iloc[0]["open"] == 1.0 and out.iloc[0]["close"] == 2.0 \
        and out.iloc[0]["high"] == 2.5 and out.iloc[0]["low"] == 0.5 and out.iloc[0]["volume"] == 20.0
    check("collision.merged_ohlcv", ok, f"rows={len(out)} {out.iloc[0].to_dict() if len(out) else ''}")
    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
