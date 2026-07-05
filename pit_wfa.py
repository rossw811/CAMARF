"""
pit_wfa.py — Point-In-Time Portfolio-Wide Walk-Forward Analysis.

Motivation (2026-07-01 discussion with Ross): the existing wfa.py is
explicitly a "semi-WFA" (per its own module docstring) — the confirmed-pair
SELECTION is fixed (chosen using the full historical sample, which includes
every fold's test period), and only each pair's spread OU parameters are
re-estimated per fold. That means even wfa.py's walk-forward numbers rest on
a pair set chosen with look-ahead knowledge of how well it would perform.
This module removes that specific bias: at each fold's TRAIN cutoff, it
re-runs the SAME screening pipeline analysis.py uses (Pearson pre-filter ->
Engle-Granger + BH-FDR -> rolling coint_fraction -> structural exclusion ->
coint_frac threshold + secondary-evidence override) using ONLY data up to
that cutoff, producing a fresh, point-in-time confirmed-pair set specific to
that fold — not the pair set chosen by looking at the whole history. That
set is then traded forward into the fold's test window.

Scope, stated explicitly:
  - 1h only. 17 of 23 confirmed pairs are 1h, and a full-universe screening
    pass (Pearson + EG across ~1600 symbols) costs ~45-50 minutes per cutoff
    (measured directly in this session's full analysis.py rerun) — running
    this at multiple fold cutoffs across every timeframe would be a multi-
    hour-per-fold undertaking with little payoff for the TFs that contribute
    only 1-2 pairs each. A future session can extend this to other TFs if
    the 1h result justifies the added cost.
  - Universe: every symbol with a cached output/cache/{symbol}_1hr.parquet
    file (no asset-class map rebuilt — asset_class_map is passed as {} to
    the reused UniverseFilter.run()/CointScanner.scan() calls, which already
    default missing entries to "unknown"; this only affects cross-asset
    tagging cosmetics, not the cointegration decision itself).
  - Analysis window: [overall_min_date, overall_max_date] across the cached
    universe (handles ragged per-symbol history the same way the production
    pipeline already does, via DataAligner's NaN-tolerant alignment).
  - Fold fractions: IDENTICAL to wfa.py's FOLD_EXPANDING/FOLD_ROLLING
    (0.00-0.20/0.20-0.50, 0.00-0.50/0.50-0.80 expanding;
    0.00-0.20/0.20-0.50, 0.50-0.70/0.70-1.00 rolling) — same convention, for
    direct comparability against wfa.py's existing numbers.
  - Per-fold spread construction: matches wfa.py's own "causal series taken
    as-is" convention — once a pair is point-in-time CONFIRMED using
    TRAIN-only data, its per-bar trading series (rolling hedge ratio,
    z-score, half-life) is rebuilt over the full train+test window via
    analysis.py's own _build_pair_result() (already causal/trailing-window
    throughout, verified project-wide — no center=True anywhere), then
    sliced to the test window only for backtesting. Scalar summary fields
    used for gating (coint_fraction_rolling, half_life_trend_slope, Hurst)
    are therefore computed on train+test combined, not train-only — a
    smaller, secondary lookahead than the pair-SELECTION lookahead this
    module exists to eliminate, and explicitly flagged here rather than
    silently ignored.

Output:
  output/backtest/pit_wfa_fold_comparison.parquet — per-pair, per-fold metrics
  output/backtest/pit_wfa_portfolio.parquet — portfolio-level per-fold aggregate
  output/backtest/pit_wfa_pair_sets.parquet — which pairs were point-in-time
    confirmed at each fold cutoff, for comparison against the full-history set
  latest_run_pit_wfa.log
"""
import glob
import logging
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analysis import (
    AnalysisPipeline, UniverseFilter, CointScanner, CrossAssetTagger,
)
from backtest import BacktestEngine, RegimeConditioner, MLConditioner, compute_metrics, aggregate_portfolio
from config import Config
from data import DataAligner, DataStore

_ROOT = os.path.dirname(os.path.abspath(__file__))
_CACHE_DIR = os.path.join(_ROOT, "output", "cache")
_OUT_DIR = os.path.join(_ROOT, "output", "backtest")

_TF_LABEL = "1h"
_TF_CACHE_SUFFIX = "1hr"

# Identical to wfa.py's FOLD_EXPANDING/FOLD_ROLLING — same convention for
# direct comparability.
FOLD_EXPANDING = [
    (0.00, 0.20, 0.20, 0.50, "fold1_exp"),
    (0.00, 0.50, 0.50, 0.80, "fold2_exp"),
]
FOLD_ROLLING = [
    (0.00, 0.20, 0.20, 0.50, "fold1_roll"),
    (0.50, 0.70, 0.70, 1.00, "fold2_roll"),
]

