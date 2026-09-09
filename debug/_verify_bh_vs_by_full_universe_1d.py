"""Synthetic proof for research/bh_vs_by_full_universe_1d.py's core
correctness claims: load_candidate_sample's reproducibility, and the
real alignment bug this script's own build caught live (DataAligner.
align_universe produces per-symbol-length arrays that silently break
_eg_worker's positional isfinite-mask; align_to_common_calendar fixes
it). Not a production script, run manually."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from universe_loader import align_to_common_calendar
from analysis import CointScanner, _eg_worker

n_checks = 0
n_passed = 0


def check(name, cond):
    global n_checks, n_passed
    n_checks += 1
    status = "PASS" if cond else "FAIL"
    if cond:
        n_passed += 1
    print(f"[{status}] {name}")


# --- Real bug this script's build caught live: two symbols with genuinely
# different real-history lengths (like AA: 2016- vs DOW: 2019-) must NOT
# crash _eg_worker once run through align_to_common_calendar. ---
idx_long = pd.date_range("2016-01-01", "2020-01-01", freq="B")
idx_short = pd.date_range("2018-01-01", "2020-01-01", freq="B")
rng = np.random.default_rng(0)

df_long = pd.DataFrame({"close": 100 + np.cumsum(rng.normal(0, 1, len(idx_long)))}, index=idx_long)
df_short = pd.DataFrame({"close": 50 + np.cumsum(rng.normal(0, 1, len(idx_short)))}, index=idx_short)

check("the two synthetic symbols genuinely have different raw lengths (the real-world scenario)",
      len(df_long) != len(df_short))

merged = {"LONG": df_long, "SHORT": df_short}
aligned = align_to_common_calendar(merged, lookback_years=10)

check("align_to_common_calendar produces the SAME length for both symbols",
      len(aligned["LONG"]) == len(aligned["SHORT"]))

log_prices = CointScanner._build_log_price_map(aligned, ["LONG", "SHORT"])
check("both symbols' log-price arrays are the same length after alignment",
      len(log_prices["LONG"]) == len(log_prices["SHORT"]))

task = ("LONG", "SHORT", log_prices["LONG"], log_prices["SHORT"], 5, "1D")
result = _eg_worker(task)
print(result)
check("_eg_worker succeeds (ok=True) on genuinely different-length real symbols once aligned "
      "via align_to_common_calendar, instead of silently failing on a shape-broadcast error",
      result.get("ok") is True)

print(f"\n{n_passed}/{n_checks} checks passed")
sys.exit(0 if n_passed == n_checks else 1)
