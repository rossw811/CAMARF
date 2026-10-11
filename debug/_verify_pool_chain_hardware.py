"""
Hardware check for the pool chain (Ross 2026-10-10: "before running the scripts make sure it's optimized for the
hardware"; written before the changes). CachyOS = i7-10700K, 8 cores / 16 threads, 46 GB. The discovery scan's measured
setup on this machine: Config.RUNTIME.N_WORKERS process workers with each worker's BLAS capped at 1 thread
(analysis._limit_worker_blas_threads; without it 15 workers x ~16 OpenBLAS threads oversubscribed the CPU).
Checks, per process-pool script in the chain (episodic_pairs_adapter, regenerate_pool_spread_series, strategy_search):
  1. its --workers default is Config.RUNTIME.N_WORKERS (derived from os.cpu_count(); the adapter defaulted to 1 --
     BUG-D110's ~28 s/pair sequential -- and strategy_search to cpu_count // 2);
  2. every process pool it creates passes the BLAS-capping initializer.
Run: python debug/_verify_pool_chain_hardware.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASS, FAIL = [], []
SCRIPTS = ["research/episodic_pairs_adapter.py", "research/regenerate_pool_spread_series.py",
           "research/strategy_search.py"]


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    for f in SCRIPTS:
        s = open(os.path.join(ROOT, f), encoding="utf-8").read()
        name = os.path.basename(f)
        d = re.search(r'add_argument\("--workers"[^)]*default=([^,)]+(?:\([^)]*\))?)', s)
        check(f"{name}.workers_default_derived", d is not None and "Config.RUNTIME.N_WORKERS" in d.group(1),
              d.group(1) if d else None)
        pools = re.findall(r"(ProcessPoolExecutor\([^)]*\)|\.Pool\([^)]*\))", s)
        check(f"{name}.pools_cap_blas", len(pools) > 0 and all("initializer=" in p and "blas" in p.lower() for p in pools),
              pools)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
