"""
Regression test for the BH-denominator part of code-review A1/S2 (2026-09-26): CointScanner combined the
two EG regression directions from successful results only, so a pair whose test CRASHED silently left
BH's m -- m shrank and every BH threshold loosened. Now (_combine_eg_directions):
  * both directions ok -> p = max(p_ab, p_ba) (the existing conservative rule, unchanged);
  * any direction crashed (exception) -> the pair ENTERS BH with p = 1.0 (attempted, not confirmable);
  * insufficient overlap (< 60 bars, never a real test) -> excluded but COUNTED and reported.

Run: python debug/_verify_eg_bh_denominator.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import _combine_eg_directions

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def ok(a, b, p):
    return {"symbol_a": a, "symbol_b": b, "ok": True, "error": "", "pvalue": p, "hedge_ratio": 1.0, "n_overlap": 500}


def bad(a, b, err):
    return {"symbol_a": a, "symbol_b": b, "ok": False, "error": err, "pvalue": 1.0, "hedge_ratio": float("nan"), "n_overlap": 0}


def main():
    cands = [{"symbol_a": "A", "symbol_b": "B"}, {"symbol_a": "C", "symbol_b": "D"}, {"symbol_a": "E", "symbol_b": "F"}]
    results = [ok("A", "B", 0.01), ok("B", "A", 0.03),                           # tested
               ok("C", "D", 0.02), bad("D", "C", "ValueError: broadcast"),       # crashed one way
               bad("E", "F", "insufficient_overlap"), bad("F", "E", "insufficient_overlap")]  # untestable
    combined, counts = _combine_eg_directions(cands, results)
    byp = {(c["symbol_a"], c["symbol_b"]): c for c in combined}
    check("tested_pair_max_p", abs(byp[("A", "B")]["pvalue"] - 0.03) < 1e-12, f"{byp.get(('A', 'B'))}")
    check("crashed_pair_in_m_with_p1", ("C", "D") in byp and byp[("C", "D")]["pvalue"] == 1.0)
    check("untestable_pair_excluded", ("E", "F") not in byp)
    check("m_is_2", len(combined) == 2, f"m={len(combined)}")
    check("counts_reported", counts == {"n_tested": 2, "n_crashed_counted_p1": 1, "n_insufficient_overlap_excluded": 1},
          f"{counts}")
    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
