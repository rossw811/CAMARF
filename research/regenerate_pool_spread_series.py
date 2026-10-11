"""
research/regenerate_pool_spread_series.py -- rebuild the Purity pool's spread_series files from the corrected
data layer (2026-09-27).

Why: backtest.py reads each pair's output/results/{tf}/spread_series_{A}_{B}.parquet. For plain-ticker legs
episodic_pairs_adapter builds these from the yfinance daily cache (code review R1.4), which until tonight
carried the D1 fabricated flat bars and was frozen at 2026-06-17 (D2); 74 pool pairs also had no spread file
at all (deleted by an earlier cleanup; they silently never traded). No new analysis logic: this drives the
adapter's own path (_load_aligned -> AnalysisPipeline._build_pair_result -> write_spread_series), with the
adapter's own once-in-the-parent preload for placeholder (PERMNO/GVKEY) symbols.

Every existing spread file is MOVED to output/results/_spread_backup_20260927/{tf_dir}/ first; a pair that
fails to rebuild gets its original moved back and is reported. After this, re-run
research/squeeze_momentum_features.py --pairs-file <pool> to restore the gate columns.

Usage (CachyOS): python research/regenerate_pool_spread_series.py [--pairs ...] [--workers N]
"""
import argparse
import os
import shutil
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from data import DataStore
from research import episodic_pairs_adapter as ad

# One backup folder PER RUN (never reused): the first run's folder holds the ORIGINAL files, and a re-run
# must not move its own freshly written files onto those paths (found 2026-09-27 before any overwrite).
_BACKUP = os.path.join("output", "results", f"_spread_backup_{time.strftime('%Y%m%d_%H%M%S')}")
_PRE = {}


def _spread_path(a, b, tf):
    return os.path.join(ad._RESULTS_DIR, ad._tf_dir(tf), f"spread_series_{a}_{b}.parquet")


def _one(task):
    from analysis import AnalysisPipeline
    a, b, tf = task
    dst = _spread_path(a, b, tf)
    bak = os.path.join(_BACKUP, ad._tf_dir(tf), os.path.basename(dst))
    try:
        al = ad._load_aligned(a, b, tf, as_of_date=None, preloaded=_PRE.get(tf))
        if al is None:
            raise RuntimeError("insufficient data / alignment failed")
        built = AnalysisPipeline._build_pair_result({"symbol_a": a, "symbol_b": b}, al, tf)
        if built is None:
            raise RuntimeError("_build_pair_result returned None")
        ad.write_spread_series(a, b, tf, built[1])
        return a, b, tf, "rebuilt", len(built[1]["index"])
    except Exception as e:
        if os.path.exists(bak) and not os.path.exists(dst):
            shutil.move(bak, dst)
            return a, b, tf, f"FAILED, original restored: {e}", 0
        return a, b, tf, f"FAILED, no original: {e}", 0


def main():
    import multiprocessing as mp
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default=os.path.join("output", "research", "purity_pairs_pit_k1.parquet"))
    ap.add_argument("--workers", type=int, default=Config.RUNTIME.N_WORKERS)   # derived (T11 2026-10-04), was 8
    args = ap.parse_args()
    P = pd.read_parquet(args.pairs)
    tasks = list(zip(P["symbol_a"], P["symbol_b"], P["tf_label"]))
    for a, b, tf in tasks:
        src = _spread_path(a, b, tf)
        if os.path.exists(src):
            dst = os.path.join(_BACKUP, ad._tf_dir(tf), os.path.basename(src))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.exists(dst):
                raise RuntimeError(f"refusing to overwrite existing backup {dst}")
            shutil.move(src, dst)
    print(f"backup of pre-existing files -> {_BACKUP}", flush=True)
    for tf in sorted(set(P["tf_label"])):
        syms = set(P.loc[P["tf_label"] == tf, "symbol_a"]) | set(P.loc[P["tf_label"] == tf, "symbol_b"])
        needed = {s for s in syms if (lambda d: d is None or d.empty)(DataStore.load(s, tf))}
        if needed:
            print(f"{tf}: pre-resolving {len(needed)} placeholder symbols via the full-universe loader (once)", flush=True)
            fu = ad._get_full_universe(tf)
            _PRE[tf] = {s: fu[s] for s in needed if s in fu}
            del fu
            print(f"{tf}: resolved {len(_PRE[tf])}/{len(needed)}", flush=True)
    t0 = time.time()
    res = []
    from analysis import _limit_worker_blas_threads   # 1 BLAS thread per worker (hardware check, 2026-10-10)
    with mp.get_context("fork").Pool(args.workers, initializer=_limit_worker_blas_threads) as pool:
        for i, r in enumerate(pool.imap_unordered(_one, tasks), 1):
            res.append(r)
            if i % 100 == 0 or i == len(tasks):
                print(f"{i}/{len(tasks)} ({time.time() - t0:.0f}s)", flush=True)
    R = pd.DataFrame(res, columns=["symbol_a", "symbol_b", "tf_label", "status", "n_bars"])
    R.to_parquet(os.path.join("output", "research", "regenerate_pool_spread_series_report.parquet"))
    print(R["status"].str.split(":").str[0].value_counts().to_string())
    print(R[R["status"] != "rebuilt"].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from pipeline_stages import stage
    stage("pool_spreads").record()  # lineage (research/pipeline_stages.py)