log = logging.getLogger("pit_wfa")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_pit_wfa.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


# =============================================================================
# UNIVERSE LOADING
# =============================================================================

def load_universe_1h() -> Dict[str, pd.DataFrame]:
    """Every symbol with a cached {symbol}_1hr.parquet file."""
    universe = {}
    for path in glob.glob(os.path.join(_CACHE_DIR, f"*_{_TF_CACHE_SUFFIX}.parquet")):
        sym = os.path.basename(path)[: -len(f"_{_TF_CACHE_SUFFIX}.parquet")]
        df = DataStore.load(sym, _TF_LABEL)
        if df is not None and not df.empty:
            universe[sym] = df
    return universe


def determine_analysis_window(universe: Dict[str, pd.DataFrame]) -> Tuple[pd.Timestamp, pd.Timestamp]:
    """Overall [min_date, max_date] across the whole cached universe."""
    starts = [df.index.min() for df in universe.values()]
    ends = [df.index.max() for df in universe.values()]
    return min(starts), max(ends)


def compute_fold_dates(
    start: pd.Timestamp, end: pd.Timestamp, fold_spec: Tuple[float, float, float, float, str]
) -> Dict[str, pd.Timestamp]:
    """Converts a (train_start_pct, train_end_pct, test_start_pct, test_end_pct,
    label) fold spec into actual timestamps over [start, end]. Pure function,
    directly testable with synthetic start/end/fold_spec inputs."""
    train_start_pct, train_end_pct, test_start_pct, test_end_pct, label = fold_spec
    total = (end - start)
    return {
        "label": label,
        "train_start": start + total * train_start_pct,
        "train_end": start + total * train_end_pct,
        "test_start": start + total * test_start_pct,
        "test_end": start + total * test_end_pct,
    }


# =============================================================================
# POINT-IN-TIME SCREENING (reuses analysis.py's production building blocks)
# =============================================================================

def screen_universe_at_cutoff(
    universe: Dict[str, pd.DataFrame],
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    n_workers: int = 12,
) -> List["PairResult"]:
    """
    Re-runs the SAME screening sequence analysis.py's _run_one_tf() uses
    (Pearson pre-filter -> EG+BH-FDR -> rolling coint_fraction -> per-pair
    modeling -> structural exclusion -> coint_frac threshold + secondary-
    evidence override), restricted to [train_start, train_end] only. Returns
    the point-in-time confirmed PairResult list for this cutoff.
    """
    truncated = {
        sym: df.loc[(df.index >= train_start) & (df.index <= train_end)]
        for sym, df in universe.items()
    }
    truncated = {sym: df for sym, df in truncated.items() if len(df) >= 60}
    if len(truncated) < 10:
        return []

    aligned = DataAligner.align_universe(
        {f"{sym}_{_TF_LABEL}": df for sym, df in truncated.items()}, _TF_LABEL
    )
    if not aligned:
        return []

    uf_raw = UniverseFilter.run(
        aligned, {}, threshold=Config.UNIVERSE.MIN_PEARSON_CORR,
        tf_label=_TF_LABEL, return_matrices=True,
    )
    if not isinstance(uf_raw, tuple) or len(uf_raw) < 5:
        return []
    candidates, retained_symbols, _returns_mat, _corr_mat, _sym_order = uf_raw
    if not candidates:
        return []

    confirmed_dicts, _eg_stats = CointScanner.scan(
        candidate_pairs=candidates, aligned_data=aligned,
        symbols_in_corr=retained_symbols, tf_label=_TF_LABEL, n_workers=n_workers,
    )
    if not confirmed_dicts:
        return []

    confirmed_dicts = CointScanner.rolling_fraction(
        confirmed_dicts, aligned, _TF_LABEL, n_workers=n_workers
    )

    pair_results = []
    for pd_meta in confirmed_dicts:
        built = AnalysisPipeline._build_pair_result(pd_meta, aligned, _TF_LABEL)
        if built is not None:
            pair_results.append(built[0])

    # Structural exclusion (forex triangles, share-class pairs, same-index ETFs)
    pair_results = [
        p for p in pair_results
        if not CrossAssetTagger._shared_currency(p.symbol_a, p.symbol_b)
        and not CrossAssetTagger._is_share_class_pair(p.symbol_a, p.symbol_b)
        and not CrossAssetTagger._is_index_tracking_pair(p.symbol_a, p.symbol_b)
    ]

    # coint_frac threshold + secondary-evidence override — identical logic
    # to _save_tf_results(), reused directly rather than reimplemented.
    min_coint_frac = getattr(Config.UNIVERSE, "MIN_COINT_FRAC", 0.40)
    confirmed = []
    for p in pair_results:
        cf = getattr(p, "coint_fraction_rolling", np.nan)
        if not np.isfinite(cf) or cf >= min_coint_frac:
            confirmed.append(p)
        elif AnalysisPipeline.passes_coint_frac_secondary_evidence(p):
            confirmed.append(p)
    return confirmed


