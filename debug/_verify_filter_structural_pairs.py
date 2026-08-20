"""
debug/_verify_filter_structural_pairs.py -- synthetic verification for
universe_loader.filter_structural_pairs(), built to close the SPY/VOO gap
found in the 2026-08-16 3y/5y/10y window comparison (see docs/HANDOFF.md).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from universe_loader import filter_structural_pairs

checks = []


def check(name, cond):
    checks.append((name, cond))
    print(f"{'PASS' if cond else 'FAIL'}: {name}")


candidates = [
    {"symbol_a": "SPY", "symbol_b": "VOO", "pearson_corr": 0.9988},
    {"symbol_a": "GOOGL", "symbol_b": "GOOG", "pearson_corr": 0.97},
    {"symbol_a": "RR.L", "symbol_b": "GVKEY100499_01W", "pearson_corr": 0.9990},
    {"symbol_a": "HBAN", "symbol_b": "KEY", "pearson_corr": 0.657},
    {"symbol_a": "GVKEY001166_02W", "symbol_b": "GVKEY001166_01W", "pearson_corr": 0.614},
    {"symbol_a": "AZN.L", "symbol_b": "GVKEY028272_01W", "pearson_corr": 0.85},
]

kept, dropped = filter_structural_pairs(candidates)
dropped_pairs = {(p["symbol_a"], p["symbol_b"]) for p in dropped}
kept_pairs = {(p["symbol_a"], p["symbol_b"]) for p in kept}

check("SPY/VOO dropped (index-tracking)", ("SPY", "VOO") in dropped_pairs)
check("GOOGL/GOOG dropped (known share-class)", ("GOOGL", "GOOG") in dropped_pairs)
check("RR.L/GVKEY100499_01W dropped (GVKEY cross-listing, corr>=0.99)",
      ("RR.L", "GVKEY100499_01W") in dropped_pairs)
check("HBAN/KEY kept (genuinely distinct companies)", ("HBAN", "KEY") in kept_pairs)
check("GVKEY001166_02W/_01W kept (same-GVKEY dual-listing is NOT this filter's job)",
      ("GVKEY001166_02W", "GVKEY001166_01W") in kept_pairs)
check("AZN.L/GVKEY028272_01W kept (below 0.99 cross-listing threshold)",
      ("AZN.L", "GVKEY028272_01W") in kept_pairs)
check("no pairs lost or duplicated", len(kept) + len(dropped) == len(candidates))

n_fail = sum(1 for _, c in checks if not c)
print(f"\n{len(checks) - n_fail}/{len(checks)} checks passed")
sys.exit(1 if n_fail else 0)
