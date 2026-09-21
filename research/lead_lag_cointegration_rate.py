"""
CAMARF research/lead_lag_cointegration_rate.py -- exploratory diagnostic,
NOT part of the production pipeline.

Motivated by a 2026-09-14 discussion with Ross, extending lead_lag_scan.py's
per-pair "best lag" question into a population-level one: lead_lag_scan.py
EG-tests only TWO points per pair (lag 0 and the single lag with peak
correlation), then reports one best_lag label per pair. That can't answer
"as you move away from the contemporaneous alignment, what fraction of
pairs are still cointegrated at each specific lag distance k?" -- a
cointegration-RATE-by-lag curve, not a per-pair point estimate.

Method:
  1. Eligibility gate (cheap): for each confirmed pair (same population as
     lead_lag_scan.py, all timeframes), reuse lagged_corr_scan to get the
     overlap count n at every lag in [-x, x]. A pair enters the EG stage
     ONLY if n >= _MIN_EG_N at EVERY lag in that range, not just at lag 0.
     This is a deliberate fixed-denominator design choice: it keeps the
     per-lag rate curve y(k) comparable across lags (same pair population
     at every k), rather than letting thin-history pairs silently drop out
     at the extremes and make the curve's tail decay partly an artifact of
     sample attrition instead of real cointegration falloff. Trade-off:
     some pairs fine near lag 0 but too short-overlapping at +-x are
     discarded entirely rather than partially counted -- flagged here, not
     the only valid choice.
  2. EG-test EVERY lag in [-x, x] per eligible pair (not just 2 points),
     using the SAME production coint() call shape as lead_lag_scan.py and
     eg_permutation_check.py. Cost optimization: every call uses a FIXED
     maxlag (Config.ANALYSIS.EG_MAX_LAG, autolag=None) instead of the
     autolag="aic" search lead_lag_scan.py uses -- autolag runs its own
     internal search over candidate lag orders on EVERY call, which would
     be paid (2x+1) times per pair here instead of lead_lag_scan.py's 2.
     Fixing maxlag trades a small amount of per-call optimality for a real
     constant-factor speedup that offsets much of that (2x+1)-vs-2
     call-count increase. This is a disclosed simplification, same spirit
     as lead_lag_scan.py's own "max_lag not TF-scaled" disclosure.
  3. Aggregate: for each lag k, BH-FDR correct the cross-section of that
     lag's p-values (one per eligible pair) at `alpha`, using the SAME
     _benjamini_hochberg used throughout the production pipeline.
     y(k) = fraction of pairs FDR-significant at lag k. N(k) should be
     constant across k given step 1's fixed-denominator gate -- reported
     alongside y(k) as a sanity check that it is.

Parallelism: one task per PAIR (not per (pair, lag)) -- the worker sweeps
all 2x+1 lags for its pair internally. This avoids pickling/duplicating
each pair's log-price series 2x+1 times across separate tasks, which a
naive per-(pair,lag) task list would do. Uses the SAME ProcessPoolExecutor
+ _limit_worker_blas_threads initializer pattern as
wrds_deep_history_episodic_scan.py/analysis.py's own EG pools, after that
project's 2026-08-24 finding that per-worker BLAS threading stacked on top
of process-pool parallelism causes oversubscription, not real throughput.

Cost: roughly pairs_eligible x (2x+1) EG calls, each O(n) -- a real
increase over lead_lag_scan.py's 2 calls/pair, partially offset by the
fixed-maxlag optimization above. Does NOT decide whether to build a
lag-realignment step into the production pipeline; answers a narrower,
cheaper question about the SHAPE of cointegration strength by lag distance
among already-confirmed pairs.

Read-only. Loads cached price data via aligned_pair_loader.load_aligned_pair
-- never fetches.

Usage:
    python research/lead_lag_cointegration_rate.py
    python research/lead_lag_cointegration_rate.py --max-lag 10 --alpha 0.05
"""
import argparse
import logging
import os
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint

log = logging.getLogger("lead_lag_cointegration_rate")

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)
# research/aligned_pair_loader.py is only importable bare ("import
# aligned_pair_loader") when research/ itself is on sys.path -- true
# automatically when a script in research/ is run directly (Python adds the
# script's own dir), but NOT when this module is imported as
# research.lead_lag_cointegration_rate from elsewhere (e.g. this file's own
# debug/_verify_*.py). lead_lag_scan.py's own transitive `from
# aligned_pair_loader import ...` would otherwise fail in that case -- fixed
# locally here rather than touching the other ~60 research/ scripts sharing
# the same bare-import convention.
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "research"))

from aligned_pair_loader import load_aligned_pair
from analysis import Config, _benjamini_hochberg, _limit_worker_blas_threads
from data import _gap_aware_returns
from research.lead_lag_scan import (
    _TF_DIRS, _DIR_TO_LABEL, _MIN_EG_N, _gap_masked_log_price, lagged_corr_scan,
)


def _eg_pvalue_fixed_maxlag(a, b, maxlag):
    """Like lead_lag_scan._eg_pvalue but with a FIXED maxlag (autolag=None)
    instead of an autolag="aic" search -- see module docstring for why."""
    mask = np.isfinite(a) & np.isfinite(b)
    a_, b_ = a[mask], b[mask]
    if a_.size < _MIN_EG_N:
        return None, a_.size
    try:
        _, pval, _ = coint(a_, b_, trend="c", maxlag=maxlag, autolag=None)
        return float(pval), a_.size
    except Exception as e:
        log.debug("EG coint() failed on a %d-obs series: %s", a_.size, e)
        return None, a_.size


def build_eligible_pairs(x):
    """Returns a list of (tf_label, symbol_a, symbol_b, logp_a, logp_b) for
    every confirmed pair with >= _MIN_EG_N overlapping observations at
    EVERY lag in [-x, x] (the fixed-denominator eligibility gate -- see
    module docstring). logp_a/logp_b are gap-masked log-price pd.Series,
    same index space, ready to .shift() per lag."""
    eligible = []
    for tf_dir in _TF_DIRS:
        path = f"output/results/{tf_dir}/pairs.parquet"
        if not os.path.exists(path):
            continue
        tf_label = _DIR_TO_LABEL[tf_dir]
        df = pd.read_parquet(path)
        for _, row in df.iterrows():
            sym_a, sym_b = row["symbol_a"], row["symbol_b"]
            df_a, df_b = load_aligned_pair(sym_a, sym_b, tf_label)
            if df_a is None or df_b is None:
                print(f"SKIP {sym_a}/{sym_b}@{tf_label}: cache missing for one leg")
                continue

            ret_a = pd.Series(_gap_aware_returns(df_a), index=df_a.index)
            ret_b = pd.Series(_gap_aware_returns(df_b), index=df_b.index)
            scan = lagged_corr_scan(ret_a, ret_b, x)
            ns = [scan[lag][1] for lag in range(-x, x + 1)]
            min_n = min(ns)
            if min_n < _MIN_EG_N:
                print(f"SKIP {sym_a}/{sym_b}@{tf_label}: insufficient overlap "
                      f"(need >={_MIN_EG_N} at every lag in [-{x},{x}], min observed={min_n})")
                continue

            logp_a = pd.Series(_gap_masked_log_price(df_a), index=df_a.index)
            logp_b = pd.Series(_gap_masked_log_price(df_b), index=df_b.index)
            eligible.append((tf_label, sym_a, sym_b, logp_a, logp_b))
    return eligible


def _worker_pair_lag_sweep(task):
    """Worker run inside ProcessPoolExecutor. Must be top-level (picklable).
    Sweeps every lag in [-x, x] for ONE pair, returns a list of per-lag
    result dicts (tf, symbol_a, symbol_b, lag, eg_pvalue, n_obs)."""
    tf, sym_a, sym_b, logp_a, logp_b, x, maxlag = task
    rows = []
    for lag in range(-x, x + 1):
        shifted_b = logp_b.shift(-lag)
        joined = pd.concat([logp_a, shifted_b], axis=1, join="inner").dropna()
        n = len(joined)
        if n < _MIN_EG_N:
            rows.append({"tf": tf, "symbol_a": sym_a, "symbol_b": sym_b,
                         "lag": lag, "eg_pvalue": None, "n_obs": n})
            continue
        pval, n_used = _eg_pvalue_fixed_maxlag(
            joined.iloc[:, 0].values, joined.iloc[:, 1].values, maxlag
        )
        rows.append({"tf": tf, "symbol_a": sym_a, "symbol_b": sym_b,
                     "lag": lag, "eg_pvalue": pval, "n_obs": n_used})
    return rows


