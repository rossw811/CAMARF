"""
debug/_verify_pit_wfa_wrds_daily_merge_and_save.py -- synthetic check for a real data-loss bug
found live (2026-09-04): research/pit_wfa_wrds_daily.py wrote its 4 output parquet files under
FIXED filenames with no `--variant` suffix, so running `--variant expanding` then, in a separate
invocation, `--variant rolling` silently overwrote expanding's saved results entirely -- both
variants' real numbers had already been manually recovered from the log files before this was
noticed, so nothing was actually lost, but the bug will keep recurring on every future two-part
run. Fixed via `_merge_and_save()`, keyed on (wfa_variant, fold): a different variant's rows are
preserved, while re-running the SAME variant still correctly replaces only its own prior rows.

Run: python debug/_verify_pit_wfa_wrds_daily_merge_and_save.py
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research.pit_wfa_wrds_daily as pw

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


tmp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_merge_and_save_test.parquet")
if os.path.exists(tmp_path):
    os.remove(tmp_path)

print("Check 1: first write with no existing file just writes the new rows")
expanding_df = pd.DataFrame([
    {"wfa_variant": "expanding", "fold": "fold1_exp", "sharpe": -0.4779},
    {"wfa_variant": "expanding", "fold": "fold2_exp", "sharpe": 0.1918},
])
pw._merge_and_save(expanding_df, tmp_path)
result1 = pd.read_parquet(tmp_path)
check("2 rows written on first call", len(result1) == 2)

print("Check 2: writing a DIFFERENT variant preserves the first variant's rows (the real bug: "
      "this used to silently destroy them)")
rolling_df = pd.DataFrame([
    {"wfa_variant": "rolling", "fold": "fold1_roll", "sharpe": -0.4779},
    {"wfa_variant": "rolling", "fold": "fold2_roll", "sharpe": 0.2175},
])
pw._merge_and_save(rolling_df, tmp_path)
result2 = pd.read_parquet(tmp_path)
check("all 4 rows present (2 expanding + 2 rolling) -- expanding's rows survived",
      len(result2) == 4)
check("both expanding rows are still exactly as originally written",
      set(result2[result2["wfa_variant"] == "expanding"]["fold"]) == {"fold1_exp", "fold2_exp"})
check("both rolling rows are present",
      set(result2[result2["wfa_variant"] == "rolling"]["fold"]) == {"fold1_roll", "fold2_roll"})

print("Check 3: re-running the SAME variant replaces only its own prior rows (no duplication, "
      "no stale rows left behind)")
expanding_rerun_df = pd.DataFrame([
    {"wfa_variant": "expanding", "fold": "fold1_exp", "sharpe": -0.9999},  # a changed value
    {"wfa_variant": "expanding", "fold": "fold2_exp", "sharpe": 0.8888},
])
pw._merge_and_save(expanding_rerun_df, tmp_path)
result3 = pd.read_parquet(tmp_path)
check("still exactly 4 rows total (2 expanding + 2 rolling) -- no duplicates from the re-run",
      len(result3) == 4)
check("expanding's rows now reflect the RE-RUN's new values, not the stale originals",
      set(result3[result3["wfa_variant"] == "expanding"]["sharpe"]) == {-0.9999, 0.8888})
check("rolling's rows are untouched by the expanding re-run",
      set(result3[result3["wfa_variant"] == "rolling"]["sharpe"]) == {-0.4779, 0.2175})

os.remove(tmp_path)
print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
