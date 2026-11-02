"""
mp_pool.worker_pool (2026-11-01): three research scripts built their Pool with mp.get_context("fork"), which does not
exist on Windows (the Amendment 7 chain runs on the Surface) -- and their workers read module globals the parent set
before the pool started (_PRE, _POOL_DF, _BACKUP), which a spawned worker would not see. Checks:
  1. the old construction fails where fork is unavailable (Windows: ValueError) -- reproduces the defect
  2. under spawn, a worker defined in the __main__ script sees the parent's globals passed to worker_pool, including a
     value computed at import time (a timestamp, like regenerate_pool_spread_series._BACKUP) -- the parent's value, not
     the child's re-import
  3. without the helper's globals a spawned worker sees the import-time defaults (why the helper is needed)
  4. the three scripts use the helper, not get_context("fork")
Run: python debug/_verify_mp_pool_spawn.py
"""
import multiprocessing as mp
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

STAMP = f"{time.time_ns()}"      # import-time value: a re-import in a spawned child gets a different one
_PRE = {}


def _work(i):
    return i, STAMP, sorted(_PRE)


def main():
    passed = failed = 0

    def check(name, cond, detail=""):
        nonlocal passed, failed
        passed += bool(cond)
        failed += not cond
        print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")

    has_fork = "fork" in mp.get_all_start_methods()
    if has_fork:
        check("1 old construction fails without fork (skipped: this platform has fork)", True)
    else:
        try:
            mp.get_context("fork")
            check("1 old construction fails without fork", False, "get_context('fork') succeeded")
        except ValueError as e:
            check("1 old construction fails without fork", True, str(e))

    try:
        import mp_pool
    except ImportError as e:
        check("mp_pool importable", False, str(e))
        print(f"\n{passed} passed, {failed} failed")
        sys.exit(1)

    global _PRE
    _PRE = {"1D": {"AAA": 1}, "1h": {}}
    with mp_pool.worker_pool(2, _work, {"_PRE": _PRE, "STAMP": STAMP}, start_method="spawn") as pool:
        out = pool.map(_work, range(4))
    check("2 spawn: worker sees the parent's globals (incl. its import-time stamp)",
          all(s == STAMP and p == ["1D", "1h"] for _, s, p in out), f"{out[0]} parent {STAMP}")

    with mp.get_context("spawn").Pool(2) as pool:
        bare = pool.map(_work, range(2))
    check("3 spawn without the helper: defaults, not the parent's state",
          all(p == [] and s != STAMP for _, s, p in bare), f"{bare[0]}")

    src = {f: open(os.path.join(ROOT, "research", f), encoding="utf-8").read()
           for f in ("regenerate_pool_spread_series.py", "strategy_search.py", "edge_accounting.py")}
    bad = [f for f, s in src.items() if 'get_context("fork")' in s or "mp_pool.worker_pool" not in s]
    check("4 scripts use mp_pool.worker_pool", not bad, f"still fork-only: {bad}")

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
