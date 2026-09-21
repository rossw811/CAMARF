# =============================================================================
# CAMARF -- multivariate_pit_predictors.py
#
# Backlog item #6 (docs/HANDOFF.md, 2026-09-12/13 overnight brainstorm),
# approved by Ross 2026-09-13 ("0.1 c" -- pivot straight to the multivariate
# study regardless of what the clean overlap re-run shows).
#
# MOTIVATION: three single-variable PIT-safe pilots this session (overlap
# length, MIN_PEARSON_CORR, MIN_COINT_FRAC) each showed noisy, non-monotonic
# relationships to OOS success in isolation -- none a clean threshold effect.
# This script tests them TOGETHER, plus a fourth covariate none of the prior
# pilots captured: hedge-ratio STABILITY over the training window (a pair
# whose hedge ratio drifts wildly during training seems like a more direct
# candidate predictor of OOS failure than any static screening threshold,
# and this project already computes hedge_ratio_ols_t per-bar -- no new data
# pipeline needed, just a new aggregate feature from an existing series).
#
# METHOD: reuses the CHEAPER, already-proven GATED screen (research.pit_wfa_
# wrds_daily.screen_universe_at_cutoff, standard production MIN_PEARSON_CORR/
# MIN_COINT_FRAC thresholds) across the same overlap-length grid research/
# overlap_threshold_pit_test.py already validated (~10-50 min per L, not the
# ~190 min/L the ungated 0.20-threshold screen cost) -- deliberately NOT the
# ungated screen, which would need 4x that cost to sweep the same grid. This
# means the question answered is narrower than the ungated pilots: AMONG
# pairs that already clear the CURRENT production gates, does overlap length
# / the pair's actual correlation value / its actual coint_fraction value /
# its hedge-ratio stability predict OOS success? Not "should the gates be
# different at all" (the ungated pilots already speak to that, separately).
#
# For each confirmed pair, _build_pair_result is called a SECOND time (cheap,
# single-pair cost) purely to recover the per_bar dict (screen_universe_at_
# cutoff discards it, keeping only the PairResult) -- needed for the
# hedge_ratio_ols_t series the stability metric is computed from.
#
# MODELING: pools ALL fold x L cells into one dataset and fits a single
# statsmodels Logit (held_up ~ n_overlap + pearson_corr + coint_fraction_
# rolling + hedge_ratio_cv, all z-scored). HONEST LIMITATION, disclosed not
# hidden: with only 1 fold, the SAME pair can appear at multiple L values in
# this pooled dataset -- these observations are not independent (pseudo-
# replication), so p-values/standard errors here are optimistic, not a
# publication-grade inference. Read the SIGN and relative magnitude of each
# coefficient as suggestive, not the exact p-value. A proper fix (clustered
# standard errors by pair, or one observation per pair) is flagged, not
# built tonight, given the exploratory scope Ross approved.
# =============================================================================
import logging
import os
import sys
import time
from typing import Dict, List

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from research.pit_wfa_wrds_daily import (
    load_universe_wrds_daily,
    determine_analysis_window,
    screen_universe_at_cutoff,
    backtest_pair_on_test_window,
    _TF_LABEL,
)
from research.overlap_threshold_pit_test import _fold_start_dates, _BARS_TO_CALENDAR_DAYS
from analysis import AnalysisPipeline
from data import DataAligner

log = logging.getLogger("multivariate_pit_predictors")

_OUT_DIR = os.path.join("output", "research")
_OUT_PATH = os.path.join(_OUT_DIR, "multivariate_pit_predictors_1D.parquet")

_DEFAULT_GRID_BARS = [126, 252, 504, 1008]
_OOS_CALENDAR_DAYS = 365
_MIN_OOS_TRADES = 3


