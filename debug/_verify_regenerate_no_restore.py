"""
Review of 2c0c0f6a, F4 (Amendment 5 re-run): research/regenerate_pool_spread_series._one moved the PRE-RUN spread file
back when a rebuild failed -- a file built from the previous data (old D118 rule, unsealed 2026 rows) then traded as
if current, and the step still exited 0. Now a failed rebuild leaves NO spread file (the pair cannot trade), is
reported, and the pre-run file stays in the run's backup folder. Check: a pair whose aligned load fails, with a
pre-run file in the backup, ends with no spread file at the live path, the backup intact, and a FAILED status.
"""
import os
import sys
import tempfile

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


import research.regenerate_pool_spread_series as rg  # noqa: E402

with tempfile.TemporaryDirectory() as td:
    old_results, old_backup, old_load = rg.ad._RESULTS_DIR, rg._BACKUP, rg.ad._load_aligned
    rg.ad._RESULTS_DIR = os.path.join(td, "results")
    rg._BACKUP = os.path.join(td, "backup")
    rg.ad._load_aligned = lambda *a, **k: None                    # alignment fails
    try:
        bak = os.path.join(rg._BACKUP, rg.ad._tf_dir("1D"), "spread_series_AAA_BBB.parquet")
        os.makedirs(os.path.dirname(bak))
        pd.DataFrame({"spread": [1.0]}).to_parquet(bak)
        r = rg._one(("AAA", "BBB", "1D", pd.Timestamp("2020-01-31")))
        live = rg._spread_path("AAA", "BBB", "1D")
        check("no stale file restored; backup kept; reported FAILED",
              not os.path.exists(live) and os.path.exists(bak) and r[3].startswith("FAILED") and "restored" not in r[3],
              str(r))
    finally:
        rg.ad._RESULTS_DIR, rg._BACKUP, rg.ad._load_aligned = old_results, old_backup, old_load

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
