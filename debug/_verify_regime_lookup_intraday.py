"""
Regression test for code-review B13 (confirmed 2026-09-26, fixed 2026-10-03, bug recheck T14.4): RegimeConditioner.
_get_regime matched macro rows `index <= ts.normalize()`, so an INTRADAY entry at 10:30 on day D saw day D's
end-of-day macro values (known only after the close) -- lookahead. Layer 2 only (off by default).
Fix: an intraday timestamp sees rows strictly BEFORE its date; a daily (midnight) timestamp keeps the same-day row.
Check: rows D-1 = "contango", D = "backwardation": intraday D 10:30 -> contango; daily D -> backwardation.
Run: python debug/_verify_regime_lookup_intraday.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from backtest import RegimeConditioner

rc = RegimeConditioner(enabled=False)
rc._macro = pd.DataFrame({"vix_term_structure": ["contango", "backwardation"], "yield_curve_regime": ["normal", "normal"]},
                         index=pd.to_datetime(["2024-03-04", "2024-03-05"]))
intra = rc._get_regime(pd.Timestamp("2024-03-05 10:30"))["vix_ts"]
daily = rc._get_regime(pd.Timestamp("2024-03-05"))["vix_ts"]
checks = {"intraday_sees_previous_day": intra == "contango", "daily_sees_same_day": daily == "backwardation"}
for k, v in checks.items():
    print(f"[{'PASS' if v else 'FAIL'}] {k} (intraday={intra!r}, daily={daily!r})")
print(); print(f"{sum(checks.values())}/{len(checks)} checks passed")
sys.exit(0 if all(checks.values()) else 1)