def _setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def hedge_ratio_stability(universe: Dict[str, pd.DataFrame], pair_result,
                           train_start: pd.Timestamp, train_end: pd.Timestamp) -> float:
    """Coefficient of variation (|std/mean|) of the causal hedge_ratio_ols_t
    series over the training window -- lower means a more stable hedge ratio.
    Returns NaN if the pair can't be rebuilt or has too few finite points to
    judge (matches this project's own "too little evidence is not the same
    as a clean answer" convention, not a silent 0)."""
    sym_a, sym_b = pair_result.symbol_a, pair_result.symbol_b
    df_a = universe.get(sym_a)
    df_b = universe.get(sym_b)
    if df_a is None or df_b is None:
        return np.nan
    win_a = df_a.loc[(df_a.index >= train_start) & (df_a.index <= train_end)]
    win_b = df_b.loc[(df_b.index >= train_start) & (df_b.index <= train_end)]
    common_idx = win_a.index.intersection(win_b.index)
    if len(common_idx) < 60:
        return np.nan
    aligned = {sym_a: win_a.loc[common_idx], sym_b: win_b.loc[common_idx]}
    built = AnalysisPipeline._build_pair_result({"symbol_a": sym_a, "symbol_b": sym_b}, aligned, _TF_LABEL)
    if built is None:
        return np.nan
    _, per_bar = built
    hr_t = per_bar.get("hedge_ratio_ols_t")
    if hr_t is None:
        return np.nan
    hr_real = np.asarray(hr_t)
    hr_real = hr_real[np.isfinite(hr_real)]
    if len(hr_real) < 30 or np.mean(hr_real) == 0:
        return np.nan
    return float(np.std(hr_real) / abs(np.mean(hr_real)))


def run_pilot(grid_bars: List[int], n_folds: int, n_workers: int) -> pd.DataFrame:
    universe = load_universe_wrds_daily(columns=["close"])
    log.info(f"Universe: {len(universe)} symbols with daily data (WRDS-primary merged universe)")
    universe_start, universe_end = determine_analysis_window(universe)
    log.info(f"Analysis window: [{universe_start.date()}, {universe_end.date()}]")

    fold_starts = _fold_start_dates(universe_start, universe_end, n_folds, max(grid_bars))
    log.info(f"Folds: {[d.date() for d in fold_starts]}, grid: {grid_bars} "
             f"(GATED screen -- production MIN_PEARSON_CORR={Config.UNIVERSE.MIN_PEARSON_CORR}, "
             f"MIN_COINT_FRAC={Config.UNIVERSE.MIN_COINT_FRAC})")

    rows = []
    n_cells = len(fold_starts) * len(grid_bars)
    cell_i = 0
    for fold_start in fold_starts:
        for l_bars in grid_bars:
            cell_i += 1
            train_end = fold_start + pd.Timedelta(days=int(l_bars * _BARS_TO_CALENDAR_DAYS))
            test_start = train_end + pd.Timedelta(days=1)
            test_end = test_start + pd.Timedelta(days=_OOS_CALENDAR_DAYS)
            if test_end > universe_end:
                log.info(f"[{cell_i}/{n_cells}] fold={fold_start.date()} L={l_bars}: "
                         f"OOS window would run past the real universe end, skipping")
                continue

            t0 = time.time()
            log.info(f"[{cell_i}/{n_cells}] fold={fold_start.date()} L={l_bars} bars: screening...")
            confirmed = screen_universe_at_cutoff(universe, fold_start, train_end, n_workers)
            log.info(f"  {len(confirmed)} pairs confirmed in {time.time()-t0:.1f}s, "
                     f"computing hedge-ratio stability + backtesting OOS...")

            for pair_result in confirmed:
                hr_cv = hedge_ratio_stability(universe, pair_result, fold_start, train_end)
                trades, metrics = backtest_pair_on_test_window(
                    pair_result, universe, fold_start, test_start, test_end
                )
                n_trades = metrics.get("n_trades", 0)
                sharpe = metrics.get("sharpe", np.nan)
                held_up = bool(n_trades >= _MIN_OOS_TRADES and np.isfinite(sharpe) and sharpe > 0)
                rows.append({
                    "fold_start": fold_start, "nominal_l_bars": l_bars,
                    "symbol_a": pair_result.symbol_a, "symbol_b": pair_result.symbol_b,
                    "actual_n_overlap": pair_result.n_overlap,
                    "pearson_corr": getattr(pair_result, "pearson_corr", np.nan),
                    "coint_fraction_rolling": getattr(pair_result, "coint_fraction_rolling", np.nan),
                    "hedge_ratio_cv": hr_cv,
                    "oos_n_trades": n_trades, "oos_sharpe": sharpe, "held_up": held_up,
                })
            log.info(f"  cell complete in {time.time()-t0:.1f}s")

    return pd.DataFrame(rows)