# =============================================================================
# TEST-WINDOW BACKTEST (causal series rebuilt over train+test, matching
# wfa.py's own convention)
# =============================================================================

def backtest_pair_on_test_window(
    pair_result, universe: Dict[str, pd.DataFrame],
    train_start: pd.Timestamp, test_start: pd.Timestamp, test_end: pd.Timestamp,
) -> Tuple[List, Dict]:
    sym_a, sym_b = pair_result.symbol_a, pair_result.symbol_b
    if sym_a not in universe or sym_b not in universe:
        return [], {}

    full_slice = {
        sym: universe[sym].loc[(universe[sym].index >= train_start) & (universe[sym].index <= test_end)]
        for sym in (sym_a, sym_b)
    }
    # drop_data_gap_rows=True: this is a single-pair/real-timestamp-join
    # consumer (per DataAligner.align_universe's own docstring), not the
    # main pipeline's cross-symbol dense-matrix construction that
    # screen_universe_at_cutoff() above correctly uses the default for.
    # Missing this produced the exact same calendar-padding bug caught
    # earlier this session in research/decoupling_backtest.py (aligned bar
    # count inflated ~5-6x vs the raw cached data for the same symbol/TF) —
    # same root cause, same fix, caught a second time in a different script.
    aligned = DataAligner.align_universe(
        {f"{sym}_{_TF_LABEL}": df for sym, df in full_slice.items()}, _TF_LABEL,
        drop_data_gap_rows=True,
    )
    if sym_a not in aligned or sym_b not in aligned:
        return [], {}

    # drop_data_gap_rows=True drops each symbol's OWN gap rows independently
    # (per-symbol, not a joint operation), so the two legs can come back
    # with slightly different lengths/timestamps even after alignment
    # (caught here: a real shape mismatch, e.g. 2203 vs 2202 bars, on the
    # first real pair tested) — _build_pair_result requires identical-length
    # arrays for elementwise ops (log_a - log_b, gap_flag_a & gap_flag_b).
    # Explicit inner-join on the shared real-timestamp intersection before
    # proceeding, rather than assuming align_universe already guarantees one.
    common_idx = aligned[sym_a].index.intersection(aligned[sym_b].index)
    if len(common_idx) < 60:
        return [], {}
    aligned = {sym_a: aligned[sym_a].loc[common_idx], sym_b: aligned[sym_b].loc[common_idx]}

    built = AnalysisPipeline._build_pair_result(
        {"symbol_a": sym_a, "symbol_b": sym_b}, aligned, _TF_LABEL
    )
    if built is None:
        return [], {}
    full_pair_result, per_bar = built

    spread_df = pd.DataFrame(
        {
            "spread": per_bar["spread"],
            "z_rolling": per_bar["z_rolling"],
            "z_expanding": per_bar["z_expanding"],
            "half_life_rolling": per_bar["half_life_rolling_series"],
            "gap_flag_a": per_bar["gap_flag_a"],
            "gap_flag_b": per_bar["gap_flag_b"],
            "hedge_ratio_ols_t": per_bar.get("hedge_ratio_ols_t"),
            "hedge_ratio_kalman_t": per_bar.get("hedge_ratio_kalman_t"),
        },
        index=per_bar["index"],
    )
    test_slice = spread_df.loc[(spread_df.index >= test_start) & (spread_df.index <= test_end)]
    if len(test_slice) < 30:
        return [], {}

    pair_row = pd.Series({**vars(full_pair_result), "tf_label": _TF_LABEL})
    engine = BacktestEngine(
        cfg=Config.BACKTEST, regime_cond=RegimeConditioner(enabled=False),
        ml_cond=MLConditioner(enabled=False),
    )
    trades = engine.run(pair_row, test_slice, hedge_method="ols", holdout_only=False)
    metrics = compute_metrics(trades, _TF_LABEL, sym_a, sym_b, "ols") if trades else {}
    return trades, metrics


