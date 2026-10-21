"""
Sealed holdout (E13; enforced 2026-10-20) in the walk-forward analysis window and the coint-strength series:
pit_wfa.determine_analysis_window and research/pit_wfa_wrds_daily.determine_analysis_window took the universe's last
date (Compustat Global runs to 2026-08), so walk-forward OOS windows could reach sealed dates; the coint-strength
series builder read every Tier-3 window. Checks: both windows end before Config.DATA.SEALED_FROM; the builder's
loader drops windows ending on/after it.
"""
import os
import sys
import tempfile

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


from config import Config  # noqa: E402
sealed = pd.Timestamp(Config.DATA.SEALED_FROM)
u = {"A": pd.DataFrame({"close": [1.0, 2.0]}, index=pd.to_datetime(["2000-01-03", "2026-08-11"])),
     "B": pd.DataFrame({"close": [1.0, 2.0]}, index=pd.to_datetime(["1990-01-02", "2025-12-31"]))}
import pit_wfa  # noqa: E402
import pit_wfa_wrds_daily  # noqa: E402
for name, mod in (("pit_wfa", pit_wfa), ("pit_wfa_wrds_daily", pit_wfa_wrds_daily)):
    s, e = mod.determine_analysis_window(u)
    check(f"{name}: end before the seal, start unchanged", e < sealed and s == pd.Timestamp("1990-01-02"), f"{s} {e}")

import coint_strength_series_builder as csb  # noqa: E402
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "w.parquet")
    pd.DataFrame({"symbol_a": ["A", "A"], "symbol_b": ["B", "B"], "pvalue": [0.01, 0.02],
                  "window_end_date": pd.to_datetime(["2025-06-30", "2026-02-02"])}).to_parquet(p)
    try:
        w = csb.load_windows(p)
        check("coint_strength_series_builder.load_windows drops sealed windows", len(w) == 1, f"{len(w)}")
    except AttributeError as ex:
        check("coint_strength_series_builder.load_windows exists", False, str(ex))
print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(1 if failed else 0)
