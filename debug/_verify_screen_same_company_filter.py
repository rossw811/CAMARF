"""
Review of the raw-rate re-derivation (2026-10-24): 66 of the 181 pairs passing BH on the full-universe 1D screen were
different share issues of one Compustat company (and more were share classes / ADR-home listings); the screen's
structural filter has no same-company rule. full_universe_eg_confirmation.drop_same_company applies the pool step's
rule (clean_pool_identity_pairs.same_company: identifier sets intersect) to the candidates BEFORE EG. Checks:
  1. pairs whose legs share a company id are dropped and returned; others kept, order preserved
  2. a leg with no ids never matches (kept)
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
    from full_universe_eg_confirmation import drop_same_company
except ImportError as e:
    check("drop_same_company exists", False, str(e))
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1)
ids = {"GVKEY065248_06W": frozenset({"g:065248"}), "GVKEY065248_01W": frozenset({"g:065248"}),
       "MOG-A": frozenset({"pc:1"}), "MOG": frozenset({"pc:1"}), "AAPL": frozenset({"pc:7"}), "XOM": frozenset({"pc:9"})}
pairs = [{"symbol_a": "GVKEY065248_06W", "symbol_b": "GVKEY065248_01W"}, {"symbol_a": "AAPL", "symbol_b": "XOM"},
         {"symbol_a": "MOG-A", "symbol_b": "MOG"}, {"symbol_a": "AAPL", "symbol_b": "NOIDS"}]
kept, dropped = drop_same_company(pairs, ids)
check("1 same-company pairs dropped, others kept in order",
      [(p["symbol_a"], p["symbol_b"]) for p in kept] == [("AAPL", "XOM"), ("AAPL", "NOIDS")] and len(dropped) == 2,
      str(kept))
check("2 leg without ids kept", any(p["symbol_b"] == "NOIDS" for p in kept))
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