# =============================================================================
# MAIN
# =============================================================================

def run_fold(
    universe: Dict[str, pd.DataFrame], fold_dates: Dict, wfa_variant: str, n_workers: int
) -> Tuple[List[Dict], Dict, List[Dict]]:
    label = fold_dates["label"]
    log.info("[%s/%s] screening train window [%s, %s] (point-in-time, no test-period data used)...",
              wfa_variant, label, fold_dates["train_start"].date(), fold_dates["train_end"].date())
    t0 = time.time()
    confirmed = screen_universe_at_cutoff(
        universe, fold_dates["train_start"], fold_dates["train_end"], n_workers
    )
    log.info("[%s/%s] %d pairs point-in-time confirmed (%.1f min)",
              wfa_variant, label, len(confirmed), (time.time() - t0) / 60)

    pair_set_rows = [
        {"wfa_variant": wfa_variant, "fold": label, "symbol_a": p.symbol_a, "symbol_b": p.symbol_b,
         "coint_fraction_rolling": p.coint_fraction_rolling, "half_life_rolling": p.half_life_rolling}
        for p in confirmed
    ]

    all_trades, all_metrics = [], []
    for p in confirmed:
        trades, metrics = backtest_pair_on_test_window(
            p, universe, fold_dates["train_start"], fold_dates["test_start"], fold_dates["test_end"]
        )
        if trades:
            all_trades.extend(trades)
            if metrics:
                all_metrics.append(metrics)

    portfolio_stats = aggregate_portfolio(all_trades, all_metrics)
    portfolio_stats.update({
        "wfa_variant": wfa_variant, "fold": label,
        "n_pit_confirmed_pairs": len(confirmed),
        "n_pairs_with_trades": len(all_metrics),
    })
    log.info("[%s/%s] backtest: %d pairs traded, %d trades, portfolio Sharpe=%.4f",
              wfa_variant, label, len(all_metrics), len(all_trades),
              portfolio_stats.get("sharpe_portfolio", float("nan")))

    return all_metrics, portfolio_stats, pair_set_rows


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Point-in-time portfolio-wide WFA (1h)")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--variant", choices=["expanding", "rolling", "both"], default="both")
    args = parser.parse_args()

    _setup_logging()
    t0 = time.time()
    log.info("=== pit_wfa.py: Point-In-Time Portfolio-Wide Walk-Forward Analysis (1h) ===")
    log.info("Unlike wfa.py's semi-WFA, pair SELECTION itself is re-derived per fold "
             "using only train-window data — see module docstring for exact scope.")

    universe = load_universe_1h()
    log.info("Universe: %d symbols with cached 1h data", len(universe))
    start, end = determine_analysis_window(universe)
    log.info("Analysis window: [%s, %s]", start.date(), end.date())

    variants = []
    if args.variant in ("expanding", "both"):
        variants.append(("expanding", FOLD_EXPANDING))
    if args.variant in ("rolling", "both"):
        variants.append(("rolling", FOLD_ROLLING))

    fold_metric_rows, portfolio_rows, pair_set_rows = [], [], []
    for wfa_variant, fold_specs in variants:
        for fold_spec in fold_specs:
            fold_dates = compute_fold_dates(start, end, fold_spec)
            metrics, portfolio_stats, pair_sets = run_fold(universe, fold_dates, wfa_variant, args.workers)
            fold_metric_rows.extend(metrics)
            portfolio_rows.append(portfolio_stats)
            pair_set_rows.extend(pair_sets)

    os.makedirs(_OUT_DIR, exist_ok=True)
    if fold_metric_rows:
        pd.DataFrame(fold_metric_rows).to_parquet(
            os.path.join(_OUT_DIR, "pit_wfa_fold_comparison.parquet"), index=False
        )
    if portfolio_rows:
        portfolio_df = pd.DataFrame(portfolio_rows)
        portfolio_df.to_parquet(os.path.join(_OUT_DIR, "pit_wfa_portfolio.parquet"), index=False)
        log.info("\n%s", portfolio_df.to_string(index=False))
    if pair_set_rows:
        pd.DataFrame(pair_set_rows).to_parquet(
            os.path.join(_OUT_DIR, "pit_wfa_pair_sets.parquet"), index=False
        )

    log.info("Saved -> output/backtest/pit_wfa_{fold_comparison,portfolio,pair_sets}.parquet")
    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("pit_wfa.py complete (%.1f min)", runtime)


if __name__ == "__main__":
    main()
