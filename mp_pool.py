"""Process pool that works with fork (Linux: CachyOS, CI) and spawn (Windows: the Surface).

Research scripts set module globals in the parent before starting the pool (pre-resolved symbols, pool frames, a
per-run backup folder) and their workers read them. fork copies them; spawn re-imports the module, so a worker would
see the import-time defaults instead (and a different timestamp in any path computed at import). worker_pool passes
the named globals to each worker's initializer, which writes them into the module that defines the worker function
(`__mp_main__` in a spawned child when that function lives in the script being run). Under fork the behaviour is
unchanged: the same objects are set again. debug/_verify_mp_pool_spawn.py
"""
import importlib
import multiprocessing as mp
import sys


def _init(module_name, fn_name, state):
    from analysis import _limit_worker_blas_threads   # 1 BLAS thread per worker (hardware check, 2026-10-10)
    _limit_worker_blas_threads()
    if state:
        mod = sys.modules.get("__mp_main__") if module_name == "__main__" else None
        if mod is None:
            mod = sys.modules.get(module_name) or importlib.import_module(module_name)
        mod.__dict__.update(state)
        # A spawned child runs the main script through runpy and copies its namespace into __mp_main__, so the
        # worker function's own globals dict is a different object from mod.__dict__: update that one too.
        getattr(mod, fn_name).__globals__.update(state)


def worker_pool(n, fn, state=None, start_method=None):
    """Pool of `n` workers for `fn`; `state` = {global name: value} the workers must see as the parent set it."""
    method = start_method or ("fork" if "fork" in mp.get_all_start_methods() else "spawn")
    return mp.get_context(method).Pool(n, initializer=_init, initargs=(fn.__module__, fn.__name__, state or {}))
