"""
research/wrds_universal_lead_lag_scan.py -- lead-lag correlation used as its
OWN pair-DISCOVERY methodology across the ENTIRE WRDS universe, added
2026-07-27 per Ross's direct correction to the narrower wrds_lead_lag_scan.py
build: "the lead lag should also be running on all assets, not just
confirmed assets. it's a new methodology to find pairs."

Genuinely different from wrds_lead_lag_scan.py (which only re-tests pairs
ALREADY confirmed by the episodic scan's own static/rolling correlation +
EG gates). This script does NOT require a pair to survive any Pearson
correlation prefilter at lag 0 first -- a pair with a real, exploitable
LAGGED relationship but weak/zero CONTEMPORANEOUS correlation would never
reach wrds_deep_history_episodic_scan.py's candidate list at all (that
script's own correlation_matrix/candidate_pairs and rolling_correlation_
candidate_pairs are both lag-0-only prefilters). This script is the
methodology that can actually find that pair.

THE COMBINATORIAL PROBLEM, stated honestly up front: the full WRDS universe
is ~5,846 symbols -> C(5846,2) ~= 17.1 MILLION unordered pairs -- 77x the
220,493-pair candidate set wrds_deep_history_episodic_scan.py's Tier 1/2/3
is already spending hours grinding through. Running the exact, per-pair
lagged_corr_scan() (a Python loop over ~21 lags, each doing a pandas concat+
dropna+corrcoef) on 17.1M pairs is not tractable on this hardware -- at even
a wildly optimistic 1ms/pair that is ~4.75 hours of PURE compute with zero
EG-confirm step included yet, and the real per-pair cost (with full
multi-decade history, not a toy series) is far more than 1ms.

FOUR-STAGE DESIGN (this is what makes the full universe tractable at all):

  STAGE 0 (this module's genuinely NEW piece) -- cheap, VECTORIZED, but
  APPROXIMATE full-universe screen. For each lag in [-max_lag, max_lag],
  computes the ENTIRE N x N lagged-correlation matrix in one BLAS matrix
  multiply: Z (globally-standardized, zero-filled returns) times its own
  lag-shifted copy, divided by a companion overlap-count matmul. This
  approximation is well understood and reasonably cheap (~1-30 min total,
  not hours/days) but has a REAL, documented bias: because each symbol's
  mean/std is computed from its OWN full marginal history (not from the
  overlapping subset shared with its counterpart), a pair whose two symbols
  have very DIFFERENT valid date ranges (e.g. a 1930s-listed CRSP name vs. a
  2015-listed one, overlap of only a few years out of decades) gets a
  correlation estimate that can be biased relative to the exact figure. This
  is a decades-old, standard large-scale correlation-screening approximation
  (not something invented ad hoc for this project) -- it is NEVER used as
  the final decision; it exists only to cut 17.1M pairs down to a tractable
  candidate set, gated on a deliberately GENEROUS, LOW absolute-correlation
  floor (not the real min-lift decision threshold) specifically to bound the
  false-negative risk the approximation's bias could otherwise introduce.

  STAGE 1 -- cheap, EXACT. Every Stage-0 survivor gets its lagged
  correlation recomputed with wrds_lead_lag_scan.py's own already-verified,
  exact, pairwise lagged_corr_scan()/best_lag() (pandas concat+dropna, no
  approximation). The REAL min-lift decision threshold is applied only
  here, on exact numbers.

  STAGE 2 -- expensive, exact. Stage-1 survivors get EG-confirmed at their
  best lag (log-price series, symbol B shifted by best_lag bars), reusing
  analysis.py's _eg_worker via the SAME bounded-batch, checkpointed
  ProcessPoolExecutor pattern already built and proven in
  wrds_deep_history_episodic_scan.py (run_full_sample_eg_pool) -- not
  reimplemented, imported directly.

  STAGE 3 -- joint BH-FDR correction across the WHOLE Stage-2-tested family
  (reusing analysis.py's _benjamini_hochberg), exactly like every other
  multi-test family in this project. A pair is "lead-lag confirmed" only if
  it clears FDR at its best lag.

Honest scope note: Stage 0's absolute-correlation floor (LEAD_LAG_STAGE0_FLOOR
below) is a SAFETY MARGIN below the real decision threshold, not a second
independent claim -- widen it (lower it further) rather than narrow it if
Stage-0-vs-exact drift is ever found to be larger than expected in
debug/_verify_wrds_universal_lead_lag_scan.py's adversarial partial-overlap
check.

See the "EPISODIC MODE" section further down (added 2026-07-27, same day,
per Ross's direct follow-up: "the lead lag should also detect for
episodic") for the --episodic variant: the same 4-stage design applied
independently within each rolling window (EPISODIC_WINDOW_BARS/
EPISODIC_STEP_BARS, same convention as wrds_deep_history_episodic_scan.py's
Tier 2/3) instead of once over the whole sample, so a lead-lag relationship
confined to a single historical regime isn't diluted to near-zero by
decades of unrelated data the way a whole-sample scan would dilute it.

Usage:
    python research/wrds_universal_lead_lag_scan.py
    python research/wrds_universal_lead_lag_scan.py --count-only   # Stage 0 only, report survivor count, no EG spend
    python research/wrds_universal_lead_lag_scan.py --episodic --count-only   # rolling-window variant, Stage 0 only
"""
import argparse
import logging
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from analysis import _eg_worker, _benjamini_hochberg
from research.wrds_deep_history_episodic_scan import (
    load_wrds_universe, build_log_prices_and_returns,
    _build_symbol_array_cache, _save_checkpoint, _load_checkpoint, clear_checkpoint,
    episodic_bhfdr_confirm, EPISODIC_WINDOW_BARS, EPISODIC_STEP_BARS,
)
from research.wrds_lead_lag_scan import lagged_corr_scan, best_lag, _MIN_CORR_N, _MIN_EG_N

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_ROOT, "output", "research")

