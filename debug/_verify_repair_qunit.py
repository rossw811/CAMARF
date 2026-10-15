"""
BUG-D118 (2026-10-14/15): Compustat Global prices are quoted per QUNIT shares (comp_global_daily.g_secd.qunit; e.g.
Brazilian listings quoted per 1,000 shares until the late 1990s-2000s). data_wrds built close = prccd / ajexdi and never
divided by qunit, so a change of quotation unit appears as a ~1000x one-day jump (698 of 15,094 Compustat Global series;
in 136 of 680 Tier-3 confirmations). Verified on GVKEY230697 (COMGAS) 2007-10-02: prccd/(qunit*ajexdi) is continuous
(44.3 -> 44.96) while prccd/ajexdi jumps 44,303 -> 44.96. Written failing-first. Checks on research/repair_qunit.py:
  1. qunit_asof(runs, dates): the quotation unit in force on each date from (first_date, last_date, qunit) runs
  2. repair_frame: every price column (open, high, low, close, close_usd, close_total_return) divided by the as-of
     qunit; a 1000 -> 1 change no longer jumps; volume untouched (shares traded are per share already)
  3. a series whose qunit is 1 throughout is returned unchanged
  4. idempotent: a frame already marked qunit_applied is not divided again
  5. data_wrds' global fetch now selects qunit and divides by it (source check, both fetch paths)
Run: python debug/_verify_repair_qunit.py
"""
import os
import re
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    try:
        import research.repair_qunit as m
    except ImportError as e:
        check("module_exists", False, e); return finish()
    idx = pd.bdate_range("2007-09-24", periods=10)
    runs = pd.DataFrame({"qunit": [1000.0, 1.0], "first_date": [idx[0], idx[6]], "last_date": [idx[5], idx[9]]})
    q = m.qunit_asof(runs, idx)
    check("qunit_asof", list(q) == [1000.0] * 6 + [1.0] * 4, list(q))
    per_share = np.linspace(44.0, 45.0, 10)
    quoted = per_share * q.to_numpy()                              # what Compustat stores: price per qunit shares
    df = pd.DataFrame({c: quoted for c in ("open", "high", "low", "close", "close_usd", "close_total_return")}, index=idx)
    df["volume"] = 1000.0
    fixed = m.repair_frame(df, runs)
    jump = np.abs(np.diff(np.log(fixed["close"].to_numpy()))).max()
    check("no_jump_after_repair", jump < 0.05 and np.allclose(fixed["close_usd"], per_share), f"max |dlog| {jump:.4f}")
    check("volume_untouched", np.allclose(fixed["volume"], 1000.0))
    check("marked", bool(fixed["qunit_applied"].all()))
    plain = df.copy()
    same = m.repair_frame(plain, pd.DataFrame({"qunit": [1.0], "first_date": [idx[0]], "last_date": [idx[-1]]}))
    check("unit_one_unchanged", np.allclose(same["close"], plain["close"]))
    again = m.repair_frame(fixed, runs)
    check("idempotent", np.allclose(again["close"], fixed["close"]))
    src = open(os.path.join(ROOT, "data_wrds.py"), encoding="utf-8").read()
    n_sel = len(re.findall(r"prccd, cshtrd, ajexdi, qunit", src))
    n_div = len(re.findall(r'"close": (?:df|g)\["prccd"\] / \((?:df|g)\["qunit"\] \* fac\)', src))
    check("fetch_divides_by_qunit", n_sel == 2 and n_div == 2, f"selects {n_sel}, divides {n_div}")
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
