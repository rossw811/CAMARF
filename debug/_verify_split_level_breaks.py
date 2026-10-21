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

    # Amendment 5 (BUG-D119 review, 2026-10-21): the rule compares CONSECUTIVE VALID prices. Real case GVKEY015736:
    # 175.88 -> 11.56 (15x) with an 810-day hole of NaN rows between them escaped it (diff() is NaN across NaN rows).
    hid = base.copy(); hid[30:] /= 15; hid[25:30] = np.nan          # 15x drop hidden behind 5 NaN rows
    hb = m.find_breaks(frame(hid)["close_total_return"])
    check("A5_break_behind_nan_hole_found", hb["breaks"] == [frame(hid).index[30]], hb)
    hs = m.split_frame(frame(hid), "GVKEY000004_01W")
    check("A5_split_at_first_valid_bar_after_hole", [len(d) for _, d in hs] == [30, 30], [len(d) for _, d in hs])
    sk = base.copy(); sk[22] *= 50; sk[20:22] = np.nan               # spike after a NaN pair, reverts next valid day
    ss = m.find_breaks(frame(sk)["close_total_return"])
    check("A5_spike_after_nan_still_a_spike", not ss["breaks"] and ss["spikes"] == [frame(sk).index[22]], ss)
    sm = m.split_frame(frame(sk), "GVKEY000005_01W")
    # (how many days after the spike get masked is the pre-existing argmin-of-|cumsum| rule, unchanged here)
    check("A5_spike_masked_on_valid_bar", len(sm) == 1 and pd.isna(sm[0][1]["close"].iloc[22])
          and sm[0][1]["close"].iloc[:20].notna().all() and sm[0][1]["close"].iloc[30:].notna().all())

    # rebuild: originals come from the backup when one exists, stale _seg files of the label are removed, and only
    # pre-seal rows are segmented (sealed rows stay with the label in the vault)
    import tempfile
    from config import Config
    with tempfile.TemporaryDirectory() as td:
        w = os.path.join(td, "wrds"); bak = os.path.join(w, "_pre_split_backup"); os.makedirs(bak)
        orig = frame(hid)
        orig.to_parquet(os.path.join(bak, "GVKEY000006_01W_1D.parquet"))
        frame(base[:30]).to_parquet(os.path.join(w, "GVKEY000006_01W_1D.parquet"))       # old, wrong pass output
        frame(base[:10]).to_parquet(os.path.join(w, "GVKEY000006_01W_seg1_1D.parquet"))  # stale segment
        frame(base[:10]).to_parquet(os.path.join(w, "GVKEY000006_01W_seg2_1D.parquet"))  # stale segment
        plan = m.rebuild_label("GVKEY000006_01W", w, dry_run=False)
        files = sorted(f for f in os.listdir(w) if f.endswith(".parquet"))
        check("A5_rebuild_from_backup_removes_stale_segments",
              files == ["GVKEY000006_01W_1D.parquet", "GVKEY000006_01W_seg1_1D.parquet"]
              and len(pd.read_parquet(os.path.join(w, "GVKEY000006_01W_1D.parquet"))) == 30, f"{files} {plan}")
        late = frame(base); late.index = pd.bdate_range("2025-11-03", periods=60)          # runs into 2026
        late.to_parquet(os.path.join(w, "GVKEY000007_01W_1D.parquet"))
        m.rebuild_label("GVKEY000007_01W", w, dry_run=False)
        got = pd.read_parquet(os.path.join(w, "GVKEY000007_01W_1D.parquet"))
        check("A5_rebuild_writes_only_pre_seal_rows", got.index.max() < pd.Timestamp(Config.DATA.SEALED_FROM),
              str(got.index.max()))
        bad = base.copy(); bad[10] *= 40; bad[12] /= 40                          # two jumps 2 days apart: neither
        frame(bad).to_parquet(os.path.join(w, "GVKEY000008_01W_seg1_1D.parquet"))   # a clean spike nor a split
        J = m.residual_jumps(w)
        n = m.quarantine_residuals(w, J)
        check("A5_residuals_quarantined", n >= 1 and len(m.residual_jumps(w)) == 0
              and os.path.exists(os.path.join(w, "_quarantine_d118_a5", "GVKEY000008_01W_seg1_1D.parquet")), f"{n}")
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
