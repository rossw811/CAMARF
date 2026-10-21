"""
BUG-D38 recurrence guard (2026-10-20). The 2026-06 fix was a one-time cache cleanup: get_intraday_fallback still
replaced the current default period with any cached per-ticker yf_period_* value, with no expiry -- a stale "60d" at
1h (420 bars < MIN_BARS_REQUIRED) failed silently forever. Since the attempts are [default, "max"], the only cached
value the current code can produce besides the default is "max". Checks for data._resolve_yf_period(default, cached):
  1. no cache -> default; 2. cached "max" -> "max"; 3. a cached value other than the default or "max" (stale) -> the
  default; 4. get_intraday_fallback uses the resolver.
"""
import inspect
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


import data  # noqa: E402

try:
    r = data._resolve_yf_period
    check("1. no cache -> default", r("730d", None) == "730d")
    check("2. cached max honoured", r("730d", "max") == "max")
    check("3. stale cached 60d at 1h -> default 730d", r("730d", "60d") == "730d", r("730d", "60d"))
    check("3b. cached equal to default", r("60d", "60d") == "60d")
except AttributeError as e:
    check("data._resolve_yf_period exists", False, str(e))
src = inspect.getsource(data.YFinanceFeed.get_intraday_fallback)
check("4. get_intraday_fallback uses _resolve_yf_period", "_resolve_yf_period(" in src)
print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(1 if failed else 0)
