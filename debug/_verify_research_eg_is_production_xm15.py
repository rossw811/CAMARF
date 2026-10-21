"""
SWEEP-C4-2 / X-M15 (2026-10-20): every research script's Engle-Granger p-value comes from the production test
(analysis.eg_pvalue_pair / eg_pvalue_segment: both directions, max p, production's gap-respecting segment). Before,
11 scripts called statsmodels coint() directly -- one direction, on arrays spliced across data gaps. Exempt, by design:
scripts that mirror production's OWN one-direction fixed-lag rolling test (coint_fraction_rolling /
_batched_eg_fixed_lag) -- they must match that test, not the discovery screen. Check: no other research script calls
coint( directly, and analysis.eg_pvalue_segment matches eg_pvalue_pair on a gap-free pair.
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
passed = failed = 0
EXEMPT = {"coint_frac_window_grid.py": "mirrors coint_fraction_rolling (one direction, fixed lag 1)",
          "gpu_batched_eg_fixed_lag.py": "mirrors analysis._batched_eg_fixed_lag (one direction, fixed lag)"}


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


import ast  # noqa: E402
offenders = []
rdir = os.path.join(ROOT, "research")
for f in sorted(os.listdir(rdir)):
    if not f.endswith(".py") or f in EXEMPT:
        continue
    try:
        tree = ast.parse(open(os.path.join(rdir, f), encoding="utf-8", errors="replace").read())
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
            if name == "coint":
                offenders.append(f"{f}:{node.lineno}")
check("no research script calls statsmodels coint() directly (except exempt mirrors)", not offenders, f"{offenders}")
from analysis import eg_pvalue_pair, eg_pvalue_segment  # noqa: E402
rng = np.random.default_rng(4)
x = np.cumsum(rng.normal(0, 0.01, 500)) + 3
y = 0.8 * x + rng.normal(0, 0.01, 500)
p1, _ = eg_pvalue_pair(y, x, 5, "1D")
p2, n2 = eg_pvalue_segment(y, x, 5, "1D")
check("eg_pvalue_segment == eg_pvalue_pair on a gap-free pair", np.isclose(p1, p2) and n2 == 500, f"{p1} {p2}")
print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(1 if failed else 0)
