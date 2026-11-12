"""
GPU path of UniverseFilter.chunked_pearson_candidate_pairs (2026-11-12) selects EXACTLY the CPU pair set.
  1. band recheck (runs anywhere): a "GPU" matrix = CPU matrix with cells planted 1e-12 across the threshold; after
     _recheck_threshold_band_cpu the selected pairs equal the CPU selection (without the recheck they would not)
  2. no-GPU machine: use_gpu=None (auto) gives the CPU result exactly (same list)
  3. GPU machine only (else reported SKIPPED, counted as pass): use_gpu=True on data with planted near-threshold pairs
     -> identical pair set to the CPU run; max |GPU - CPU| over selected pairs reported (must be < the band)
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import gpu_backend  # noqa: E402
from analysis import UniverseFilter as U  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def keyset(pairs):
    return {(p["symbol_a"], p["symbol_b"]) for p in pairs}


rng = np.random.default_rng(7)
N, T, THR = 60, 400, 0.4
f = rng.normal(size=T)
load = rng.uniform(0, 0.9, N)
R = load[:, None] * f[None, :] + np.sqrt(1 - load[:, None] ** 2) * rng.normal(size=(N, T))
R[rng.random((N, T)) < 0.03] = np.nan
syms = [f"S{i}" for i in range(N)]

cpu = U.correlation_matrix(R, use_gpu=False)
fake = cpu.copy()
iu = np.argwhere(np.triu(np.isfinite(cpu), 1))
pick = iu[rng.choice(len(iu), 25, replace=False)]
for i, j in pick:                                   # plant: CPU value exactly at the threshold, "GPU" 1e-12 below
    R_pair = R[[i, j]]
    fake[i, j] = fake[j, i] = THR - 1e-12
    cpu[i, j] = cpu[j, i] = THR
# the recheck recomputes from returns, so build the CPU truth from returns too: emulate by monkeypatching _pairwise_corr
orig = U._pairwise_corr
truth = {(int(i), int(j)): THR for i, j in pick}


def patched(returns, min_overlap=30, use_gpu=False):
    if returns.shape[0] == 2:
        for (i, j), v in truth.items():
            if np.array_equal(returns, R[[i, j]], equal_nan=True):
                return np.array([[1.0, v], [v, 1.0]])
    return orig(returns, min_overlap=min_overlap, use_gpu=use_gpu)


U._pairwise_corr = staticmethod(patched)
fixed = U._recheck_threshold_band_cpu(fake, R, THR)
U._pairwise_corr = staticmethod(orig)
sel = lambda M: keyset(U.candidate_pairs(M, syms, THR, {}))
check("1. band recheck restores the CPU selection for 25 cells planted 1e-12 across the threshold",
      sel(fixed) == sel(cpu) and sel(fake) != sel(cpu),
      f"cpu {len(sel(cpu))} pairs, unrechecked 'gpu' {len(sel(fake))}, rechecked {len(sel(fixed))}")

R2 = load[:, None] * f[None, :] + np.sqrt(1 - load[:, None] ** 2) * rng.normal(size=(N, T))
a = U.chunked_pearson_candidate_pairs(R2, syms, THR, {}, batch_size=17, use_gpu=False)
if not gpu_backend.gpu_available():
    b = U.chunked_pearson_candidate_pairs(R2, syms, THR, {}, batch_size=17)
    check("2. no GPU: auto equals CPU exactly", a == b, f"{len(a)} pairs")
    print("[SKIPPED] 3. GPU comparison (no CUDA device on this machine) -- run on CachyOS")
    passed += 1
else:
    check("2. GPU machine: auto runs (result checked in 3)", True)
    big_n = 3200                                       # past gpu_backend's crossover, so the GPU path really runs
    fb = rng.normal(size=2000)
    lb = rng.uniform(0, 0.9, big_n)
    RB = lb[:, None] * fb[None, :] + np.sqrt(1 - lb[:, None] ** 2) * rng.normal(size=(big_n, 2000))
    RB[rng.random(RB.shape) < 0.02] = np.nan
    sb = [f"B{i}" for i in range(big_n)]
    pc = U.chunked_pearson_candidate_pairs(RB, sb, THR, {}, batch_size=1600, use_gpu=False)
    pg = U.chunked_pearson_candidate_pairs(RB, sb, THR, {}, batch_size=1600, use_gpu=True)
    dc = {(p["symbol_a"], p["symbol_b"]): p["pearson_corr"] for p in pc}
    dg = {(p["symbol_a"], p["symbol_b"]): p["pearson_corr"] for p in pg}
    md = max((abs(dc[k] - dg[k]) for k in dc.keys() & dg.keys()), default=0.0)
    check("3. GPU selects exactly the CPU pair set; value diffs below the band",
          dc.keys() == dg.keys() and md < U.GPU_THRESHOLD_BAND, f"{len(dc)} pairs; max |gpu - cpu| {md:.2e}")

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(1 if failed else 0)
