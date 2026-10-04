"""
Regression test for code-review B15 (confirmed 2026-09-26, fixed 2026-10-03, bug recheck T14.4): the survivorship
truncation decided "still trading after its removal date?" from spread_df.index.max() -- the SHARED index end, which
runs on (NaN rows) after a symbol delists -- so a genuine delisting could be read as a false positive and not truncate.
Fix: `data_last_seen(spread_df)` = the last bar with a real (finite) spread.
Checks: a spread that stops 2020-06-30 on an index running to 2023 -> last seen 2020-06-30, and a removal date of
2020-06-15 truncates (returns the removal date); a spread running to 2023 -> no truncation (false positive).
Run: python debug/_verify_survivorship_last_real_bar.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import backtest

idx = pd.bdate_range("2019-01-02", "2023-06-30")
dead = pd.DataFrame({"spread": np.where(idx <= "2020-06-30", 0.1, np.nan)}, index=idx)
alive = pd.DataFrame({"spread": 0.1}, index=idx)
removed = pd.Timestamp("2020-06-15")
ok = hasattr(backtest, "data_last_seen")
checks = {"helper_exists": ok}
if ok:
    checks["last_real_bar"] = backtest.data_last_seen(dead) == pd.Timestamp("2020-06-30")
    checks["delisting_truncates"] = backtest.resolve_survivorship_oos_end(removed, backtest.data_last_seen(dead)) == removed
    checks["still_trading_not_truncated"] = backtest.resolve_survivorship_oos_end(removed, backtest.data_last_seen(alive)) is None
src = open(backtest.__file__, encoding="utf-8").read()
checks["call_site_uses_it"] = "resolve_survivorship_oos_end(_candidate_oos_end, data_last_seen(spread_df))" in src
for k, v in checks.items():
    print(f"[{'PASS' if v else 'FAIL'}] {k}")
print(); print(f"{sum(checks.values())}/{len(checks)} checks passed")
sys.exit(0 if all(checks.values()) else 1)
