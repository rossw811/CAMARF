"""
Standalone, read-only investigation: why do 5m and 30m yield ZERO confirmed
pairs while neighboring TFs (1m/3m/15m/1h) don't, even though their raw EG
pass rates aren't obviously lower (see Development.md's "TF-Level Funnel
Analysis" section)? Recomputes the correlation pre-filter + EG step for
5m, 15m (control — DOES yield survivors), and 30m directly, capturing the
FULL raw p-value array (not just summary counts, which is all the real
pipeline persists). Never touches analysis.py's saved output.
"""
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from config import Config
from data import DataAligner, UniverseBuilder
from analysis import UniverseFilter, CointScanner, _eg_worker


def investigate(tf_label: str, universe):
    asset_class_map = {sym: cls for sym, cls in universe.assets}
    exclusions = getattr(universe, "exclusion_set", set()) or set()

    tf_data_raw = {}
    for sym, _cls in universe.assets:
        if sym in exclusions:
            continue
        key = f"{sym}_{tf_label}"
        df = universe.data.get(key)
        if df is None:
            continue
        tf_data_raw[sym] = df
    print(f"[{tf_label}] {len(tf_data_raw)} assets have data")

    aligned = DataAligner.align_universe(
        {f"{sym}_{tf_label}": df for sym, df in tf_data_raw.items()}, tf_label
    )
    print(f"[{tf_label}] aligned: {len(aligned)} assets")

    t0 = time.time()
    candidates, retained_symbols, _ret, _corr, _order = UniverseFilter.run(
        aligned,
        asset_class_map,
        threshold=Config.UNIVERSE.MIN_PEARSON_CORR,
        tf_label=tf_label,
        return_matrices=True,
    )
    print(f"[{tf_label}] {len(candidates)} candidates in {time.time()-t0:.1f}s")

    log_prices = CointScanner._build_log_price_map(aligned, retained_symbols)
    tasks = []
    for p in candidates:
        lp_a = log_prices.get(p["symbol_a"])
        lp_b = log_prices.get(p["symbol_b"])
        if lp_a is None or lp_b is None:
            continue
        tasks.append((p["symbol_a"], p["symbol_b"], lp_a, lp_b, Config.ANALYSIS.EG_MAX_LAG))

    t0 = time.time()
    results = []
    with ProcessPoolExecutor(max_workers=12) as pool:
        for r in pool.map(_eg_worker, tasks, chunksize=50):
            results.append(r)
    print(f"[{tf_label}] EG on {len(tasks)} pairs in {time.time()-t0:.1f}s")

    ok = [r for r in results if r.get("ok")]
    pvals = np.array([r["pvalue"] for r in ok])
    return {
        "tf_label": tf_label,
        "n_tested": len(ok),
        "pvals": pvals,
        "n_candidates": len(candidates),
        "candidates": candidates,
    }


def main():
    print("Building universe (read-only, cache-only)...")
    universe = UniverseBuilder().build(connect=False, fetch=False)
    print(f"Universe: {len(universe.assets)} assets\n")

    results = {}
    for tf in ["5m", "15m", "30m"]:
        print(f"\n=== {tf} ===")
        results[tf] = investigate(tf, universe)

    print("\n\n=== SUMMARY: raw p-value distribution shape ===")
    for tf, r in results.items():
        pv = r["pvals"]
        n = pv.size
        print(f"\n[{tf}] n_tested={n}")
        for lo, hi in [(0, 0.001), (0.001, 0.01), (0.01, 0.05), (0.05, 0.10), (0.10, 0.25), (0.25, 1.0)]:
            frac = np.mean((pv >= lo) & (pv < hi))
            print(f"  p in [{lo:.3f}, {hi:.3f}): {frac:.4f}  (n={int(frac*n)})")
        print(f"  min p-value: {pv.min():.6f}")
        sorted_p = np.sort(pv)
        print(f"  10 smallest p-values: {sorted_p[:10]}")

    # Save raw arrays for further inspection if needed
    out = {tf: r["pvals"] for tf, r in results.items()}
    np.savez("debug/_5m_30m_pvals.npz", **out)
    print("\nSaved raw p-value arrays to debug/_5m_30m_pvals.npz")


if __name__ == "__main__":
    main()
