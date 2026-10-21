"""
W6.4 (2026-10-20): stats.py's remaining silent exception handlers (spread loaders, GPD/GARCH fits, the GARCH AIC row,
the permutation test's reference Sharpe) now log a warning with the cause. Checks: an unreadable spread file and a
failing GPD fit each produce a WARNING naming the cause, and no `except Exception:` followed by a bare pass / continue
/ return remains in stats.py.
"""
import logging
import os
import re
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


import stats  # noqa: E402


class _H(logging.Handler):
    def __init__(self):
        super().__init__(); self.msgs = []

    def emit(self, r):
        if r.levelno >= logging.WARNING:
            self.msgs.append(r.getMessage())


h = _H(); stats.log.addHandler(h)
with tempfile.TemporaryDirectory() as td:
    bad = os.path.join(td, "spread_series_A_B.parquet")
    open(bad, "wb").write(b"not a parquet file")
    orig = stats.glob.glob
    stats.glob.glob = lambda pat: [bad]
    try:
        stats._load_spread_series("A", "B", "1D")
        stats._load_spread_df("A", "B", "1D")
    finally:
        stats.glob.glob = orig
check("unreadable spread file -> warning with the path", sum(bad in m for m in h.msgs) >= 1, f"{h.msgs[:2]}")
orig_fit = stats.genpareto.fit
stats.genpareto.fit = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
try:
    out = stats._fit_gpd(np.linspace(-5, 5, 400))
finally:
    stats.genpareto.fit = orig_fit
check("GPD fit failure -> NaN and a warning", np.isnan(out[0]) and any("GPD fit failed" in m for m in h.msgs))
src = open(os.path.join(ROOT, "stats.py"), encoding="utf-8").read()
silent = re.findall(r"except Exception:\s*\n\s*(pass|continue|return\b[^\n]*)\s*\n", src)
check("no silent `except Exception:` handlers left in stats.py", not silent, f"{silent}")
print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(1 if failed else 0)