def cointegration_rate_by_lag(full_df, alpha):
    """full_df: one row per (pair, lag) with an `eg_pvalue` column (may be
    None/NaN). Returns a DataFrame indexed by lag with columns
    [lag, n_pairs_tested, n_significant, rate] -- rate is the BH-FDR
    corrected fraction of pairs cointegrated at that specific lag, FDR
    applied WITHIN each lag's own cross-section (not pooled across lags),
    matching the project's existing layered-FDR convention."""
    rows = []
    for lag, group in full_df.groupby("lag"):
        pvals = group["eg_pvalue"].dropna().values
        n_tested = len(pvals)
        if n_tested == 0:
            rows.append({"lag": lag, "n_pairs_tested": 0, "n_significant": 0, "rate": None})
            continue
        rejected, _ = _benjamini_hochberg(pvals, alpha)
        rows.append({
            "lag": lag, "n_pairs_tested": n_tested,
            "n_significant": int(rejected.sum()), "rate": float(rejected.mean()),
        })
    return pd.DataFrame(rows).sort_values("lag").reset_index(drop=True)


def main():
    p = argparse.ArgumentParser(
        description="Cointegration-rate-by-lag scan on confirmed pairs (2026-09-14)"
    )
    p.add_argument("--max-lag", type=int, default=Config.RESEARCH.LEAD_LAG_MAX_LAG,
                    help="Lag span x: sweep k in [-x, x] bars. Default sourced from "
                         "Config.RESEARCH.LEAD_LAG_MAX_LAG (same default lead_lag_scan.py uses).")
    p.add_argument("--alpha", type=float, default=Config.ANALYSIS.EG_SIGNIFICANCE,
                    help="BH-FDR alpha applied within each lag's cross-section.")
    p.add_argument("--workers", type=int, default=Config.RUNTIME.N_WORKERS)
    args = p.parse_args()
    x = args.max_lag
    maxlag = Config.ANALYSIS.EG_MAX_LAG

    eligible = build_eligible_pairs(x)
    if not eligible:
        print("No confirmed pairs eligible (insufficient overlap at every lag).")
        return
    print(f"\n{len(eligible)} pairs eligible (n>={_MIN_EG_N} at every lag in [-{x},{x}])")
    print(f"Running EG at every lag with fixed maxlag={maxlag} (autolag disabled) "
          f"-> {len(eligible) * (2 * x + 1)} total EG calls across {args.workers} workers...")

    tasks = [(tf, a, b, logp_a, logp_b, x, maxlag) for (tf, a, b, logp_a, logp_b) in eligible]

    all_rows = []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=_limit_worker_blas_threads) as pool:
        for rows in pool.map(_worker_pair_lag_sweep, tasks):
            all_rows.extend(rows)

    full_df = pd.DataFrame(all_rows)
    curve_df = cointegration_rate_by_lag(full_df, args.alpha)

    print("\nCointegration rate by lag (FDR-corrected within each lag's cross-section):")
    print(curve_df.to_string(index=False))

    n_distinct = curve_df["n_pairs_tested"].nunique()
    if n_distinct > 1:
        print(f"\nNOTE: n_pairs_tested varies across lags ({sorted(curve_df['n_pairs_tested'].unique())}) "
              f"-- expected to be constant given the fixed-denominator eligibility gate. "
              f"If this varies, investigate before trusting the rate curve's shape.")

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    full_path = os.path.join(out_dir, "lead_lag_cointegration_rate_full.parquet")
    curve_path = os.path.join(out_dir, "lead_lag_cointegration_rate_curve.parquet")
    full_df.to_parquet(full_path)
    curve_df.to_parquet(curve_path)
    print(f"\nFull per-(pair,lag) results -> {full_path}")
    print(f"Per-lag cointegration-rate curve -> {curve_path}")


if __name__ == "__main__":
    main()
