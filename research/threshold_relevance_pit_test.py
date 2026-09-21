# =============================================================================
# CAMARF -- threshold_relevance_pit_test.py
#
# Empirical, PIT-safe study of whether this project's two hard cross-sectional
# gates -- Config.UNIVERSE.MIN_PEARSON_CORR (0.40, applied before any
# cointegration test even runs) and Config.UNIVERSE.MIN_COINT_FRAC (0.70,
# applied after EG+FDR confirmation, on the rolling cointegration fraction)
# -- actually predict OOS backtest success, or are arbitrary cutoffs whose
# real relevance has never been measured (Ross, 2026-09-12: "let's see if .4
# cointegration is a reliable indicator for successful strategies... test the
# degree that cointegration has to be in to see its relevance in a
# successful PIT backtest" -- clarified to mean BOTH thresholds).
#
# METHOD: a sibling to research/overlap_threshold_pit_test.py, sharing its
# PIT-safe train/OOS-test machinery (pit_wfa_wrds_daily.py's screen/backtest
# functions) but testing a different axis. The key difference: this project's
# OWN screen_universe_at_cutoff() HARD-GATES on both thresholds before a pair
# is ever visible -- to measure whether the threshold VALUE matters (not just
# pass/fail), pairs below the current cutoffs must survive to be scored too.
# _screen_universe_at_cutoff_ungated() below is a local, deliberately-lowered-
# threshold variant (COPIED, not monkeypatched -- same reasoning as pit_wfa_
# wrds_daily.py's own "copied, not imported" precedent for backtest_pair_on_
# test_window: the original screen function stays untouched for every other
# caller, only this file's own copy has the gates relaxed):
#   - MIN_PEARSON_CORR lowered to _LOWERED_PEARSON_THRESHOLD (0.20, not 0.0 --
#     going to zero would generate a computationally infeasible O(N^2)
#     candidate set at ~44,000-symbol scale; 0.20 gives real range below the
#     production 0.40 cutoff while staying tractable).
#   - MIN_COINT_FRAC gate removed entirely (cheap to relax -- this happens
#     AFTER EG+FDR+rolling-fraction already ran on the corr-and-EG-confirmed
#     set, no extra compute from removing it).
# Every surviving pair's ACTUAL pearson_corr and coint_fraction_rolling are
# recorded, then bucketed against real OOS backtest outcomes (same held_up
# criterion as overlap_threshold_pit_test.py: OOS Sharpe > 0 AND >=
# _MIN_OOS_TRADES trades) to see whether either threshold's value actually
# predicts success, independent of overlap length.
#
# PILOT SCOPE (Ross, 2026-09-12: "small pilot first"): ONE fold, reusing the
# same anchor-at-latest-usable-start logic already fixed in overlap_threshold_
# pit_test.py. Not the full sweep -- get a first real signal before
# committing more compute.
# =============================================================================
import logging
import os
import sys
import time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import AnalysisPipeline, UniverseFilter, CointScanner, CrossAssetTagger
from config import Config
from data import DataAligner
from research.pit_wfa_wrds_daily import (
    load_universe_wrds_daily,
    determine_analysis_window,
    backtest_pair_on_test_window,
    _TF_LABEL,
)
from research.overlap_threshold_pit_test import _fold_start_dates, _BARS_TO_CALENDAR_DAYS

log = logging.getLogger("threshold_relevance_pit_test")

_OUT_DIR = os.path.join("output", "research")
_OUT_PATH = os.path.join(_OUT_DIR, "threshold_relevance_pit_test_1D.parquet")

_LOWERED_PEARSON_THRESHOLD = 0.20  # see header -- 0.0 is computationally infeasible at this scale
_TRAIN_L_BARS = 504  # matches the overlap pilot's one cell that actually produced confirmed pairs
_OOS_CALENDAR_DAYS = 365
_MIN_OOS_TRADES = 3