def fit_logit(df: pd.DataFrame) -> str:
    import statsmodels.api as sm

    covariates = ["actual_n_overlap", "pearson_corr", "coint_fraction_rolling", "hedge_ratio_cv"]
    d = df.dropna(subset=covariates + ["held_up"]).copy()
    if len(d) < 30 or d["held_up"].nunique() < 2:
        return (f"Not enough clean data to fit (n={len(d)}, held_up unique values="
                f"{d['held_up'].nunique() if len(d) else 'n/a'}) -- reporting raw data only.")

    # z-score each covariate so coefficients are directly comparable in magnitude
    X = d[covariates].apply(lambda c: (c - c.mean()) / c.std())
    X = sm.add_constant(X)
    y = d["held_up"].astype(int)
    model = sm.Logit(y, X).fit(disp=0)
    return (f"n={len(d)} (pooled across all fold x L cells -- see the pseudo-replication "
            f"caveat in this file's header before over-reading p-values)\n\n"
            + model.summary().as_text())


def fit_gee(df: pd.DataFrame) -> str:
    """Same covariates/z-scoring as fit_logit, but via GEE (Generalized
    Estimating Equations) clustered by pair (symbol_a/symbol_b), exchangeable
    working correlation -- directly addresses fit_logit's own disclosed
    pseudo-replication limitation (the SAME pair appears at multiple L values
    within a fold, so its observations aren't independent) instead of just
    flagging it. Found via tonight's literature sweep pass 3, topic 1
    (2026-09-15) -- statsmodels.genmod.generalized_estimating_equations.GEE,
    already in this project's existing dependency set, no new package
    needed. Diagnostic re-fit only: does NOT replace fit_logit or change
    run_pilot's own data-generation path -- both are reported side by side
    for comparison, same "report both, don't silently swap" convention as
    the Kelly-multiplier grid elsewhere in this project."""
    import statsmodels.api as sm
    import statsmodels.genmod.generalized_estimating_equations as gee_mod

    covariates = ["actual_n_overlap", "pearson_corr", "coint_fraction_rolling", "hedge_ratio_cv"]
    d = df.dropna(subset=covariates + ["held_up"]).copy()
    if len(d) < 30 or d["held_up"].nunique() < 2:
        return (f"Not enough clean data to fit (n={len(d)}, held_up unique values="
                f"{d['held_up'].nunique() if len(d) else 'n/a'}) -- reporting raw data only.")
    if "symbol_a" not in d.columns or "symbol_b" not in d.columns:
        return "Cannot cluster by pair -- symbol_a/symbol_b columns not present in this data."

    d["pair_id"] = d["symbol_a"].astype(str) + "/" + d["symbol_b"].astype(str)
    n_pairs = d["pair_id"].nunique()
    if n_pairs < 2:
        return f"Only {n_pairs} distinct pair(s) in the data -- GEE clustering needs >=2."

    X = d[covariates].apply(lambda c: (c - c.mean()) / c.std())
    X = sm.add_constant(X)
    y = d["held_up"].astype(int)
    model = gee_mod.GEE(y, X, groups=d["pair_id"],
                         family=sm.families.Binomial(),
                         cov_struct=sm.cov_struct.Exchangeable()).fit()
    return (f"n={len(d)} observations pooled across {n_pairs} distinct pairs "
            f"(clustered, exchangeable working correlation -- addresses the "
            f"pseudo-replication caveat fit_logit's plain Logit does not)\n\n"
            + model.summary().as_text())


def main():
    import argparse
    p = argparse.ArgumentParser(
        description="Multivariate PIT-safe predictor study: overlap x corr x coint_frac x "
                    "hedge-ratio stability -> OOS held_up (1D, gated screen)"
    )
    p.add_argument("--grid", type=int, nargs="+", default=_DEFAULT_GRID_BARS)
    p.add_argument("--folds", type=int, default=1)
    p.add_argument("--n-workers", type=int, default=Config.RUNTIME.N_WORKERS)
    args = p.parse_args()

    _setup_logging()
    log.info("=== multivariate_pit_predictors.py: overlap x corr x coint_frac x hedge-ratio "
             "stability -> OOS success ===")

    os.makedirs(_OUT_DIR, exist_ok=True)
    t0 = time.time()
    df = run_pilot(args.grid, args.folds, args.n_workers)
    log.info(f"Pilot complete in {(time.time()-t0)/60:.1f} min, {len(df)} pair-cell observations")

    if df.empty:
        log.warning("No observations produced")
        return

    df.to_parquet(_OUT_PATH, index=False)
    log.info(f"Saved raw observations -> {_OUT_PATH}")

    log.info("\n=== Logit (naive, pseudo-replicated) ===\n" + fit_logit(df))
    log.info("\n=== GEE (clustered by pair, addresses pseudo-replication) ===\n" + fit_gee(df))


if __name__ == "__main__":
    main()
