"""
Standalone verification harness for UniverseFilter correlation pre-filter
optimization. READ-ONLY against output/cache/*.parquet. Does not modify
analysis.py or data.py. Does not fetch any data.

Usage:
    python _perf_test/verify_universefilter.py [n_symbols] [tf]

Loads real cached parquet files, aligns them with the real DataAligner
(daily or intraday per tf), builds the real returns matrix via
UniverseFilter.build_returns_matrix, then runs OLD vs NEW implementations
of correlation_matrix / spearman_matrix / rolling_corr_avg_matrix and
candidate_pairs, comparing results for exact equivalence and timing both.
"""
import sys
import os
import time
import glob

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from data import DataAligner
import analysis
from analysis import UniverseFilter

N_SYMBOLS = int(sys.argv[1]) if len(sys.argv) > 1 else 200
TF = sys.argv[2] if len(sys.argv) > 2 else "1day"
OFFSET = int(sys.argv[3]) if len(sys.argv) > 3 else 0

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "cache")


def load_real_universe(n_symbols, tf, offset=0):
    pattern = os.path.join(CACHE_DIR, f"*_{tf}.parquet")
    files = sorted(glob.glob(pattern))
    if not files:
        raise SystemExit(f"No cache files found for pattern {pattern}")
    files = files[offset:offset + n_symbols]
    raw = {}
    for f in files:
        sym = os.path.basename(f).replace(f"_{tf}.parquet", "")
        df = pd.read_parquet(f)
        if df is None or df.empty or "close" not in df.columns:
            continue
        raw[sym] = df
    print(f"Loaded {len(raw)} raw symbols from cache ({tf})")
    return raw


def align(raw, tf):
    if tf == "1day":
        aligned = DataAligner.align_daily(raw)
    else:
        aligned = DataAligner.align_intraday(raw, tf)
    print(f"Aligned {len(aligned)} symbols")
    return aligned


# =============================================================================
# OLD (current, in analysis.py) reference implementations — copied verbatim
# for side-by-side comparison without touching the live module during the
# "before" pass. (After patching analysis.py, these serve as the frozen
# baseline to diff against.)
# =============================================================================

def old_pairwise_corr(returns: np.ndarray, min_overlap: int = 30) -> np.ndarray:
    n = returns.shape[0]
    corr = np.full((n, n), np.nan, dtype=float)
    means = np.nanmean(returns, axis=1, keepdims=True)
    demeaned = returns - means
    for i in range(n):
        corr[i, i] = 1.0
        ri = demeaned[i]
        valid_i = np.isfinite(ri)
        for j in range(i + 1, n):
            rj = demeaned[j]
            valid = valid_i & np.isfinite(rj)
            m = int(np.sum(valid))
            if m < min_overlap:
                continue
            a = ri[valid]
            a = a - a.mean()
            b = rj[valid]
            b = b - b.mean()
            den = np.sqrt(np.dot(a, a) * np.dot(b, b))
            if den > 0:
                c = float(np.dot(a, b) / den)
                corr[i, j] = c
                corr[j, i] = c
    return corr


def old_spearman_matrix(returns: np.ndarray) -> np.ndarray:
    n, T = returns.shape
    ranks = np.full_like(returns, np.nan, dtype=float)
    for i in range(n):
        mask = np.isfinite(returns[i])
        if np.sum(mask) < 30:
            continue
        r = np.empty(T, dtype=float)
        r[:] = np.nan
        vals = returns[i][mask]
        r_vals = np.argsort(np.argsort(vals)).astype(float)
        r[mask] = r_vals
        ranks[i] = r
    return old_pairwise_corr(ranks)


def old_rolling_corr_avg_matrix(returns: np.ndarray, window: int = 252, n_windows: int = 5) -> np.ndarray:
    n, T = returns.shape
    corr = np.full((n, n), np.nan, dtype=float)
    np.fill_diagonal(corr, 1.0)
    starts = list(range(0, T - window, window))[-n_windows:]
    if not starts:
        return corr
    sums = np.zeros((n, n), dtype=float)
    counts = np.zeros((n, n), dtype=int)
    means = np.nanmean(returns, axis=1, keepdims=True)
    dm = returns - means
    for s in starts:
        e = s + window
        w = dm[:, s:e]
        for i in range(n):
            ri = w[i]
            valid_i = np.isfinite(ri)
            for j in range(i + 1, n):
                rj = w[j]
                valid = valid_i & np.isfinite(rj)
                m = int(np.sum(valid))
                if m < 30:
                    continue
                a = ri[valid]
                a = a - a.mean()
                b = rj[valid]
                b = b - b.mean()
                den = np.sqrt(np.dot(a, a) * np.dot(b, b))
                if den > 0:
                    sums[i, j] += np.dot(a, b) / den
                    sums[j, i] += np.dot(a, b) / den
                    counts[i, j] += 1
                    counts[j, i] += 1
    mask = counts > 0
    corr[mask] = sums[mask] / counts[mask]
    return corr