TF_LABEL = "1D_wrds_universal_leadlag"
LEAD_LAG_STAGE0_FLOOR = 0.15  # deliberately generous/low -- see module docstring

log = logging.getLogger("wrds_universal_lead_lag_scan")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(os.path.join(_ROOT, "latest_run_wrds_universal_lead_lag_scan.log"),
                              mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def compute_bulk_lagged_corr(returns_df: pd.DataFrame, max_lag: int, min_overlap: int = _MIN_CORR_N):
    """
    STAGE 0. Vectorized, APPROXIMATE full N x N lagged-correlation screen --
    see module docstring for the exact approximation and why it's safe to
    use ONLY as a cheap pre-screen, never as a final number.

    For each lag k in [-max_lag, max_lag]:
      - shift the (zero-filled, globally-standardized) return matrix by k
      - corr_matrix_k[i,j] = (Z.T @ Z_shifted_k)[i,j] / overlap_k[i,j]
      - overlap_k[i,j] = (mask.T @ mask_shifted_k)[i,j]  (count of days both
        symbols have real data at this lag alignment)

    Tracks, per pair, the lag with the largest |corr| (subject to
    overlap_k[i,j] >= min_overlap -- a lag alignment with too little shared
    history is never allowed to "win" regardless of its apparent correlation,
    same discipline as the exact scan's own _MIN_CORR_N gate) and the lag-0
    correlation/overlap for the same pair.

    Returns a DataFrame, one row per (symbol_a, symbol_b) with i<j, columns:
    approx_best_lag, approx_best_corr, approx_overlap_at_best,
    approx_corr_lag0, approx_overlap_lag0.
    """
    symbols = list(returns_df.columns)
    n_sym = len(symbols)
    R = returns_df.to_numpy(dtype=np.float64)
    valid = np.isfinite(R)
    R_filled = np.where(valid, R, 0.0)
    counts = valid.sum(axis=0).astype(np.float64)
    counts_safe = np.where(counts > 0, counts, np.nan)
    means = R_filled.sum(axis=0) / counts_safe
    demeaned = np.where(valid, R - means, 0.0)
    sumsq = (demeaned ** 2).sum(axis=0)
    stds = np.sqrt(sumsq / counts_safe)
    stds_safe = np.where((stds > 0) & np.isfinite(stds), stds, np.nan)
    Z = np.where(valid, demeaned / stds_safe, 0.0)
    Z = np.nan_to_num(Z, nan=0.0)  # any symbol with all-NaN/zero-variance history contributes 0 everywhere
    mask_f = valid.astype(np.float64)

    best_abscorr = np.full((n_sym, n_sym), -1.0, dtype=np.float64)
    best_corr = np.zeros((n_sym, n_sym), dtype=np.float64)
    best_lag_mat = np.zeros((n_sym, n_sym), dtype=np.int16)
    best_overlap = np.zeros((n_sym, n_sym), dtype=np.int32)
    corr_lag0 = None
    overlap_lag0 = None

    t0 = time.time()
    for lag in range(-max_lag, max_lag + 1):
        Z_shift = np.roll(Z, -lag, axis=0)
        mask_shift = np.roll(mask_f, -lag, axis=0)
        if lag > 0:
            Z_shift[-lag:, :] = 0.0
            mask_shift[-lag:, :] = 0.0
        elif lag < 0:
            Z_shift[: -lag, :] = 0.0
            mask_shift[: -lag, :] = 0.0

        overlap = mask_f.T @ mask_shift  # n_sym x n_sym
        dot = Z.T @ Z_shift  # n_sym x n_sym
        with np.errstate(invalid="ignore", divide="ignore"):
            corr = dot / overlap
        corr = np.where(overlap >= min_overlap, corr, np.nan)

        if lag == 0:
            corr_lag0 = corr.copy()
            overlap_lag0 = overlap.copy()

        abscorr = np.abs(corr)
        better = np.nan_to_num(abscorr, nan=-1.0) > best_abscorr
        best_abscorr = np.where(better, np.nan_to_num(abscorr, nan=-1.0), best_abscorr)
        best_corr = np.where(better, np.nan_to_num(corr, nan=0.0), best_corr)
        best_lag_mat = np.where(better, lag, best_lag_mat)
        best_overlap = np.where(better, overlap.astype(np.int32), best_overlap)
        log.debug(f"  Stage 0 lag={lag} done ({time.time()-t0:.1f}s elapsed)")

    log.info(f"Stage 0 (vectorized approximate screen): all {2*max_lag+1} lags computed "
             f"in {(time.time()-t0)/60:.1f} min")

    iu = np.triu_indices(n_sym, k=1)
    df = pd.DataFrame({
        "symbol_a": [symbols[i] for i in iu[0]],
        "symbol_b": [symbols[j] for j in iu[1]],
        "approx_best_lag": best_lag_mat[iu],
        "approx_best_corr": best_corr[iu],
        "approx_overlap_at_best": best_overlap[iu],
        "approx_corr_lag0": corr_lag0[iu],
        "approx_overlap_lag0": overlap_lag0[iu],
    })
    return df


def stage0_survivors(bulk_df: pd.DataFrame, floor: float = LEAD_LAG_STAGE0_FLOOR):
    """Applies Stage 0's deliberately generous, low absolute-correlation
    floor -- NOT the real min-lift decision (that's Stage 1's job, on exact
    numbers). Also requires a non-zero best lag (lag-0-only pairs are
    exactly what the existing correlation-prefiltered episodic scan already
    covers -- this methodology exists to find NONZERO-lag relationships)."""
    mask = (bulk_df["approx_best_lag"] != 0) & (bulk_df["approx_best_corr"].abs() >= floor)
    return bulk_df[mask].copy()


def stage1_exact_recheck(survivors: pd.DataFrame, max_lag: int, min_lift: float, ret_by_symbol: dict):
    """STAGE 1: exact, pairwise recheck of every Stage 0 survivor using
    wrds_lead_lag_scan.py's own verified lagged_corr_scan/best_lag (pandas
    concat+dropna -- no approximation). Applies the REAL min_lift decision
    threshold here, on exact numbers only. Returns a DataFrame of pairs that
    pass, with exact_best_lag/exact_corr_at_best_lag/exact_corr_at_lag0/
    exact_lift/exact_n_at_best_lag columns."""
    rows = []
    for _, r in survivors.iterrows():
        sym_a, sym_b = r["symbol_a"], r["symbol_b"]
        ret_a, ret_b = ret_by_symbol.get(sym_a), ret_by_symbol.get(sym_b)
        if ret_a is None or ret_b is None:
            continue
        scan = lagged_corr_scan(ret_a, ret_b, max_lag)
        k_star, c_star, n_star = best_lag(scan)
        c0, n0 = scan.get(0, (None, 0))
        if k_star is None or c0 is None or k_star == 0:
            continue
        lift = abs(c_star) - abs(c0)
        if lift < min_lift:
            continue
        rows.append({
            "symbol_a": sym_a, "symbol_b": sym_b,
            "exact_best_lag": k_star, "exact_corr_at_best_lag": c_star, "exact_n_at_best_lag": n_star,
            "exact_corr_at_lag0": c0, "exact_n_at_lag0": n0, "exact_lift": lift,
        })
    return pd.DataFrame(rows)


def stage2_eg_confirm(stage1_df: pd.DataFrame, log_price_df: pd.DataFrame, max_lag: int,
                       workers=12, pair_batch_size=2000, checkpoint_id="universal_leadlag_stage2"):
    """STAGE 2: EG-confirm each Stage-1 survivor at its OWN best lag --
    symbol B's log-price series shifted by exact_best_lag bars before the
    EG test, exactly mirroring wrds_lead_lag_scan.py's scan_pair() EG-confirm
    logic, but batched across the whole survivor set at once (reusing the
    SAME bounded-memory, checkpointed ProcessPoolExecutor pattern already
    proven in wrds_deep_history_episodic_scan.py's run_full_sample_eg_pool)
    since the survivor count here can be far larger than a single confirmed-
    pair list."""
    if stage1_df.empty:
        return stage1_df.assign(eg_pvalue=[])

    all_symbols = set(stage1_df["symbol_a"]) | set(stage1_df["symbol_b"])
    array_cache = _build_symbol_array_cache(log_price_df, all_symbols)

    pairs = stage1_df.to_dict("records")
    results = [None] * len(pairs)
    start_idx = 0
    if checkpoint_id:
        loaded, n_done = _load_checkpoint(checkpoint_id)
        if loaded is not None:
            for i, rec in enumerate(loaded):
                if i < len(results):
                    results[i] = rec
            start_idx = n_done
            log.info(f"Resuming Stage 2 EG confirm from checkpoint: {n_done}/{len(pairs)} pairs already done")

    from concurrent.futures import ProcessPoolExecutor
    n_batches = (len(pairs) + pair_batch_size - 1) // pair_batch_size
    log.info(f"Stage 2: EG-confirming {len(pairs)} exact-lift-surviving pairs in {n_batches} "
             f"batches of <={pair_batch_size} (workers={workers})...")
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for batch_num, i in enumerate(range(start_idx, len(pairs), pair_batch_size)):
            batch = pairs[i:i + pair_batch_size]
            tasks = []
            for p in batch:
                lp_a = array_cache[p["symbol_a"]]
                lp_b = np.roll(array_cache[p["symbol_b"]], -p["exact_best_lag"])
                tasks.append((p["symbol_a"], p["symbol_b"], lp_a, lp_b, max_lag, TF_LABEL))
            batch_results = list(pool.map(_eg_worker, tasks, chunksize=50))
            for j, (p, r) in enumerate(zip(batch, batch_results)):
                merged = dict(p)
                merged["eg_pvalue"] = r.get("pvalue") if r.get("ok") else None
                results[i + j] = merged
            n_done_now = i + len(batch)
            if checkpoint_id:
                _save_checkpoint(checkpoint_id, [r for r in results if r is not None], n_done_now)
            if batch_num % 5 == 0:
                log.info(f"  Stage 2 batch (pairs {i}-{n_done_now}/{len(pairs)}) done "
                         f"({(time.time()-t0)/60:.1f} min elapsed)")
    if checkpoint_id:
        clear_checkpoint(checkpoint_id)
    log.info(f"Stage 2 complete in {(time.time()-t0)/60:.1f} min")
    return pd.DataFrame([r for r in results if r is not None])


def stage3_bhfdr(stage2_df: pd.DataFrame, alpha: float):
    """STAGE 3: joint BH-FDR correction across the whole Stage-2-tested
    family (analysis.py's _benjamini_hochberg, unchanged) -- a pair is
    "lead-lag confirmed" only if it clears FDR here."""
    valid = stage2_df[stage2_df["eg_pvalue"].notna()].copy()
    if valid.empty:
        return valid.assign(fdr_adjusted_pvalue=[], fdr_confirmed=[])
    rejected, adjusted = _benjamini_hochberg(valid["eg_pvalue"].to_numpy(), alpha)
    valid["fdr_adjusted_pvalue"] = adjusted
    valid["fdr_confirmed"] = rejected
    return valid


# =============================================================================
# EPISODIC MODE -- added 2026-07-27, same day, per Ross's direct follow-up:
# "the lead lag should also detect for episodic." The whole-sample scan
# above (Stages 0-3) finds a pair's SINGLE best lag over its ENTIRE shared
# history -- exactly the same structural blind spot Ross already identified
# for episodic COINTEGRATION (wrds_deep_history_episodic_scan.py's Tier 2/3):
# a pair whose lagged relationship exists only in ONE historical regime
# (e.g. a multi-year stretch, not the full multi-decade sample) will have
# that regime's signal diluted into near-zero by a whole-sample average --
# a whole-sample lagged-corr scan is structurally unable to find it. This
# section re-runs the SAME 3-stage screen-then-confirm design (approximate
# vectorized screen -> exact recheck -> EG confirm), independently WITHIN
# each rolling window, reusing EPISODIC_WINDOW_BARS/EPISODIC_STEP_BARS
# (imported from wrds_deep_history_episodic_scan.py, not redefined, so the
# window/step convention stays identical across every episodic script in
# this project) and reusing episodic_bhfdr_confirm for the SAME joint,
# per-pair-across-windows FDR aggregation Tier 2/3 already use -- a pair is
# "episodically lead-lag confirmed" if >=1 of its windows survives FDR,
# exactly mirroring Tier 2/3's own definition of "episodically confirmed."
#
# Compute cost, stated honestly: this multiplies Stage 0's already-large
# whole-universe cost by roughly the number of rolling windows (~8-10 for
# century-scale WRDS history) -- see main()'s --episodic branch, which is
# deliberately NOT run in the same invocation as the whole-sample mode.
# =============================================================================

def compute_bulk_lagged_corr_episodic(returns_df: pd.DataFrame, max_lag: int,
                                       window: int = EPISODIC_WINDOW_BARS,
                                       step: int = EPISODIC_STEP_BARS,
                                       min_overlap: int = _MIN_CORR_N):
    """EPISODIC STAGE 0: re-runs compute_bulk_lagged_corr's exact same
    vectorized matmul screen (reused unchanged, not reimplemented) once per
    rolling window instead of once over the whole sample. Returns a LONG
    DataFrame -- one row per (symbol_a, symbol_b, window_start_date) --
    tagging each window's results with that window's actual start date
    (not a raw integer position), so downstream stages can slice both
    returns_df and log_price_df by date and avoid any position-offset risk
    between the two (log_price_df has one more row than returns_df, since
    returns = log_price_df.diff().iloc[1:])."""
    n = len(returns_df)
    frames = []
    n_windows = 0
    t0 = time.time()
    for start in range(0, n - window + 1, step):
        seg = returns_df.iloc[start:start + window]
        window_start_date = returns_df.index[start]
        bulk = compute_bulk_lagged_corr(seg, max_lag, min_overlap=min_overlap)
        bulk["window_start_date"] = window_start_date
        frames.append(bulk)
        n_windows += 1
        log.info(f"  Episodic Stage 0: window {n_windows} (start={window_start_date.date()}) done "
                 f"({(time.time()-t0)/60:.1f} min elapsed)")
    log.info(f"Episodic Stage 0: {n_windows} rolling windows scanned "
             f"({(time.time()-t0)/60:.1f} min total)")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def stage0_survivors_episodic(bulk_episodic_df: pd.DataFrame, floor: float = LEAD_LAG_STAGE0_FLOOR):
    """Same filter as stage0_survivors (non-zero lag, |corr| >= floor),
    applied per (pair, window) row -- preserves window_start_date so Stage 1
    can recheck EXACTLY that window, not the whole series."""
    if bulk_episodic_df.empty:
        return bulk_episodic_df
    mask = (bulk_episodic_df["approx_best_lag"] != 0) & (bulk_episodic_df["approx_best_corr"].abs() >= floor)
    return bulk_episodic_df[mask].copy()


def stage1_exact_recheck_episodic(survivors: pd.DataFrame, max_lag: int, min_lift: float,
                                   returns_df: pd.DataFrame, window: int = EPISODIC_WINDOW_BARS):
    """STAGE 1 (episodic): exact pairwise recheck, but scoped to ONLY the
    (pair, window)'s own date range -- slices returns_df to
    [window_start_date, window_start_date + window bars) and runs the SAME
    verified lagged_corr_scan()/best_lag() used by the whole-sample Stage 1.
    Applies the real min_lift threshold WITHIN that window, not over the
    whole history."""
    rows = []
    for _, r in survivors.iterrows():
        sym_a, sym_b, wstart = r["symbol_a"], r["symbol_b"], r["window_start_date"]
        pos = returns_df.index.get_loc(wstart)
        seg = returns_df.iloc[pos:pos + window]
        ret_a, ret_b = seg[sym_a], seg[sym_b]
        scan = lagged_corr_scan(ret_a, ret_b, max_lag)
        k_star, c_star, n_star = best_lag(scan)
        c0, n0 = scan.get(0, (None, 0))
        if k_star is None or c0 is None or k_star == 0:
            continue
        lift = abs(c_star) - abs(c0)
        if lift < min_lift:
            continue
        rows.append({
            "symbol_a": sym_a, "symbol_b": sym_b, "window_start_date": wstart,
            "exact_best_lag": k_star, "exact_corr_at_best_lag": c_star, "exact_n_at_best_lag": n_star,
            "exact_corr_at_lag0": c0, "exact_n_at_lag0": n0, "exact_lift": lift,
        })
    return pd.DataFrame(rows)


def stage2_eg_confirm_episodic(stage1_df: pd.DataFrame, log_price_df: pd.DataFrame,
                                returns_df: pd.DataFrame, max_lag: int,
                                window: int = EPISODIC_WINDOW_BARS, workers=12, task_batch_size=4000,
                                checkpoint_id="universal_leadlag_stage2_episodic"):
    """STAGE 2 (episodic): EG-confirms each (pair, window) row using ONLY
    that window's log-price slice (dates looked up via returns_df's index,
    then applied to log_price_df via .loc -- NOT a raw position offset,
    since log_price_df has one more row than returns_df), with symbol B
    shifted by that window's OWN exact_best_lag. Same bounded-batch,
    checkpointed ProcessPoolExecutor pattern as the whole-sample Stage 2.
    Output's p-value column is named 'pvalue' (not 'eg_pvalue') so it can
    feed directly into episodic_bhfdr_confirm (imported unchanged from
    wrds_deep_history_episodic_scan.py) without any renaming."""
    if stage1_df.empty:
        return stage1_df.assign(pvalue=[])

    all_symbols = set(stage1_df["symbol_a"]) | set(stage1_df["symbol_b"])
    array_cache = None  # not reused here -- each task needs a WINDOW slice, not the full series

    tasks_meta = stage1_df.to_dict("records")
    results = [None] * len(tasks_meta)
    start_idx = 0
    if checkpoint_id:
        loaded, n_done = _load_checkpoint(checkpoint_id)
        if loaded is not None:
            for i, rec in enumerate(loaded):
                if i < len(results):
                    results[i] = rec
            start_idx = n_done
            log.info(f"Resuming episodic Stage 2 from checkpoint: {n_done}/{len(tasks_meta)} rows already done")

    from concurrent.futures import ProcessPoolExecutor
    n_batches = (len(tasks_meta) + task_batch_size - 1) // task_batch_size
    log.info(f"Episodic Stage 2: EG-confirming {len(tasks_meta)} (pair,window) rows in {n_batches} "
             f"batches of <={task_batch_size} (workers={workers})...")
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for batch_num, i in enumerate(range(start_idx, len(tasks_meta), task_batch_size)):
            batch = tasks_meta[i:i + task_batch_size]
            tasks = []
            for p in batch:
                pos = returns_df.index.get_loc(p["window_start_date"])
                window_dates = returns_df.index[pos:pos + window]
                lp_a = log_price_df.loc[window_dates, p["symbol_a"]].to_numpy()
                lp_b = log_price_df.loc[window_dates, p["symbol_b"]].to_numpy()
                lp_b_shift = np.roll(lp_b, -p["exact_best_lag"])
                tasks.append((p["symbol_a"], p["symbol_b"], lp_a, lp_b_shift, max_lag, TF_LABEL))
            batch_results = list(pool.map(_eg_worker, tasks, chunksize=50))
            for j, (p, r) in enumerate(zip(batch, batch_results)):
                merged = dict(p)
                merged["pvalue"] = r.get("pvalue") if r.get("ok") else None
                results[i + j] = merged
            n_done_now = i + len(batch)
            if checkpoint_id:
                _save_checkpoint(checkpoint_id, [x for x in results if x is not None], n_done_now)
            if batch_num % 5 == 0:
                log.info(f"  Episodic Stage 2 batch (rows {i}-{n_done_now}/{len(tasks_meta)}) done "
                         f"({(time.time()-t0)/60:.1f} min elapsed)")
    if checkpoint_id:
        clear_checkpoint(checkpoint_id)
    log.info(f"Episodic Stage 2 complete in {(time.time()-t0)/60:.1f} min")
    return pd.DataFrame([r for r in results if r is not None])


def _run_episodic(returns: pd.DataFrame, log_price_df: pd.DataFrame, args):
    """Wires the episodic Stages 0b/1/2/3 together, mirroring main()'s
    whole-sample flow exactly (same count-only short-circuit, same
    save-every-stage discipline, same final FDR-confirmed summary log) but
    over (pair, window) rows instead of (pair) rows, and using
    episodic_bhfdr_confirm's per-pair-across-windows aggregation for the
    final confirmed set."""
    bulk_df = compute_bulk_lagged_corr_episodic(returns, args.max_lag)
    survivors = stage0_survivors_episodic(bulk_df, args.stage0_floor)
    log.info(f"Episodic Stage 0: {len(survivors):,}/{len(bulk_df):,} (pair,window) rows survive the "
             f"approximate |corr| >= {args.stage0_floor} floor at a non-zero lag")

    os.makedirs(_OUT_DIR, exist_ok=True)
    bulk_df.to_parquet(os.path.join(_OUT_DIR, "wrds_universal_lead_lag_episodic_stage0_full.parquet"),
                        index=False)

    if args.count_only:
        log.info("--count-only set: stopping after episodic Stage 0. No EG-confirm compute spent.")
        return
    if survivors.empty:
        log.warning("No episodic Stage 0 survivors -- nothing to recheck.")
        return

    stage1_df = stage1_exact_recheck_episodic(survivors, args.max_lag, args.min_lift, returns)
    log.info(f"Episodic Stage 1 (exact recheck): {len(stage1_df):,}/{len(survivors):,} (pair,window) "
             f"rows confirm a real exact lift >= {args.min_lift} within that window")
    stage1_df.to_parquet(os.path.join(_OUT_DIR, "wrds_universal_lead_lag_episodic_stage1_exact.parquet"),
                          index=False)

    if stage1_df.empty:
        log.warning("No episodic Stage 1 survivors -- nothing to EG-confirm.")
        return

    stage2_df = stage2_eg_confirm_episodic(stage1_df, log_price_df, returns, Config.ANALYSIS.EG_MAX_LAG)
    stage2_df.to_parquet(os.path.join(_OUT_DIR, "wrds_universal_lead_lag_episodic_stage2_eg.parquet"),
                          index=False)

    flat_rows = stage2_df[stage2_df["pvalue"].notna()].to_dict("records")
    confirmed = episodic_bhfdr_confirm(flat_rows, Config.STATS.FDR_ALPHA)
    log.info(f"=== Episodic Stage 3 (joint BH-FDR across {len(flat_rows)} (pair,window) tests, "
             f"alpha={Config.STATS.FDR_ALPHA}): {len(confirmed)} pairs episodically lead-lag "
             f"confirmed (>=1 FDR-rejected window) -- these are relationships a WHOLE-SAMPLE lead-lag "
             f"scan would structurally miss ===")
    for r in sorted(confirmed, key=lambda x: x["min_adjusted_pvalue"])[:30]:
        log.info(f"  [EPISODIC CONFIRMED] {r['symbol_a']}/{r['symbol_b']}: "
                 f"{r['n_windows_fdr_rejected']}/{r['n_windows_tested']} windows FDR-rejected, "
                 f"min_adj_p={r['min_adjusted_pvalue']:.3e}")
    pd.DataFrame(confirmed).to_parquet(
        os.path.join(_OUT_DIR, "wrds_universal_lead_lag_episodic_confirmed.parquet"), index=False)
    log.info("Saved -> output/research/wrds_universal_lead_lag_episodic_{stage0_full,stage1_exact,"
             "stage2_eg,confirmed}.parquet")


def main():
    p = argparse.ArgumentParser(description="Full-universe lead-lag pair-discovery scan (2026-07-27)")
    p.add_argument("--max-lag", type=int, default=Config.RESEARCH.LEAD_LAG_MAX_LAG)
    p.add_argument("--min-lift", type=float, default=0.05)
    p.add_argument("--stage0-floor", type=float, default=LEAD_LAG_STAGE0_FLOOR)
    p.add_argument("--count-only", action="store_true",
                    help="Run Stage 0 only, report survivor count, do not spend Stage 1/2/3 compute")
    p.add_argument("--episodic", action="store_true",
                    help="Run the EPISODIC variant (rolling-window lead-lag discovery, finds "
                         "regime-confined relationships a whole-sample scan would dilute to zero) "
                         "instead of the whole-sample scan. Substantially more expensive (~N-window "
                         "multiple of whole-sample Stage 0's cost) -- run separately, not together.")
    args = p.parse_args()
    _setup_logging()

    mode = "EPISODIC (rolling-window)" if args.episodic else "whole-sample"
    log.info(f"=== wrds_universal_lead_lag_scan.py [{mode}]: lead-lag correlation as a "
             f"PAIR-DISCOVERY methodology across the FULL WRDS universe (not just already-confirmed "
             f"pairs) ===")
    close_by_symbol, _ = load_wrds_universe()
    if len(close_by_symbol) < 10:
        log.warning("Fewer than 10 symbols loaded -- aborting.")
        return
    log_price_df, returns = build_log_prices_and_returns(close_by_symbol)
    symbols = list(returns.columns)
    n_pairs_total = len(symbols) * (len(symbols) - 1) // 2
    log.info(f"{len(symbols)} symbols, {n_pairs_total:,} unordered pairs in the full combinatorial universe")

    if args.episodic:
        _run_episodic(returns, log_price_df, args)
        return

    bulk_df = compute_bulk_lagged_corr(returns, args.max_lag)
    survivors = stage0_survivors(bulk_df, args.stage0_floor)
    log.info(f"Stage 0: {len(survivors):,}/{n_pairs_total:,} pairs survive the approximate "
             f"|corr| >= {args.stage0_floor} floor at a non-zero lag")

    os.makedirs(_OUT_DIR, exist_ok=True)
    bulk_df.to_parquet(os.path.join(_OUT_DIR, "wrds_universal_lead_lag_stage0_full.parquet"), index=False)

    if args.count_only:
        log.info("--count-only set: stopping after Stage 0. No EG-confirm compute spent.")
        return
    if survivors.empty:
        log.warning("No Stage 0 survivors -- nothing to recheck.")
        return

    ret_by_symbol = {s: returns[s] for s in symbols}
    stage1_df = stage1_exact_recheck(survivors, args.max_lag, args.min_lift, ret_by_symbol)
    log.info(f"Stage 1 (exact recheck): {len(stage1_df):,}/{len(survivors):,} Stage-0 survivors "
             f"confirm a real exact lift >= {args.min_lift} at a non-zero lag")
    stage1_df.to_parquet(os.path.join(_OUT_DIR, "wrds_universal_lead_lag_stage1_exact.parquet"), index=False)

    if stage1_df.empty:
        log.warning("No Stage 1 survivors -- nothing to EG-confirm.")
        return

    stage2_df = stage2_eg_confirm(stage1_df, log_price_df, Config.ANALYSIS.EG_MAX_LAG)
    stage2_df.to_parquet(os.path.join(_OUT_DIR, "wrds_universal_lead_lag_stage2_eg.parquet"), index=False)

    stage3_df = stage3_bhfdr(stage2_df, Config.STATS.FDR_ALPHA)
    n_confirmed = int(stage3_df["fdr_confirmed"].sum()) if not stage3_df.empty else 0
    log.info(f"=== Stage 3 (joint BH-FDR, alpha={Config.STATS.FDR_ALPHA}, m={len(stage3_df)}): "
             f"{n_confirmed} lead-lag-confirmed pairs, discovered PURELY via lagged correlation, "
             f"independent of any lag-0 correlation prefilter ===")
    confirmed = stage3_df[stage3_df["fdr_confirmed"]] if not stage3_df.empty else stage3_df
    for _, r in confirmed.sort_values("fdr_adjusted_pvalue").head(30).iterrows():
        log.info(f"  CONFIRMED: {r['symbol_a']}/{r['symbol_b']}: lag={r['exact_best_lag']} "
                 f"corr={r['exact_corr_at_best_lag']:.3f} lift={r['exact_lift']:.3f} "
                 f"eg_p={r['eg_pvalue']:.3e} adj={r['fdr_adjusted_pvalue']:.3e}")
    stage3_df.to_parquet(os.path.join(_OUT_DIR, "wrds_universal_lead_lag_confirmed.parquet"), index=False)
    log.info("Saved -> output/research/wrds_universal_lead_lag_{stage0_full,stage1_exact,stage2_eg,confirmed}.parquet")


if __name__ == "__main__":
    main()
