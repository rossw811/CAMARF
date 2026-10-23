"""
N13 (2026-10-22): the full-universe correlation prefilter and EG confirmation wrote the same output paths whatever
--tf was, so a 1M run would overwrite the 1D candidates and confirmed pairs. Both now take their paths from one helper
(full_universe_correlation_prefilter.screen_paths). Checks:
  1. 1D paths are unchanged (existing files and readers keep working)
  2. any other timeframe gets distinct paths that include the timeframe
  3. the confirmation stage reads exactly the chunk directory the prefilter writes, per timeframe
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


try:
    from full_universe_correlation_prefilter import screen_paths
except ImportError as e:
    check("screen_paths exists", False, str(e))
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1)

d = screen_paths("1D", 10)
check("1 1D paths unchanged",
      d["candidates"] == "output/research/full_universe_correlation_prefilter_candidates_10y.parquet"
      and d["chunks"] == "output/research/full_universe_correlation_prefilter_candidates_10y_chunks"
      and d["confirmed"] == "output/research/full_universe_eg_confirmed_pairs_10y.parquet", str(d))
m = screen_paths("1M", 10)
check("2 1M paths distinct and labelled", all(m[k] != d[k] and "1M" in m[k] for k in d), str(m))
src = open(os.path.join(ROOT, "research", "full_universe_eg_confirmation.py"), encoding="utf-8").read()
check("3 confirmation stage uses screen_paths", "screen_paths(args.tf, args.lookback_years)" in src)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
