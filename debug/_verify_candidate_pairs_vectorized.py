"""
UniverseFilter.candidate_pairs (2026-11-12): hit search vectorized (np.nonzero on the upper triangle). Output must equal
the former per-cell Python double loop exactly -- same pairs, same order, same values -- including NaN cells, cells exactly
at the threshold, negative correlations, and the Spearman / rolling / dCor tagging.
  1. random matrices with NaN and exact-threshold cells: identical list of dicts (order included)
  2. a real-sized block (3000 x 3000): identical, and the vectorized version is faster (timed, reported)
"""
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from analysis import UniverseFilter  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def loop_reference(corr, symbols, threshold, acm, spearman=None, rolling_avg=None, dcor=None):
    """The pre-2026-11-12 body, verbatim in logic."""
    n = corr.shape[0]
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            c = corr[i, j]
            if not np.isfinite(c) or abs(c) < threshold:
                continue
            sa, sb = symbols[i], symbols[j]
            ca, cb = acm.get(sa, "unknown"), acm.get(sb, "unknown")
            sp = float(spearman[i, j]) if spearman is not None and np.isfinite(spearman[i, j]) else np.nan
            ro = float(rolling_avg[i, j]) if rolling_avg is not None and np.isfinite(rolling_avg[i, j]) else np.nan
            dc = float(dcor[i, j]) if dcor is not None and np.isfinite(dcor[i, j]) else np.nan
            sp_ok = np.isfinite(sp) and abs(sp) >= threshold
            ro_ok = np.isfinite(ro) and abs(ro) >= threshold
            tier = {3: "gold", 2: "silver", 1: "bronze"}[1 + int(sp_ok) + int(ro_ok)]
            pairs.append({"symbol_a": sa, "symbol_b": sb, "asset_class_a": ca, "asset_class_b": cb,
                          "pearson_corr": float(c), "spearman_corr": sp, "rolling_avg_corr": ro, "dcor": dc,
                          "pearson_confirmed": True, "spearman_confirmed": sp_ok, "rolling_confirmed": ro_ok,
                          "confidence_tier": tier, "is_cross_asset": ca != cb})
    return pairs


def same(a, b):
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if x.keys() != y.keys():
            return False
        for k in x:
            vx, vy = x[k], y[k]
            if isinstance(vx, float) and np.isnan(vx):
                if not (isinstance(vy, float) and np.isnan(vy)):
                    return False
            elif vx != vy:
                return False
    return True


def sym_mat(rng, n, nan_share=0.05):
    m = rng.uniform(-1, 1, (n, n))
    m = (m + m.T) / 2
    m[rng.random((n, n)) < nan_share] = np.nan
    m = np.triu(m, 1)
    m = m + m.T
    np.fill_diagonal(m, 1.0)
    return m


rng = np.random.default_rng(20261112)
ok = True
for trial in range(20):
    n = int(rng.integers(2, 80))
    C, S, R, D = (sym_mat(rng, n) for _ in range(4))
    thr = 0.4
    C[0, -1] = C[-1, 0] = thr          # exactly at the threshold: kept by both rules
    if n > 2:
        C[0, 1] = C[1, 0] = -thr        # negative, exactly at -threshold: kept (|c| >= thr)
    syms = [f"S{i}" for i in range(n)]
    acm = {s: ("equity" if i % 3 else "fx") for i, s in enumerate(syms)}
    kw = dict(spearman=S, rolling_avg=R, dcor=D) if trial % 2 else {}
    ok &= same(UniverseFilter.candidate_pairs(C, syms, thr, acm, **kw), loop_reference(C, syms, thr, acm, **kw))
check("1. identical output on 20 random matrices (NaN, +/- exact-threshold cells, with/without tags)", ok)

n = 3000
C = sym_mat(rng, n, 0.01)
syms = [f"S{i}" for i in range(n)]
acm = {}
t = time.perf_counter(); v = UniverseFilter.candidate_pairs(C, syms, 0.97, acm); tv = time.perf_counter() - t
t = time.perf_counter(); r = loop_reference(C, syms, 0.97, acm); tr = time.perf_counter() - t
check("2. 3000 x 3000 block identical; vectorized faster", same(v, r) and tv < tr,
      f"{len(v)} pairs; vectorized {tv:.2f}s vs loop {tr:.2f}s ({tr / max(tv, 1e-9):.0f}x)")

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(1 if failed else 0)
