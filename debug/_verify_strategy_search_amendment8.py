"""
Amendment 8 (BUG-D123 re-run, Ross 2026-11-11) changes to research/strategy_search.py.
Checks:
  1. pool_fingerprint changes when a pair's spread-series file changes and the pool file does not (the re-run
     regenerates spreads with new half-life columns; trade files built from the old spreads must not be reused),
     and when a spread file is missing; it is stable when nothing changes.
  2. the hlbc arm: pools_for_arm("hlbc") = the same pool files under <pool>_hlbc names; half_life_column() gives
     half_life_rolling_bc for those and the Config default for the primary pools.
  3. a run task does not change the global Config.BACKTEST (copy.copy of a class returned the global itself):
     _run_one's config copy is independent, and it carries the arm's column.
Run: python debug/_verify_strategy_search_amendment8.py
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
import pandas as pd

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    import backtest as bt
    import strategy_search as ss
    from config import Config
    tf_dir, tf_label = bt._TF_DIRS[0]
    d = tempfile.mkdtemp(prefix="a8_")
    old_root = bt.SPREAD_ROOT
    try:
        bt.SPREAD_ROOT = os.path.join(d, "results")
        os.makedirs(os.path.join(bt.SPREAD_ROOT, tf_dir))
        pool = os.path.join(d, "pool.parquet")
        pd.DataFrame({"symbol_a": ["A", "C"], "symbol_b": ["B", "D"], "tf_label": [tf_label, tf_label],
                      "eligible_from": pd.to_datetime(["2010-01-01", "2011-01-01"])}).to_parquet(pool)
        sp = bt._spread_path(tf_dir, "A", "B")
        pd.DataFrame({"spread": [0.1, 0.2], "half_life_rolling": [20.0, 21.0]}).to_parquet(sp)
        pd.DataFrame({"spread": [0.3], "half_life_rolling": [9.0]}).to_parquet(bt._spread_path(tf_dir, "C", "D"))
        f0 = ss.pool_fingerprint(pool)
        check("1a stable when nothing changes", ss.pool_fingerprint(pool) == f0)
        pd.DataFrame({"spread": [0.1, 0.2], "half_life_rolling": [28.0, 29.0]}).to_parquet(sp)   # new half-lives
        f1 = ss.pool_fingerprint(pool)
        check("1b changes when a spread file changes (pool unchanged)", f1 != f0)
        os.remove(sp)
        check("1c changes when a spread file goes missing", ss.pool_fingerprint(pool) not in (f0, f1))
    finally:
        bt.SPREAD_ROOT = old_root
        shutil.rmtree(d, ignore_errors=True)

    pools = ss.pools_for_arm("hlbc") if hasattr(ss, "half_life_column") else {}
    check("2a hlbc pools = same files, _hlbc names",
          pools == {f"{k}_hlbc": v for k, v in ss.POOLS.items()}, sorted(pools))
    if hasattr(ss, "half_life_column"):
        check("2b column per pool", all(ss.half_life_column(k) == "half_life_rolling_bc" for k in pools)
              and all(ss.half_life_column(k) == Config.BACKTEST.HALF_LIFE_COLUMN for k in ss.POOLS))
    else:
        check("2b column per pool", False, "no half_life_column")

    # 3. run one cheap task on an empty pool: the engine runs, no pairs; the global config must be untouched
    before = {k: getattr(Config.BACKTEST, k) for k in ("ENTRY_ZSCORE", "STOP_ZSCORE", "EXIT_ZSCORE",
                                                        "MAX_HOLD_MULTIPLIER", "HALF_LIFE_COLUMN")}
    d = tempfile.mkdtemp(prefix="a8run_")
    old_out = ss._OUT
    try:
        ss._OUT = d
        name = "pit_k2_hlbc"
        ss._POOL_DF[name] = pd.DataFrame(columns=["symbol_a", "symbol_b", "tf_label", "eligible_from"])
        c = [g for g in ss.build_grid() if g["ENTRY_ZSCORE"] != before["ENTRY_ZSCORE"]][0]
        seen = {}
        orig = bt.BacktestEngine.__init__

        def spy(self, *a, **k):
            seen["col"] = getattr(k.get("cfg"), "HALF_LIFE_COLUMN", None)
            return orig(self, *a, **k)
        bt.BacktestEngine.__init__ = spy
        try:
            ss._run_one((name, c))
        finally:
            bt.BacktestEngine.__init__ = orig
        after = {k: getattr(Config.BACKTEST, k) for k in before}
        check("3a global Config.BACKTEST unchanged by a run task", after == before, (before, after))
        check("3b the arm's engine reads the corrected column", seen.get("col") == "half_life_rolling_bc", seen)
    finally:
        ss._OUT = old_out
        shutil.rmtree(d, ignore_errors=True)
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
