"""
BUG-D120 / Amendment 5 (DECISIONS_2026-10-21 #1): the pool is the point-in-time-eligible set itself. Before, pool
MEMBERSHIP came from purity_pairs.parquet (one BH over the whole window family, as of the adapter's build date) and
the point-in-time BH only DATED pairs inside it: 330 of 767 pairs k1-eligible before 2026 were excluded. Checks on
research/purity_pit_eligibility.build_pit_pool (synthetic Tier-3 windows):
  1. a pair PIT-eligible but absent from the whole-history pool file IS in the pool (flagged in_whole_history_set=False)
  2. a pair in the whole-history pool file that never becomes PIT-eligible is NOT in the pool
  3. eligible_from equals pit_kth_rejection_dates' date; k = 2 needs two rejections
  4. windows ending on/after the seal of their timeframe are ignored (daily 2026-01-01, intraday SEALED_FROM_INTRADAY)
  5. symbol order follows the windows file (discovery's order), and adapter metadata is joined in either order
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
from config import Config  # noqa: E402

if not hasattr(ppe, "build_pit_pool"):
    check("build_pit_pool exists", False)
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1)

# Background family of 400 null windows so BH has an m; three tracked pairs.
rng = np.random.default_rng(1)
ends = pd.date_range("2010-01-31", periods=200, freq="ME")
bg = pd.DataFrame({"symbol_a": [f"N{i}" for i in range(400)], "symbol_b": [f"M{i}" for i in range(400)],
                   "window_end_date": np.tile(ends, 2), "pvalue": rng.uniform(0.2, 1.0, 400)})
rows = [("ZED", "ABC", "2012-03-31", 1e-9), ("ZED", "ABC", "2014-06-30", 1e-9),   # P1: not in whole-history file
        ("QQQ", "RRR", "2011-05-31", 0.5),                                          # P2: in file, never eligible
        ("SSS", "TTT", "2013-01-31", 1e-9),                                         # P3: k1 only
        ("UUU", "VVV", "2026-02-27", 1e-9), ("UUU", "VVV", "2026-03-31", 1e-9)]     # P4: sealed (daily)
w1d = pd.concat([bg, pd.DataFrame(rows, columns=bg.columns)], ignore_index=True)
w1d["window_end_date"] = pd.to_datetime(w1d["window_end_date"])
I = pd.Timestamp(Config.DATA.SEALED_FROM_INTRADAY)
w1h = pd.concat([bg, pd.DataFrame([("HA", "HB", "2026-03-31", 1e-9), ("HC", "HD", str((I + pd.Timedelta(days=3)).date()), 1e-9)],
                                  columns=bg.columns)], ignore_index=True)
w1h["window_end_date"] = pd.to_datetime(w1h["window_end_date"])
whole = pd.DataFrame({"symbol_a": ["QQQ", "ABC"], "symbol_b": ["RRR", "SSS"], "tf_label": ["1D", "1D"],
                      "hedge_ratio_ols": [1.0, 2.0]})
whole = pd.concat([whole, pd.DataFrame({"symbol_a": ["TTT"], "symbol_b": ["SSS"], "tf_label": ["1D"],
                                        "hedge_ratio_ols": [3.0]})], ignore_index=True)

P1 = ppe.build_pit_pool({"1D": w1d, "1h": w1h}, 1, whole)
keys = {(a, b, t) for a, b, t in zip(P1["symbol_a"], P1["symbol_b"], P1["tf_label"])}
check("1 PIT-eligible pair absent from the whole-history file is in the pool",
      ("ZED", "ABC", "1D") in keys and not bool(P1.set_index(["symbol_a", "symbol_b"]).loc[("ZED", "ABC"), "in_whole_history_set"]),
      str(sorted(keys)))
check("2 whole-history pair never PIT-eligible is not in the pool", ("QQQ", "RRR", "1D") not in keys)
e = ppe.pit_kth_rejection_dates(w1d[w1d["window_end_date"] < pd.Timestamp(Config.DATA.SEALED_FROM)], 1)
want = e[(e["key_a"] == "ABC") & (e["key_b"] == "ZED")]["eligible_from"].iloc[0]
got = P1[(P1["symbol_a"] == "ZED")]["eligible_from"].iloc[0]
check("3a eligible_from = pit_kth_rejection_dates", got == want, f"{got} {want}")
P2 = ppe.build_pit_pool({"1D": w1d, "1h": w1h}, 2, whole)
k2 = {(a, b) for a, b in zip(P2["symbol_a"], P2["symbol_b"])}
check("3b k=2: two rejections needed", ("ZED", "ABC") in k2 and ("SSS", "TTT") not in k2, str(k2))
check("4a daily windows on/after SEALED_FROM ignored", ("UUU", "VVV", "1D") not in keys)
check("4b intraday: 2026-03 window kept, post-SEALED_FROM_INTRADAY window ignored",
      ("HA", "HB", "1h") in keys and ("HC", "HD", "1h") not in keys, str(sorted(k for k in keys if k[2] == "1h")))
r3 = P1[(P1["symbol_a"] == "SSS") & (P1["symbol_b"] == "TTT")]
check("5 windows' symbol order kept; reversed (TTT/SSS) row flagged but its hedge ratio NOT copied (review F5)",
      len(r3) == 1 and pd.isna(r3["hedge_ratio_ols"].iloc[0]) and bool(r3["in_whole_history_set"].iloc[0]),
      str(r3.to_dict("records")))
r6 = ppe.build_pit_pool({"1D": w1d}, 1, pd.DataFrame({"symbol_a": ["SSS"], "symbol_b": ["TTT"], "tf_label": ["1D"],
                                                       "hedge_ratio_ols": [4.0]}))
r6 = r6[r6["symbol_a"] == "SSS"]
check("5b same orientation: metadata joined", len(r6) == 1 and r6["hedge_ratio_ols"].iloc[0] == 4.0, str(r6.to_dict("records")))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
