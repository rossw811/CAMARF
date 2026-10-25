"""
Amendment 6 (Ross 2026-10-25): pool membership re-decided every month -- a pair may open trades only in the month
after a month-end at which the as-of BH family counts >= k of its windows as rejected. Checks:
  1. purity_pit_eligibility.pit_active_months: a pair with one strong early rejection is active right after it, and
     becomes INACTIVE once later null windows grow the as-of family until BH no longer rejects it (Amendment 5's rule
     would keep it forever); its first active month equals pit_kth_rejection_dates' eligible_from
  2. backtest.active_at: an entry on any day of month M is allowed iff the month-end of M-1 is active (strictly before:
     a month-end's status is known only after it)
  3. strategy_search arm selection: --arm dyn uses the _dyn pools and suffixes its outputs; the default is unchanged
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


import purity_pit_eligibility as ppe  # noqa: E402

if not hasattr(ppe, "pit_active_months"):
    check("pit_active_months exists", False)
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1)
rng = np.random.default_rng(2)
ends = pd.date_range("2010-01-31", periods=120, freq="ME")
rows = [("P", "Q", pd.Timestamp("2010-03-31"), 2e-4)]
for i, e in enumerate(ends):                           # 10 null windows a month: the as-of family grows
    rows += [(f"N{i}_{j}", f"M{i}_{j}", e, rng.uniform(0.3, 1.0)) for j in range(10)]
W = pd.DataFrame(rows, columns=["symbol_a", "symbol_b", "window_end_date", "pvalue"])
A = ppe.pit_active_months(W, 1, keys={("P", "Q")})
act = pd.DatetimeIndex(A.loc[(A["key_a"] == "P") & (A["key_b"] == "Q"), "active_month_ends"].iloc[0])
ef = ppe.pit_kth_rejection_dates(W, 1)
ef = ef[(ef["key_a"] == "P") & (ef["key_b"] == "Q")]["eligible_from"].iloc[0]
check("1a active right after the rejection; first active month = eligible_from", len(act) and act.min() == ef, f"{act.min()} {ef}")
check("1b becomes inactive as the family grows (never removed under Amendment 5)", act.max() < ends.max(),
      f"last active {act.max().date()}, family to {ends.max().date()}")

import backtest as bt  # noqa: E402
months = pd.DatetimeIndex(["2012-01-31", "2012-02-29"])
check("2 entry allowed in the month after an active month-end only",
      bt.active_at(months, pd.Timestamp("2012-02-15")) and bt.active_at(months, pd.Timestamp("2012-03-01 10:00"))
      and not bt.active_at(months, pd.Timestamp("2012-01-31")) and not bt.active_at(months, pd.Timestamp("2012-04-02")))

import strategy_search as ss  # noqa: E402
d, y = ss.pools_for_arm("a5"), ss.pools_for_arm("dyn")
check("3 arm selection", sorted(d) == ["pit_k1", "pit_k2"] and sorted(y) == ["pit_k1_dyn", "pit_k2_dyn"]
      and all(v.endswith("_dyn.parquet") for v in y.values()), f"{d} {y}")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
