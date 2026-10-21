"""
BUG-A06 / X-C02 (bug recheck 2026-10-07: "fixed-untested"): excluded assets must not enter analysis via universe.data.
The guard lived inline in AnalysisPipeline._run_one_tf (untestable without a full timeframe run); it is now
AnalysisPipeline._extract_tf_data. Checks:
  1. a symbol in universe.exclusion_set with cached data is skipped
  2. a non-excluded symbol with data is kept; one without data (missing key / None) is skipped
  3. a frequency-mismatched cache (daily bars under a 1h key) is skipped and reported
  4. the 1m shallow cap keeps the last 5,000 bars
Scope note: the exclusion set is data.py's fetch-layer list (three hard-coded tickers yfinance cannot serve, plus a
persistent-failure file that exists on neither machine); research scripts on load_full_universe (WRDS first) do not
apply it, by design -- VLTO, for one, has a real CRSP series.
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


from analysis import AnalysisPipeline  # noqa: E402
from data import UniverseResult  # noqa: E402

if not hasattr(AnalysisPipeline, "_extract_tf_data"):
    check("_extract_tf_data exists", False)
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1)

h = pd.date_range("2025-03-03 09:30", periods=400, freq="1h")
h = h[(h.hour >= 9) & (h.hour <= 15)]
f1h = pd.DataFrame({"close": np.linspace(1, 2, len(h)), "volume": 1.0}, index=h)
d = pd.bdate_range("2020-01-01", periods=300)
fday = pd.DataFrame({"close": np.linspace(1, 2, len(d)), "volume": 1.0}, index=d)
u = UniverseResult(assets=[("EXCL", "equity"), ("KEEP", "equity"), ("NODATA", "equity"), ("NONE", "equity"),
                           ("DAILY", "equity")], excluded=[], quality_reports=[], exclusion_set={"EXCL"},
                   data={"EXCL_1h": f1h, "KEEP_1h": f1h, "NONE_1h": None, "DAILY_1h": fday})
out, mism = AnalysisPipeline._extract_tf_data(u, "1h")
check("1 excluded symbol with data skipped", "EXCL" not in out, str(sorted(out)))
check("2 kept / missing / None", "KEEP" in out and "NODATA" not in out and "NONE" not in out, str(sorted(out)))
check("3 frequency mismatch skipped and reported", "DAILY" not in out and mism == ["DAILY"], str(mism))
m = pd.date_range("2025-03-03 09:30", periods=8000, freq="1min")
u2 = UniverseResult(assets=[("M", "equity")], excluded=[], quality_reports=[],
                    data={"M_1m": pd.DataFrame({"close": np.linspace(1, 2, len(m)), "volume": 1.0}, index=m)})
o2, _ = AnalysisPipeline._extract_tf_data(u2, "1m")
check("4 1m shallow cap = last 5,000 bars", "M" in o2 and len(o2["M"]) == 5000 and o2["M"].index[-1] == m[-1],
      str(len(o2.get("M", []))))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
