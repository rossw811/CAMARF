"""
S31 / R1.3 option (c) (Ross 2026-10-10; FIX 2026-10-20): the S&P 500 membership gate applies only when both legs
resolve to a CRSP PERMNO, so US-US pairs are gated and pairs with a Compustat Global leg are not. Mixing them has no
clean interpretation, so each pool pair carries its arm and results are reported per arm. Checks for
clean_pool_identity_pairs.discovery_arm: CRSP-CRSP -> "us_us_gated"; GVKEY-GVKEY -> "international"; one of each ->
"mixed"; main() writes the column.
"""
import inspect
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


import clean_pool_identity_pairs as c  # noqa: E402
try:
    check("CRSP-CRSP", c.discovery_arm("AAPL", "PERMNO123") == "us_us_gated")
    check("intraday", c.discovery_arm("ALGN", "TER", "1h") == "intraday_ungated")
    check("GVKEY-GVKEY", c.discovery_arm("GVKEY000001_01W", "GVKEY000002_01W") == "international")
    check("mixed", c.discovery_arm("ASML", "GVKEY061214_01W") == "mixed")
except AttributeError as e:
    check("discovery_arm exists", False, str(e))
# 2026-10-25: the cleaning loop (and the arm column) moved into clean_pool, which main calls
check("main() writes the arm column", '"arm"' in inspect.getsource(c.clean_pool) and "clean_pool(" in inspect.getsource(c.main))
print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(1 if failed else 0)
