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

# Train/test split-ratio sweep (task #67, 2026-07-14) — each entry is a
# single contiguous train-then-test split (no fold-to-fold structure, no
# gap between train_end and test_start) at a fixed fraction of the
# analysis window. Scoped by Ross earlier this session ("test different
# training window periods... 50/50, 60/40, 70/30, 80/20, 90/10... with
# explicit overfitting discipline"). wfa_variant is a pass-through label
# only (see run_fold — it's never branched on internally), so reusing this
# mechanism for a plain split sweep is safe.
FOLD_SPLIT_SWEEP = [
    (0.00, 0.50, 0.50, 1.00, "split_50_50"),
    (0.00, 0.60, 0.60, 1.00, "split_60_40"),
    (0.00, 0.70, 0.70, 1.00, "split_70_30"),
    (0.00, 0.80, 0.80, 1.00, "split_80_20"),
    (0.00, 0.90, 0.90, 1.00, "split_90_10"),
]

# Absolute train-window-LENGTH sweep (task #67, 2026-07-14) — the second,
# distinct dimension from FOLD_SPLIT_SWEEP's split RATIO (see Development.md,
# "Two distinct dimensions, not to be conflated"). Fixed calendar train
# durations (not fractions of total history), all anchored at the SAME
# test_start/test_end (0.80/1.00 — matching split_80_20's anchor point, for
# direct comparability) so only train LENGTH varies between variants, not
# test-window placement. Window days are converted to fractions of the
# universe's actual [start, end] span at runtime (build_window_sweep_specs),
# since the real span isn't known until the universe is loaded.
WINDOW_SWEEP_DAYS = [180, 365, 545, 730]  # 6mo / 1yr / 1.5yr / 2yr
WINDOW_SWEEP_ANCHOR_PCT = 0.80


def build_window_sweep_specs(
    start: pd.Timestamp, end: pd.Timestamp,
    window_days_list=WINDOW_SWEEP_DAYS, anchor_pct: float = WINDOW_SWEEP_ANCHOR_PCT,
):
    """Converts absolute train-window day counts into (train_start_pct,
    train_end_pct, test_start_pct, test_end_pct, label) fold specs anchored
    at a fixed test_start/test_end, for direct use with compute_fold_dates.
    A window longer than the available pre-anchor history is clipped to
    train_start_pct=0.0 (uses everything available) rather than silently
    dropped — logged by the caller, not hidden."""
    total_days = (end - start).days
    specs = []
    for wd in window_days_list:
        train_start_pct = max(0.0, anchor_pct - wd / total_days)
        specs.append((train_start_pct, anchor_pct, anchor_pct, 1.0, f"window_{wd}d"))
    return specs


# Fixed-calendar-checkpoint variant (Phase 13/§7.3.1, 2026-07-14) — the
# paper's original "point-in-time screening at 3 checkpoints" plan, distinct
# from both FOLD_SPLIT_SWEEP (fractional split ratios) and the window-length
# sweep (fixed train duration, single fixed anchor): here each checkpoint is
# an EXPLICIT CALENDAR DATE used as train_end/test_start, test_end always
# the full available window's end ("trade forward from cutoff to now").
CHECKPOINT_DATES = ["2024-02-01", "2025-01-01", "2025-08-01"]

# Minimum-training-history comparison arm (2026-07-14, Ross's request) — the
# checkpoint_sweep's worst result (2024-02-01, -1.9037 Sharpe) had only ~7mo
# of training history, the shortest of the 3. This tests a "wait for a full
# year before going live" policy directly: same test window (trade forward
# to now), just a later, more-trained first checkpoint, for a clean apples-
# to-apples read against checkpoint_2024-02-01 specifically.
MIN_HISTORY_CHECKPOINT_DATES = ["2024-07-13"]  # exactly 12mo after analysis start (2023-07-13)


