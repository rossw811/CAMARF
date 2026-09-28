"""
Regression test for code-review finding U1 (2026-09-26): universe_loader's WRDS/Binance/IBKR/memo cache dirs were
RELATIVE paths ("output/cache/wrds"), so load_full_universe run from any directory other than the project root
silently returned only the ~1,700-symbol yfinance universe (and memoized that shrunken result); there was no
universe-size guard. Now the dirs are anchored to the module's own location, and requesting WRDS when zero WRDS
files are found raises instead of silently shrinking.
Checks: (1) the cache-dir constants are absolute; (2) from a foreign cwd the WRDS dir still resolves to the real
cache (file count > 0); (3) pointing the WRDS dir at an empty folder with include_wrds=True raises.
Run: python debug/_verify_loader_cwd_independent.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import universe_loader as ul

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    dirs = [ul._WRDS_CACHE_DIR, ul._BINANCE_CACHE_DIR, ul._IBKR_CACHE_DIR, ul._MEMO_CACHE_DIR]
    check("dirs_absolute", all(os.path.isabs(d) for d in dirs), f"{dirs}")
    here = os.getcwd()
    with tempfile.TemporaryDirectory() as t:
        os.chdir(t)
        try:
            n = len([f for f in os.listdir(ul._WRDS_CACHE_DIR) if f.endswith("_1D.parquet")]) if os.path.isdir(ul._WRDS_CACHE_DIR) else 0
            check("wrds_dir_resolves_from_foreign_cwd", n > 0, f"WRDS 1D files visible: {n}")
        finally:
            os.chdir(here)
    orig = ul._WRDS_CACHE_DIR
    with tempfile.TemporaryDirectory() as empty:
        ul._WRDS_CACHE_DIR = empty
        try:
            raised = False
            try:
                ul.load_full_universe("1D", include_yfinance=False, include_binance=False, use_memo_cache=False)
            except RuntimeError:
                raised = True
            check("empty_wrds_raises", raised)
        finally:
            ul._WRDS_CACHE_DIR = orig
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
