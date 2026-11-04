"""
Tier 2 candidate list is one definition for fresh and resumed scan runs (A7 review 2026-11-04: fresh runs passed all
Pearson candidates, 1,096,062, resumed arms the 1,070,361 rows Tier 1 kept).
  1. tier2_candidates maps Tier 1 rows to {symbol_a, symbol_b, pearson_corr}, order kept;
  2. both main() paths (resume from the tier1 file, fresh compute) build `pairs` with it -- no second definition left;
  3. the claim that dropping Tier 1's insufficient-overlap pairs changes no window: a pair whose full-sample longest
     gap-respecting segment is < 60 bars gets insufficient_overlap from _eg_worker in every window as well.
Run: python debug/_verify_tier2_candidates.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "research")]
import numpy as np

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


src = open(os.path.join(ROOT, "research", "wrds_deep_history_episodic_scan.py"), encoding="utf-8").read()
try:
    import wrds_deep_history_episodic_scan as S
    rows = [{"symbol_a": "A", "symbol_b": "B", "pearson_corr": 0.9, "pvalue": 0.01, "fdr_confirmed": True},
            {"symbol_a": "C", "symbol_b": "D", "pearson_corr": 0.8, "pvalue": 0.5, "fdr_confirmed": False}]
    out = S.tier2_candidates(rows)
    check("1 tier2_candidates: three keys, order kept", out == [{"symbol_a": "A", "symbol_b": "B", "pearson_corr": 0.9},
                                                               {"symbol_a": "C", "symbol_b": "D", "pearson_corr": 0.8}], out)
except AttributeError as e:
    check("1 tier2_candidates: three keys, order kept", False, str(e))

n_calls = len(re.findall(r"^\s+pairs = tier2_candidates\(", src, re.M))
old = 'tier1_df[["symbol_a", "symbol_b", "pearson_corr"]].to_dict("records")' in src
check("2 both main() paths build pairs with tier2_candidates", n_calls == 2 and not old, f"calls {n_calls}, old path left {old}")

from analysis import _eg_worker
rng = np.random.default_rng(0)
n = 2000
a = np.cumsum(rng.normal(size=n))
b = a + rng.normal(size=n)
b_sparse = np.full(n, np.nan)
b_sparse[700:750] = b[700:750]                      # one 50-bar overlap block plus 8 isolated bars = 58 < 60
b_sparse[::250] = b[::250]                          # (on 1D no gap breaks a segment by default: the count is what binds)
full = _eg_worker(("A", "B", a, b_sparse, 1, "1D"))
wins = [_eg_worker(("A", "B", a[s:s + 504], b_sparse[s:s + 504], 1, "1D")) for s in range(0, n - 504, 126)]
check("3 insufficient full-sample overlap => every window insufficient too",
      full.get("error") == "insufficient_overlap" and all(w.get("error") == "insufficient_overlap" for w in wins),
      f"full {full.get('error')} n={full.get('n_overlap')}; windows {sorted({w.get('error') for w in wins})}")

print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