def _setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def screen_universe_at_cutoff_ungated(
    universe: Dict[str, pd.DataFrame], train_start: pd.Timestamp, train_end: pd.Timestamp,
    n_workers: int, correlation_batch_size: int = 1500,
) -> List["object"]:
    """COPIED from pit_wfa_wrds_daily.screen_universe_at_cutoff, gates
    relaxed per this file's header. Every other step (Pearson prefilter at
    the lowered threshold, EG+BH-FDR, rolling coint_fraction, structural
    exclusion) is IDENTICAL to production -- only the two threshold gates
    this study is measuring are removed, not the underlying screening
    logic itself, so a pair's pearson_corr/coint_fraction_rolling values
    are directly comparable to what production would have computed."""
    truncated = {
        sym: df.loc[(df.index >= train_start) & (df.index <= train_end)]
        for sym, df in universe.items()
    }
    truncated = {sym: df for sym, df in truncated.items() if len(df) >= 60}
    if len(truncated) < 10:
        return []

    aligned = DataAligner.align_universe(
        {f"{sym}_{_TF_LABEL}": df for sym, df in truncated.items()}, _TF_LABEL,
    )
    if not aligned:
        return []

    returns, syms, _dates = UniverseFilter.build_returns_matrix(aligned)
    if len(syms) < 10:
        return []
    candidates = UniverseFilter.chunked_pearson_candidate_pairs(
        returns, syms, threshold=_LOWERED_PEARSON_THRESHOLD, asset_class_map={},
        batch_size=correlation_batch_size, progress_every=50,
        progress_label=f"[{train_end.date()}] ",
    )
    if not candidates:
        return []

    confirmed_dicts, _eg_stats = CointScanner.scan(
        candidate_pairs=candidates, aligned_data=aligned,
        symbols_in_corr=syms, tf_label=_TF_LABEL, n_workers=n_workers,
    )
    if not confirmed_dicts:
        return []

    confirmed_dicts = CointScanner.rolling_fraction(confirmed_dicts, aligned, _TF_LABEL, n_workers=n_workers)

    pair_results = []
    for pd_meta in confirmed_dicts:
        built = AnalysisPipeline._build_pair_result(pd_meta, aligned, _TF_LABEL)
        if built is not None:
            pair_results.append(built[0])

    pair_results = [
        p for p in pair_results
        if not CrossAssetTagger._shared_currency(p.symbol_a, p.symbol_b)
        and not CrossAssetTagger._is_share_class_pair(p.symbol_a, p.symbol_b)
        and not CrossAssetTagger._is_index_tracking_pair(p.symbol_a, p.symbol_b)
    ]

    # NO MIN_COINT_FRAC gate here -- the whole point of this study is to see
    # the OOS outcome across the full range of coint_fraction_rolling, not
    # just the pairs that already cleared the production 0.70 cutoff.
    return pair_results


def run_pilot(n_folds: int, n_workers: int) -> pd.DataFrame:
    universe = load_universe_wrds_daily(columns=["close"])
    log.info(f"Universe: {len(universe)} symbols with daily data (WRDS-primary merged universe)")
    universe_start, universe_end = determine_analysis_window(universe)
    log.info(f"Analysis window: [{universe_start.date()}, {universe_end.date()}]")

    fold_starts = _fold_start_dates(universe_start, universe_end, n_folds, _TRAIN_L_BARS)
    log.info(f"Folds: {[d.date() for d in fold_starts]}, train_l_bars={_TRAIN_L_BARS}, "
             f"lowered_pearson_threshold={_LOWERED_PEARSON_THRESHOLD} "
             f"(production MIN_PEARSON_CORR={Config.UNIVERSE.MIN_PEARSON_CORR}, "
             f"production MIN_COINT_FRAC={Config.UNIVERSE.MIN_COINT_FRAC})")

    rows = []
    for i, fold_start in enumerate(fold_starts):
        train_end = fold_start + pd.Timedelta(days=int(_TRAIN_L_BARS * _BARS_TO_CALENDAR_DAYS))
        test_start = train_end + pd.Timedelta(days=1)
        test_end = test_start + pd.Timedelta(days=_OOS_CALENDAR_DAYS)
        if test_end > universe_end:
            log.info(f"[{i+1}/{len(fold_starts)}] fold={fold_start.date()}: "
                     f"OOS window would run past the real universe end, skipping")
            continue

        t0 = time.time()
        log.info(f"[{i+1}/{len(fold_starts)}] fold={fold_start.date()} "
                 f"(train=[{fold_start.date()},{train_end.date()}], "
                 f"test=[{test_start.date()},{test_end.date()}]): screening (ungated)...")
        pair_results = screen_universe_at_cutoff_ungated(universe, fold_start, train_end, n_workers)
        log.info(f"  {len(pair_results)} pairs survived EG+FDR (ungated on corr/coint_frac) "
                 f"in {time.time()-t0:.1f}s, backtesting OOS...")

        for pair_result in pair_results:
            trades, metrics = backtest_pair_on_test_window(
                pair_result, universe, fold_start, test_start, test_end
            )
            n_trades = metrics.get("n_trades", 0)
            sharpe = metrics.get("sharpe", np.nan)
            held_up = bool(n_trades >= _MIN_OOS_TRADES and np.isfinite(sharpe) and sharpe > 0)
            rows.append({
                "fold_start": fold_start, "symbol_a": pair_result.symbol_a,
                "symbol_b": pair_result.symbol_b,
                "pearson_corr": getattr(pair_result, "pearson_corr", np.nan),
                "coint_fraction_rolling": getattr(pair_result, "coint_fraction_rolling", np.nan),
                "coint_pvalue_adjusted": getattr(pair_result, "coint_pvalue_adjusted", np.nan),
                "oos_n_trades": n_trades, "oos_sharpe": sharpe, "held_up": held_up,
            })
        log.info(f"  cell complete in {time.time()-t0:.1f}s")

    return pd.DataFrame(rows)