def build_checkpoint_specs(start: pd.Timestamp, end: pd.Timestamp, checkpoint_dates=CHECKPOINT_DATES):
    """Converts explicit calendar checkpoint dates into (train_start_pct=0.0,
    train_end_pct, test_start_pct, test_end_pct=1.0, label) fold specs for
    compute_fold_dates. A checkpoint outside [start, end] is skipped (logged
    by the caller), not silently clamped — an out-of-range checkpoint is a
    real scoping problem worth surfacing, not papering over."""
    total_days = (end - start).days
    specs = []
    for cp in checkpoint_dates:
        cp_ts = pd.Timestamp(cp)
        if cp_ts <= start or cp_ts >= end:
            specs.append(None)
            continue
        pct = (cp_ts - start).days / total_days
        specs.append((0.0, pct, pct, 1.0, f"checkpoint_{cp}"))
    return specs


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

    # BUG-D69 (2026-07-14): full_pair_result's scalar summary fields
    # (coint_fraction_rolling, half_life_trend_slope, etc.) were computed
    # above on the FULL train+test window, purely as a byproduct of
    # rebuilding the per-bar trading series for the test-window backtest —
    # they are NOT point-in-time. Currently inert for THIS specific call
    # (no storm_flags passed, regime_cond/ml_cond both disabled below, so
    # nothing reads these fields for a gating/sizing decision) but that is
    # a fragile invariant, not a real guarantee — a future caller reusing
    # this function with STORM flags or the conditioners enabled would
    # silently reintroduce the same lookahead BUG-D68 fixed at the
    # selection stage. Override with the ORIGINAL, genuinely train-only
    # pair_result's own scalar fields (already correct — this is exactly
    # what screen_universe_at_cutoff() used to make the accept/reject
    # decision) so pair_row is point-in-time-safe regardless of which
    # downstream logic reads it, not just for today's disabled-conditioner
    # configuration.
    pair_row = pd.Series({
        **vars(full_pair_result),
        "coint_fraction_rolling": getattr(pair_result, "coint_fraction_rolling", np.nan),
        "half_life_trend_slope": getattr(pair_result, "half_life_trend_slope", np.nan),
        "mean_reversion_speed": getattr(pair_result, "mean_reversion_speed", np.nan),
        "tf_label": _TF_LABEL,
    })
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


# Persistence-filter comparison arm (2026-07-14, Ross's request after seeing
# the checkpoint_sweep result) — tests whether requiring a pair to survive
# TWO independent point-in-time screens (not just one snapshot) before it's
# tradeable would have avoided checkpoint 1's -1.9037 Sharpe. A pair must be
# confirmed at BOTH (checkpoint - lookback) and checkpoint itself; only the
# intersection is traded, using the checkpoint's own (more current) pair_result
# for actual trading — the earlier screen is a filter, not a data source.
PERSISTENCE_LOOKBACK_DAYS = 90