def compare(name, old, new, atol=1e-9):
    if old.shape != new.shape:
        print(f"  [{name}] SHAPE MISMATCH: {old.shape} vs {new.shape}")
        return False
    nan_old = np.isnan(old)
    nan_new = np.isnan(new)
    if not np.array_equal(nan_old, nan_new):
        n_mismatch = np.sum(nan_old != nan_new)
        print(f"  [{name}] NaN PATTERN MISMATCH: {n_mismatch} cells differ in NaN-ness")
        return False
    both_finite = ~nan_old
    if not np.any(both_finite):
        print(f"  [{name}] all-NaN result (nothing to compare numerically)")
        return True
    diffs = np.abs(old[both_finite] - new[both_finite])
    maxdiff = float(np.max(diffs))
    ok = np.allclose(old[both_finite], new[both_finite], atol=atol, rtol=1e-9)
    print(f"  [{name}] max abs diff = {maxdiff:.3e}  -> {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    print(f"=== UniverseFilter verification: N_SYMBOLS={N_SYMBOLS} TF={TF} OFFSET={OFFSET} ===\n")
    raw = load_real_universe(N_SYMBOLS, TF, OFFSET)
    aligned = align(raw, TF)

    returns, symbols, _idx = UniverseFilter.build_returns_matrix(aligned, min_overlap=252)
    n, T = returns.shape
    print(f"Returns matrix: n={n} assets, T={T} bars")
    nan_frac = np.mean(~np.isfinite(returns))
    print(f"NaN fraction in returns matrix: {nan_frac:.4f}\n")

    all_pass = True

    # ---- correlation_matrix (Pearson) ----
    print("--- Pearson correlation_matrix ---")
    t0 = time.time()
    old_pearson = old_pairwise_corr(returns, min_overlap=30)
    t1 = time.time()
    new_pearson = UniverseFilter.correlation_matrix(returns)
    t2 = time.time()
    print(f"  old: {t1-t0:.3f}s   new: {t2-t1:.3f}s   speedup: {(t1-t0)/max(t2-t1,1e-9):.1f}x")
    all_pass &= compare("Pearson", old_pearson, new_pearson)

    # ---- spearman_matrix ----
    print("\n--- Spearman spearman_matrix ---")
    t0 = time.time()
    old_sp = old_spearman_matrix(returns)
    t1 = time.time()
    new_sp = UniverseFilter.spearman_matrix(returns)
    t2 = time.time()
    print(f"  old: {t1-t0:.3f}s   new: {t2-t1:.3f}s   speedup: {(t1-t0)/max(t2-t1,1e-9):.1f}x")
    all_pass &= compare("Spearman", old_sp, new_sp)

    # ---- rolling_corr_avg_matrix ----
    print("\n--- rolling_corr_avg_matrix ---")
    t0 = time.time()
    old_roll = old_rolling_corr_avg_matrix(returns)
    t1 = time.time()
    new_roll = UniverseFilter.rolling_corr_avg_matrix(returns)
    t2 = time.time()
    print(f"  old: {t1-t0:.3f}s   new: {t2-t1:.3f}s   speedup: {(t1-t0)/max(t2-t1,1e-9):.1f}x")
    all_pass &= compare("RollingAvg", old_roll, new_roll)

    # ---- candidate_pairs (full pipeline equivalence) ----
    print("\n--- candidate_pairs (end-to-end) ---")
    asset_class_map = {s: "equity" for s in symbols}
    threshold = 0.6
    old_pairs = UniverseFilter.candidate_pairs(
        old_pearson, symbols, threshold, asset_class_map,
        spearman=old_sp, rolling_avg=old_roll,
    )
    new_pairs = UniverseFilter.candidate_pairs(
        new_pearson, symbols, threshold, asset_class_map,
        spearman=new_sp, rolling_avg=new_roll,
    )
    old_set = {(p["symbol_a"], p["symbol_b"], p["confidence_tier"]) for p in old_pairs}
    new_set = {(p["symbol_a"], p["symbol_b"], p["confidence_tier"]) for p in new_pairs}
    print(f"  old pairs: {len(old_pairs)}   new pairs: {len(new_pairs)}")
    if old_set == new_set:
        print("  PAIR SETS IDENTICAL (symbol_a, symbol_b, tier)")
    else:
        print("  MISMATCH in pair sets!")
        print("  only in old:", list(old_set - new_set)[:10])
        print("  only in new:", list(new_set - old_set)[:10])
        all_pass = False

    print(f"\n=== OVERALL: {'ALL PASS' if all_pass else 'FAILURES DETECTED'} ===")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
