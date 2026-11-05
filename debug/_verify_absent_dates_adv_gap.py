"""
Synthetic checks for research/absent_dates_adv_gap.file_effect (BUG-D122 open point b).
  1. no absent days: counts 0, no verdict flips, ADV ratio 1;
  2. a 10-trading-day absent run (> _MAX_FILL_BARS): counted once with max run 10; rolling_adv on the rows does NOT see it
     (gate passes through it) -- the effect being measured -- while the calendar-reindexed version voids the windows
     that hold it, so passes flip to fails by a gap;
  3. a 3-day absent run (<= _MAX_FILL_BARS): counted, but no gap and no flip;
  4. rows on/after the seal are never evaluated.
Run: python debug/_verify_absent_dates_adv_gap.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "research")]
import numpy as np
import pandas as pd

from absent_dates_adv_gap import file_effect

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


cal = pd.bdate_range("2010-01-01", "2014-12-31")
thr = 25e6


def frame(days):
    return pd.DataFrame({"close": 50.0, "volume": 1e6}, index=days)     # $50M a day, well above the threshold


e = file_effect(frame(cal), cal, thr, sealed_from="2030-01-01")
check("1 no absent days: zero counts, no flips, ratio 1",
      e["n_absent"] == 0 and e["n_runs_gt"] == 0 and e["flip_close"] == 0 and e["flip_open"] == 0
      and abs(e["ratio_med"] - 1) < 1e-12, e)

hole = cal[400:410]
e = file_effect(frame(cal.difference(hole)), cal, thr, sealed_from="2030-01-01")
check("2a 10-day absent run counted once, max run 10", e["n_absent"] == 10 and e["n_runs_gt"] == 1 and e["max_run"] == 10, e)
# windows ending at rows whose trailing 252 calendar days hold > 5 of the 10 absent days are voided: ~252 rows after it
check("2b gap invisible to row-based ADV, visible after reindex: passes flip to fails by a gap",
      e["flip_close"] > 200 and e["close_gap"] == e["flip_close"] and e["flip_open"] == 0, e)

e = file_effect(frame(cal.difference(cal[400:403])), cal, thr, sealed_from="2030-01-01")
check("3 3-day absent run: counted, no gap, no flip", e["n_absent"] == 3 and e["n_runs_gt"] == 0 and e["flip_close"] == 0, e)

e = file_effect(frame(cal), cal, thr, sealed_from="2013-01-01")
check("4 sealed rows never evaluated", e["n_rows"] == int((cal < "2013-01-01").sum()) == e["n_eval"], e)

print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