def summarize_by_threshold(df: pd.DataFrame, value_col: str, edges: List[float]) -> pd.DataFrame:
    """False-confirmation rate by threshold-value bucket, for either
    pearson_corr or coint_fraction_rolling."""
    if df.empty:
        return df
    d = df.copy()
    d["bucket"] = pd.cut(d[value_col], bins=edges, right=False).astype(str)

    def _agg(g):
        return pd.Series({
            "n_pairs": len(g),
            "n_held_up": g["held_up"].sum(),
            "held_up_rate": g["held_up"].mean(),
        })

    return d.groupby("bucket", observed=True).apply(_agg, include_groups=False).reset_index()


def main():
    import argparse
    p = argparse.ArgumentParser(
        description="Empirical PIT-safe MIN_PEARSON_CORR/MIN_COINT_FRAC relevance study (1D)"
    )
    p.add_argument("--folds", type=int, default=1)
    p.add_argument("--n-workers", type=int, default=Config.RUNTIME.N_WORKERS)
    args = p.parse_args()

    _setup_logging()
    log.info("=== threshold_relevance_pit_test.py: empirical PIT-safe threshold-relevance study ===")

    os.makedirs(_OUT_DIR, exist_ok=True)
    t0 = time.time()
    df = run_pilot(args.folds, args.n_workers)
    log.info(f"Pilot complete in {(time.time()-t0)/60:.1f} min, {len(df)} pair observations")

    if df.empty:
        log.warning("No observations produced")
        return

    df.to_parquet(_OUT_PATH, index=False)
    log.info(f"Saved raw observations -> {_OUT_PATH}")

    corr_summary = summarize_by_threshold(
        df, "pearson_corr", [_LOWERED_PEARSON_THRESHOLD, 0.30, 0.40, 0.50, 0.60, 1.01]
    )
    coint_frac_summary = summarize_by_threshold(
        df, "coint_fraction_rolling", [0.0, 0.40, 0.55, 0.70, 0.85, 1.01]
    )
    corr_path = _OUT_PATH.replace(".parquet", "_by_pearson_corr.parquet")
    coint_path = _OUT_PATH.replace(".parquet", "_by_coint_frac.parquet")
    corr_summary.to_parquet(corr_path, index=False)
    coint_frac_summary.to_parquet(coint_path, index=False)
    log.info(f"Saved -> {corr_path}, {coint_path}")
    log.info("\nBy pearson_corr (production MIN_PEARSON_CORR=%.2f):\n%s",
             Config.UNIVERSE.MIN_PEARSON_CORR, corr_summary.to_string(index=False))
    log.info("\nBy coint_fraction_rolling (production MIN_COINT_FRAC=%.2f):\n%s",
             Config.UNIVERSE.MIN_COINT_FRAC, coint_frac_summary.to_string(index=False))


if __name__ == "__main__":
    main()
