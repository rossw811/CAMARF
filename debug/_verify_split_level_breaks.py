"""
BUG-D118 part 2 (Ross 2026-10-15, approved): after the qunit repair, a remaining one-day move larger than
LEVEL_BREAK_FACTOR (5x) in a Compustat Global total-return series is a data break -- a stitched listing, an unadjusted
split or redenomination, or a near-wipeout; no cointegration window may span it. For DAILY data the gap rule never
breaks a series (data.is_genuine_data_gap returns False unless DAILY_GAP_BREAKS), so masking would be bridged: the
series is SPLIT instead. Written failing-first. Checks on research/split_level_breaks.py:
  1. find_breaks: a permanent 1000x shift -> 'break' at that date; a spike that reverts within REVERT_DAYS (|sum of the
     jump and the next days' moves| < REVERT_TOL) -> 'spike' with the masked dates; moves < 5x ignored
  2. split_frame: a series with one permanent break -> two segments [start, break) and [break, end]; the LAST segment
     keeps the original label, earlier ones get _seg1, _seg2...; no segment contains a > 5x move
  3. spike days are set to NaN in every price column (volume kept), the series is not split
  4. a series with no break is returned whole, unchanged
Run: python debug/_verify_split_level_breaks.py
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def frame(px):
    idx = pd.bdate_range("2001-01-01", periods=len(px))
    d = pd.DataFrame({c: px for c in ("open", "high", "low", "close", "close_usd", "close_total_return")}, index=idx)
    d["volume"] = 100.0
    return d


def main():
    try:
        import research.split_level_breaks as m
    except ImportError as e:
        check("module_exists", False, e); return finish()
    base = 10 * np.exp(np.cumsum(np.random.default_rng(0).normal(0, 0.01, 60)))
    shift = base.copy(); shift[30:] *= 1000                      # permanent 1000x shift at bar 30
    spike = base.copy(); spike[20] *= 50                         # one-day bad print
    small = base.copy(); small[40:] *= 3                         # 3x: below the 5x rule
    b = m.find_breaks(frame(shift)["close_total_return"])
    check("permanent_break_found", len(b["breaks"]) == 1 and b["breaks"][0] == frame(shift).index[30] and not b["spikes"], b)
    s = m.find_breaks(frame(spike)["close_total_return"])
    check("spike_found", not s["breaks"] and s["spikes"] == [frame(spike).index[20]], s)
    check("small_move_ignored", m.find_breaks(frame(small)["close_total_return"]) == {"breaks": [], "spikes": []})
    segs = m.split_frame(frame(shift), "GVKEY000001_01W")
    names = [n for n, _ in segs]
    check("two_segments_named", names == ["GVKEY000001_01W_seg1", "GVKEY000001_01W"], names)
    lens = [len(d) for _, d in segs]
    check("segment_bounds", lens == [30, 30], lens)
    ok = all(np.abs(np.diff(np.log(d["close_total_return"].to_numpy()))).max() < np.log(5) for _, d in segs)
    check("no_break_inside_segments", ok)
    sp = m.split_frame(frame(spike), "GVKEY000002_01W")
    check("spike_masked_not_split", len(sp) == 1 and pd.isna(sp[0][1]["close"].iloc[20]) and sp[0][1]["volume"].iloc[20] == 100.0)
    whole = m.split_frame(frame(base), "GVKEY000003_01W")
    check("no_break_unchanged", len(whole) == 1 and whole[0][0] == "GVKEY000003_01W" and np.allclose(whole[0][1]["close"], base))
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
