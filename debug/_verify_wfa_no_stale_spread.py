"""
Regression test (inconsistency sweep, 2026-09-27): wfa._load_spread silently fell back to output/results/<tf>_stale/
when the current spread file was missing, so walk-forward results could come from superseded spreads with no trace.
Checks (temp results dir): 1. only a stale file exists -> None (and a warning); 2. a current file exists -> it is used.
Run: python debug/_verify_wfa_no_stale_spread.py
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import wfa

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    root = tempfile.mkdtemp(prefix="verify_wfa_stale_")
    orig = wfa._ROOT
    wfa._ROOT = root
    try:
        tf_dir = wfa._TF_MAP["1D"][0]
        os.makedirs(os.path.join(root, "output", "results", tf_dir + "_stale"))
        os.makedirs(os.path.join(root, "output", "results", tf_dir))
        idx = pd.bdate_range("2024-01-01", periods=10)
        pd.DataFrame({"spread": 1.0}, index=idx).to_parquet(
            os.path.join(root, "output", "results", tf_dir + "_stale", "spread_series_A_B.parquet"))
        check("stale_only_not_used", wfa._load_spread("A", "B", "1D") is None)
        pd.DataFrame({"spread": 2.0}, index=idx).to_parquet(
            os.path.join(root, "output", "results", tf_dir, "spread_series_A_B.parquet"))
        d = wfa._load_spread("A", "B", "1D")
        check("current_used", d is not None and float(d["spread"].iloc[0]) == 2.0)
    finally:
        wfa._ROOT = orig
        shutil.rmtree(root, ignore_errors=True)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