def run_persistence_fold(
    universe: Dict[str, pd.DataFrame], fold_dates: Dict, wfa_variant: str, n_workers: int,
    lookback_days: int = PERSISTENCE_LOOKBACK_DAYS,
) -> Tuple[List[Dict], Dict, List[Dict]]:
    label = fold_dates["label"]
    earlier_cutoff = fold_dates["train_end"] - pd.Timedelta(days=lookback_days)

    log.info("[%s/%s] screening EARLIER cutoff [%s, %s] (persistence pre-check)...",
              wfa_variant, label, fold_dates["train_start"].date(), earlier_cutoff.date())
    t0 = time.time()
    confirmed_earlier = screen_universe_at_cutoff(
        universe, fold_dates["train_start"], earlier_cutoff, n_workers
    )
    earlier_keys = {(p.symbol_a, p.symbol_b) for p in confirmed_earlier}
    log.info("[%s/%s] %d pairs confirmed at earlier cutoff (%.1f min)",
              wfa_variant, label, len(confirmed_earlier), (time.time() - t0) / 60)

    log.info("[%s/%s] screening train window [%s, %s] (point-in-time)...",
              wfa_variant, label, fold_dates["train_start"].date(), fold_dates["train_end"].date())
    t0 = time.time()
    confirmed_now = screen_universe_at_cutoff(
        universe, fold_dates["train_start"], fold_dates["train_end"], n_workers
    )
    log.info("[%s/%s] %d pairs point-in-time confirmed at full cutoff (%.1f min)",
              wfa_variant, label, len(confirmed_now), (time.time() - t0) / 60)

    persistent = [p for p in confirmed_now if (p.symbol_a, p.symbol_b) in earlier_keys]
    log.info("[%s/%s] %d/%d pairs survive the persistence filter (confirmed at both cutoffs)",
              wfa_variant, label, len(persistent), len(confirmed_now))

    pair_set_rows = [
        {"wfa_variant": wfa_variant, "fold": label, "symbol_a": p.symbol_a, "symbol_b": p.symbol_b,
         "coint_fraction_rolling": p.coint_fraction_rolling, "half_life_rolling": p.half_life_rolling}
        for p in persistent
    ]

    all_trades, all_metrics = [], []
    for p in persistent:
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
        "n_pit_confirmed_pairs": len(persistent),
        "n_pairs_with_trades": len(all_metrics),
        "n_pre_filter_pairs": len(confirmed_now),
    })
    log.info("[%s/%s] backtest: %d pairs traded, %d trades, portfolio Sharpe=%.4f",
              wfa_variant, label, len(all_metrics), len(all_trades),
              portfolio_stats.get("sharpe_portfolio", float("nan")))

    return all_metrics, portfolio_stats, pair_set_rows


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Point-in-time portfolio-wide WFA (1h)")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument(
        "--variant",
        choices=["expanding", "rolling", "both", "split_sweep", "window_sweep", "checkpoint_sweep",
                 "persistence_sweep", "min_history_sweep"],
        default="both",
    )
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
    if args.variant == "split_sweep":
        variants.append(("split_sweep", FOLD_SPLIT_SWEEP))
    if args.variant == "window_sweep":
        window_specs = build_window_sweep_specs(start, end)
        for (ts_pct, te_pct, _, _, label), wd in zip(window_specs, WINDOW_SWEEP_DAYS):
            if wd / (end - start).days > WINDOW_SWEEP_ANCHOR_PCT:
                log.warning(
                    "[%s] requested %dd train window exceeds available pre-anchor history — "
                    "clipped to train_start_pct=%.3f (uses everything available before the anchor)",
                    label, wd, ts_pct,
                )
        variants.append(("window_sweep", window_specs))
    if args.variant == "checkpoint_sweep":
        checkpoint_specs = build_checkpoint_specs(start, end)
        valid_specs = []
        for spec, cp in zip(checkpoint_specs, CHECKPOINT_DATES):
            if spec is None:
                log.warning("[checkpoint_%s] outside analysis window [%s, %s] — skipped",
                            cp, start.date(), end.date())
            else:
                valid_specs.append(spec)
        variants.append(("checkpoint_sweep", valid_specs))
    if args.variant == "persistence_sweep":
        checkpoint_specs = build_checkpoint_specs(start, end)
        valid_specs = []
        for spec, cp in zip(checkpoint_specs, CHECKPOINT_DATES):
            if spec is None:
                log.warning("[checkpoint_%s] outside analysis window [%s, %s] — skipped",
                            cp, start.date(), end.date())
            else:
                valid_specs.append(spec)
        variants.append(("persistence_sweep", valid_specs))
    if args.variant == "min_history_sweep":
        checkpoint_specs = build_checkpoint_specs(start, end, checkpoint_dates=MIN_HISTORY_CHECKPOINT_DATES)
        valid_specs = [s for s in checkpoint_specs if s is not None]
        variants.append(("min_history_sweep", valid_specs))

    os.makedirs(_OUT_DIR, exist_ok=True)

    fold_metric_rows, portfolio_rows, pair_set_rows = [], [], []
    for wfa_variant, fold_specs in variants:
        for fold_spec in fold_specs:
            fold_dates = compute_fold_dates(start, end, fold_spec)
            runner = run_persistence_fold if wfa_variant == "persistence_sweep" else run_fold
            metrics, portfolio_stats, pair_sets = runner(universe, fold_dates, wfa_variant, args.workers)
            fold_metric_rows.extend(metrics)
            portfolio_rows.append(portfolio_stats)
            pair_set_rows.extend(pair_sets)

            # Checkpoint after every fold (2026-07-14) — a multi-hour sweep
            # previously lost ALL folds' results to a mid-run process kill
            # because output only got written once, after every fold
            # finished. Overwrites the same final output paths each time, so
            # a killed run always leaves the latest complete state on disk
            # instead of nothing.
            if fold_metric_rows:
                pd.DataFrame(fold_metric_rows).to_parquet(
                    os.path.join(_OUT_DIR, "pit_wfa_fold_comparison.parquet"), index=False
                )
            if portfolio_rows:
                pd.DataFrame(portfolio_rows).to_parquet(
                    os.path.join(_OUT_DIR, "pit_wfa_portfolio.parquet"), index=False
                )
            if pair_set_rows:
                pd.DataFrame(pair_set_rows).to_parquet(
                    os.path.join(_OUT_DIR, "pit_wfa_pair_sets.parquet"), index=False
                )
            log.info("[%s/%s] checkpoint saved (%d folds completed so far)",
                      wfa_variant, fold_dates["label"], len(portfolio_rows))

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
