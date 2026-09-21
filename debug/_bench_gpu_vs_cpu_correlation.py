"""
debug/_bench_gpu_vs_cpu_correlation.py -- real GPU-vs-CPU benchmark of
UniverseFilter.chunked_pearson_matrix at multiple N, re-confirming (per
Ross's direct instruction, 2026-09-20: "always test the gpu if it's better
wire it in") the guidance already documented in that function's own
docstring from an earlier 2026-08-23 benchmark: GPU is slower below
N~2,000-4,000 (kernel-launch/transfer overhead dominates), worth it only at
genuinely large (WRDS-expanded, 17k-44k symbol) universe scale. Re-run fresh
rather than trusted from the old note, since CachyOS's GPU/driver setup can
change (already true once this session -- see gpu_backend.py's own account
of a cupy/libcublas fix).

Only meaningful on a CUDA-capable machine (CachyOS) -- gpu_backend.gpu_
available() gates it; on the Windows dev box this just runs the CPU side and
reports GPU unavailable, same fail-safe convention as production code.

Usage:
    python debug/_bench_gpu_vs_cpu_correlation.py
    python debug/_bench_gpu_vs_cpu_correlation.py --sizes 1000 5000 17000 44000
"""
import argparse
import sys
import time

import numpy as np

sys.path.insert(0, ".")
from analysis import UniverseFilter
import gpu_backend

_DEFAULT_SIZES = [1000, 2000, 4000, 8000, 17000, 44000]


def _make_returns(n, t_len=1000, seed=42):
    rng = np.random.default_rng(seed)
    returns = rng.standard_normal((n, t_len)).astype(np.float64)
    mask = rng.random((n, t_len)) < 0.02
    returns[mask] = np.nan
    return returns


# 2026-09-21: a real OOM found live -- this benchmark holds BOTH the CPU and GPU result
# arrays in memory simultaneously for the correctness check below, and at N=44000 each
# (n,n) float64 array is ~15.5GB, so holding both at once is ~31GB+ before any other
# overhead. Killed the process twice (dmesg-confirmed: PIDs 1174420 and 2555008, both
# "Out of memory: Killed process ... (python)") on a 46GB machine before this was caught --
# the SSH-drop Monitor failures around the same time were a coincidental RED HERRING, not
# the real cause; re-checking dmesg directly (not just assuming from a Monitor error) is
# what actually found this, same "get the raw evidence, don't guess" discipline as every
# other OOM this session. Fixed below: only do the full-array correctness check below a
# safe size ceiling; above it, measure timing only and free each array before computing
# the next one (never hold both large arrays at once).
_CORRECTNESS_CHECK_MAX_N = 8000  # verified safe: this size completed cleanly before the OOM


def bench_one(n, batch_size=1500):
    import gc

    returns = _make_returns(n)
    check_correctness = n <= _CORRECTNESS_CHECK_MAX_N

    t0 = time.time()
    corr_cpu = UniverseFilter.chunked_pearson_matrix(returns, batch_size=batch_size, use_gpu=False)
    dt_cpu = time.time() - t0

    if not check_correctness:
        # Free the (n,n) CPU array BEFORE computing the GPU one -- the two must never
        # coexist above the safe ceiling (see module-level note on the OOM this caused).
        del corr_cpu
        gc.collect()
        corr_cpu = None

    dt_gpu = None
    gpu_matches = None
    if gpu_backend.gpu_available():
        t0 = time.time()
        corr_gpu = UniverseFilter.chunked_pearson_matrix(returns, batch_size=batch_size, use_gpu=True)
        dt_gpu = time.time() - t0
        if check_correctness:
            # Verify correctness, not just speed -- a fast wrong answer is worse than no GPU at all.
            finite_mask = np.isfinite(corr_cpu) & np.isfinite(corr_gpu)
            gpu_matches = bool(np.allclose(corr_cpu[finite_mask], corr_gpu[finite_mask], atol=1e-6))
        else:
            gpu_matches = "not checked (N above correctness-check ceiling, timing only)"
        del corr_gpu

    if corr_cpu is not None:
        del corr_cpu
    gc.collect()

    return dt_cpu, dt_gpu, gpu_matches


def main():
    p = argparse.ArgumentParser(description="GPU vs CPU benchmark for chunked_pearson_matrix")
    p.add_argument("--sizes", type=int, nargs="+", default=_DEFAULT_SIZES)
    p.add_argument("--batch-size", type=int, default=1500)
    args = p.parse_args()

    print(f"GPU available: {gpu_backend.gpu_available()}")
    if gpu_backend.gpu_available():
        print(f"Free VRAM: {gpu_backend.gpu_free_vram_gb():.2f}GB")
    print()

    results = []
    for n in args.sizes:
        print(f"N={n} ...")
        dt_cpu, dt_gpu, gpu_matches = bench_one(n, args.batch_size)
        if dt_gpu is not None:
            speedup = dt_cpu / dt_gpu if dt_gpu > 0 else float("inf")
            faster = "GPU FASTER" if speedup > 1.0 else "CPU FASTER"
            print(f"  CPU: {dt_cpu:.3f}s  GPU: {dt_gpu:.3f}s  speedup={speedup:.2f}x  "
                  f"({faster})  correctness_match={gpu_matches}")
        else:
            print(f"  CPU: {dt_cpu:.3f}s  GPU: not available")
        results.append({"n": n, "cpu_s": dt_cpu, "gpu_s": dt_gpu, "gpu_matches": gpu_matches})

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    crossover_n = None
    for r in results:
        if r["gpu_s"] is not None:
            speedup = r["cpu_s"] / r["gpu_s"] if r["gpu_s"] > 0 else float("inf")
            print(f"  N={r['n']:>6}: CPU={r['cpu_s']:.3f}s GPU={r['gpu_s']:.3f}s "
                  f"speedup={speedup:.2f}x match={r['gpu_matches']}")
            if speedup > 1.0 and crossover_n is None:
                crossover_n = r["n"]
        else:
            print(f"  N={r['n']:>6}: CPU={r['cpu_s']:.3f}s GPU=n/a")
    if crossover_n is not None:
        print(f"\nGPU becomes faster at or above N={crossover_n} (smallest tested N where it won).")
    else:
        print("\nGPU was not faster at any tested N (or GPU unavailable).")


if __name__ == "__main__":
    main()
