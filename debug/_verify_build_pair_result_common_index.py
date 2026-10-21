"""
A1 residual in _build_pair_result (found 2026-10-20 by the N11 re-run: multivariate_pit_predictors crashed with
"operands could not be broadcast together with shapes (360,) (504,)"). DataAligner.align_universe returns per-symbol
spans at 1D; analysis.py's own pipeline reindexes with align_to_common_index, but research callers
(pit_wfa_wrds_daily.screen_universe_at_cutoff and others) pass the spans straight in, and _build_pair_result pairs the
legs by POSITION. Different lengths -> crash; equal lengths with shifted dates -> silently pairs different days.
Checks: (1) legs of different spans build; (2) equal-length shifted legs give the same result as pre-aligned legs;
(3) already-shared input is unchanged.
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import logging  # noqa: E402
logging.disable(logging.CRITICAL)
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


from analysis import AnalysisPipeline, align_to_common_index  # noqa: E402
from data import DataAligner  # noqa: E402

rng = np.random.default_rng(3)
idx = pd.bdate_range("2015-01-02", periods=900)
x = np.cumsum(rng.normal(0, 0.01, 900)) + 3
noise = np.zeros(900); e = rng.normal(0, 0.005, 900)
for t in range(1, 900):
    noise[t] = 0.8 * noise[t - 1] + e[t]
A = pd.DataFrame({"close": np.exp(x), "volume": 1e6}, index=idx)
B = pd.DataFrame({"close": np.exp(0.9 * x + 0.2 + noise), "volume": 1e6}, index=idx)
meta = {"symbol_a": "AA", "symbol_b": "BB"}


def build(fa, fb):
    al = DataAligner.align_universe({"AA_1D": fa, "BB_1D": fb}, "1D")
    return AnalysisPipeline._build_pair_result(dict(meta), al, "1D"), al


try:
    r1, al1 = build(A, B.iloc[200:])                     # different spans
    check("1. different spans build (no broadcast error)", r1 is not None, f"{len(al1['AA'])} vs {len(al1['BB'])}")
except ValueError as ex:
    check("1. different spans build (no broadcast error)", False, str(ex)[:80])
try:
    fa, fb = A.iloc[:700], B.iloc[100:800]                # equal length 700, shifted by 100 days
    r2, al2 = build(fa, fb)
    ref = AnalysisPipeline._build_pair_result(dict(meta), align_to_common_index(al2), "1D")
    same = (r2 is not None and ref is not None
            and np.isclose(r2[0].hedge_ratio_ols, ref[0].hedge_ratio_ols, equal_nan=True))
    check("2. equal-length shifted legs paired by date, not position",
          same, f"{getattr(r2[0], 'hedge_ratio_ols', None) if r2 else None} vs {ref[0].hedge_ratio_ols if ref else None}")
except ValueError as ex:
    check("2. equal-length shifted legs paired by date, not position", False, str(ex)[:80])
r3, al3 = build(A, B)
ref3 = AnalysisPipeline._build_pair_result(dict(meta), align_to_common_index(al3), "1D")
check("3. shared-index input unchanged", np.isclose(r3[0].hedge_ratio_ols, ref3[0].hedge_ratio_ols))
print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(1 if failed else 0)
