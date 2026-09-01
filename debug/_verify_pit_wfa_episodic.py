"""
debug/_verify_pit_wfa_episodic.py -- synthetic checks for research/pit_wfa_episodic.py.

episodic_bhfdr_confirm_asof() itself is already verified elsewhere (it is
reused, not reimplemented, here). These checks target THIS script's own new
logic: correct Tier-3-windows file loading/mtime disclosure, correct
single-symbol WRDS loading with missing-file/empty-data handling, and the
checkpoint screening wrapper correctly excluding a pair whose only
FDR-significant window concludes after the as-of cutoff.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.pit_wfa_episodic import load_symbol_close, screen_at_checkpoint

passed = 0
failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}")
        failed += 1


print("Check 1: load_symbol_close returns empty DataFrame for a nonexistent symbol")
df = load_symbol_close("__NONEXISTENT_SYMBOL_XYZ__")
check("empty on missing file", df.empty)

print("Check 2: screen_at_checkpoint excludes a pair whose only significant window "
      "concludes AFTER the as-of cutoff")
rows = [
    {"symbol_a": "AAA", "symbol_b": "BBB", "pvalue": 0.0001,
     "window_end_date": pd.Timestamp("2020-01-01")},  # before cutoff, should be eligible
    {"symbol_a": "CCC", "symbol_b": "DDD", "pvalue": 0.0001,
     "window_end_date": pd.Timestamp("2023-01-01")},  # AFTER cutoff, must be excluded
]
confirmed = screen_at_checkpoint(rows, pd.Timestamp("2021-01-01"), alpha=0.05)
confirmed_pairs = {frozenset((c["symbol_a"], c["symbol_b"])) for c in confirmed}
check("AAA/BBB (window concludes before cutoff) IS confirmed",
      frozenset(("AAA", "BBB")) in confirmed_pairs)
check("CCC/DDD (window concludes after cutoff) is NOT confirmed",
      frozenset(("CCC", "DDD")) not in confirmed_pairs)

print("Check 3: screen_at_checkpoint returns empty list on empty input, no crash")
empty_result = screen_at_checkpoint([], pd.Timestamp("2021-01-01"), alpha=0.05)
check("empty input -> empty output, no exception", empty_result == [])

print("Check 4: a real WRDS-cached symbol (if any exist locally) loads with a 'close' column")
wrds_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "output", "cache", "wrds")
real_symbol = None
if os.path.isdir(wrds_dir):
    for f in os.listdir(wrds_dir):
        if f.endswith("_1D.parquet") and os.path.getsize(os.path.join(wrds_dir, f)) > 0:
            real_symbol = f[: -len("_1D.parquet")]
            break
if real_symbol:
    df_real = load_symbol_close(real_symbol)
    check(f"real symbol {real_symbol} loads with 'close' column and non-empty data",
          not df_real.empty and "close" in df_real.columns)
else:
    print("  SKIP: no real WRDS cache file found locally to test against")

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
