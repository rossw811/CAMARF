# =============================================================================
# CAMARF — overlap_threshold_pit_test.py
#
# Empirical, PIT-safe study of MIN_OVERLAP_BY_TF: at what real overlap-bar
# count does an EG/BH-FDR-confirmed pair actually hold up out-of-sample,
# rather than picking an arbitrary constant (Ross, 2026-09-12, live chat
# authorization, verbatim: "i'd ideally like a test to see at what value is
# the asset actually traceable rather than picking a random arbitrary number
# accounting for PIT and lead lag").
#
# METHOD (design confirmed with Ross before this file existed, per that same
# message):
#   1. For a grid of nominal training-window lengths L (bar counts), and a
#      handful of independent historical fold start-points, run this
#      project's OWN already-vetted PIT-safe screen (research.pit_wfa_wrds_
#      daily.screen_universe_at_cutoff) restricted to [fold_start, fold_start
#      + L bars] -- i.e., re-confirm pairs using ONLY data that would have
#      been available at that point in time. This is the exact same
#      screening SEQUENCE (Pearson prefilter -> EG+BH-FDR -> rolling
#      coint_fraction -> structural exclusion -> coint_frac threshold) as
#      the production pipeline, not a simplified stand-in.
#   2. Each confirmed pair's REAL overlap-bar count within that window
#      (PairResult.n_overlap) is recorded and used for bucketing -- not the
#      nominal L -- since gaps/differing per-symbol availability mean actual
#      overlap can fall short of the nominal window length.
#   3. Each pair is backtested on a fixed-length, chronologically-later,
#      non-overlapping OOS window immediately following the training window
#      (research.pit_wfa_wrds_daily.backtest_pair_on_test_window -- the same
#      production BacktestEngine, not a simplified proxy). "Held up" =
#      OOS Sharpe > 0 AND >= _MIN_OOS_TRADES trades (a pair with too few OOS
#      trades to even compute a meaningful Sharpe is treated as not having
#      demonstrated anything, not as a pass by default).
#   4. Lead-lag control (Ross's explicit ask): for each pair, research.
#      lead_lag_scan's own lagged_corr_scan/best_lag machinery computes the
#      best-lag correlation lift over lag-0 on the TRAINING window's gap-
#      aware returns. Pairs whose lift clears _LEAD_LAG_MIN_LIFT (same
#      default lead_lag_scan.py's own CLI already uses) are flagged
#      mechanical_lead_lag=True and reported SEPARATELY, since a pair driven
#      by a mechanical lag relationship could "hold up" OOS for reasons
#      unrelated to genuine cointegration, which would bias the main curve.
#   5. false_confirmation_rate(overlap_bucket) = 1 - mean(held_up), computed
#      per timeframe, per overlap-bucket, split by mechanical_lead_lag.
#
# COMPUTE COST, disclosed up front rather than discovered mid-run: each
# (fold, L) cell is a FULL production-scale PIT screen -- the exact same
# cost class as research/full_universe_eg_confirmation.py's own re-run
# (47.5 min at 1D/10y real-universe scale, 2026-09-12). The default grid/fold
# count below is deliberately small (a pilot, not the full sweep) --
# --grid and --folds let Ross scale this up once the pilot's shape looks
# right, rather than committing many CachyOS-hours unsupervised on a first
# pass.
#
# NOT run yet as of this file's creation -- built and synthetic-verified
# (debug/_verify_overlap_threshold_pit_test.py) but the real pilot run is a
# separate, explicit step (python research/overlap_threshold_pit_test.py),
# left for Ross/the next session to launch once reviewed.
# =============================================================================
import argparse
import logging
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from research.pit_wfa_wrds_daily import (
    load_universe_wrds_daily,
    determine_analysis_window,
    screen_universe_at_cutoff,
    backtest_pair_on_test_window,
    _TF_LABEL,
)
from research.lead_lag_scan import lagged_corr_scan, best_lag
from data import _clean_close, _gap_aware_returns

log = logging.getLogger("overlap_threshold_pit_test")

_OUT_DIR = os.path.join("output", "research")
_OUT_PATH = os.path.join(_OUT_DIR, "overlap_threshold_pit_test_1D.parquet")

# Bar-count grid: spans well below the current MIN_OVERLAP_BY_TF["1D"]=252
# floor up to well beyond it, so the resulting curve can show whether 252
# under- or over-shoots the real inflection point. ~365/252 calendar-day-
# per-bar ratio used to convert bar counts to a date-range window width
# (matches this project's own existing "252 trading days ~= 1 calendar
# year" convention elsewhere, e.g. config.py's MIN_OVERLAP_BY_TF comment).
_DEFAULT_GRID_BARS = [63, 126, 189, 252, 378, 504, 756, 1008, 1260]
_BARS_TO_CALENDAR_DAYS = 365.0 / 252.0

# Fixed OOS holdout length -- one full year, non-overlapping, immediately
# following the training window. A pair needs total real overlap >= L +
# this before it's even eligible for a given L (checked implicitly: if the
# OOS window runs past the universe's real end date, that fold/L cell is
# skipped).
_OOS_CALENDAR_DAYS = 365

# A pair must produce at least this many OOS trades before its Sharpe is
# treated as informative at all -- fewer than this and "held up" is scored
# False regardless of the Sharpe sign (too little evidence either way is
# not the same as evidence of holding up).
_MIN_OOS_TRADES = 3

# Same default lead_lag_scan.py's own CLI (--min-lift) already uses --
# reused, not re-derived, so "mechanical lead-lag" means the same thing
# here as it does everywhere else in this project.
_LEAD_LAG_MIN_LIFT = 0.05
_LEAD_LAG_MAX_LAG = Config.RESEARCH.LEAD_LAG_MAX_LAG


def _setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _fold_start_dates(universe_start: pd.Timestamp, universe_end: pd.Timestamp,
                       n_folds: int, max_l_bars: int) -> List[pd.Timestamp]:
    """Spread n_folds non-degenerate start points across the real analysis
    window, leaving enough room after each for the largest L plus the OOS
    window -- otherwise every fold would silently fail every L near the
    grid's upper end, exactly the kind of silent partial-coverage bug this
    project's own audits keep finding elsewhere.

    A single fold defaults to the LATEST usable start, not the earliest --
    caught live (2026-09-12) running the actual pilot: `determine_analysis_
    window`'s universe_start reflects the single earliest symbol anywhere in
    the merged universe (a handful of century-old tickers, e.g. XOM/KO back
    to 1925 per CLAUDE.md), so a fold anchored there screens a near-empty
    1926-era universe -- technically not wrong, but uninformative, and would
    have burned the entire single-fold pilot's compute on a degenerate
    result before this was caught. Recent history has far more real
    candidates and is what this study actually needs to say something about.
    """
    # +1 for the 1-day gap between train_end and test_start (test_start =
    # train_end + 1 day) -- omitting it caused a real off-by-one, caught live
    # 2026-09-12 running threshold_relevance_pit_test.py: a fold placed
    # exactly at the reserved boundary computed a test_end exactly 1 day past
    # the real universe end, silently skipping the only fold in a 1-fold
    # pilot (0 observations produced, no error).
    max_days_needed = int(max_l_bars * _BARS_TO_CALENDAR_DAYS) + 1 + _OOS_CALENDAR_DAYS
    latest_usable_start = universe_end - pd.Timedelta(days=max_days_needed)
    if latest_usable_start <= universe_start:
        return [universe_start]
    total_span = (latest_usable_start - universe_start).days
    if n_folds <= 1:
        return [latest_usable_start]
    return [
        universe_start + pd.Timedelta(days=int(total_span * i / (n_folds - 1)))
        for i in range(n_folds)
    ]


def _mechanical_lead_lag(pair_result, universe: Dict[str, pd.DataFrame],
                          train_start: pd.Timestamp, train_end: pd.Timestamp) -> Optional[bool]:
    """Lead-lag control per Ross's explicit ask. Returns None (not True/False)
    when there isn't enough training-window data to judge -- callers must
    treat None as "unknown", not as "no lead-lag", so a data-starved pair
    doesn't silently get pooled into the "clean" cohort."""
    sym_a, sym_b = pair_result.symbol_a, pair_result.symbol_b
    df_a = universe.get(sym_a)
    df_b = universe.get(sym_b)
    if df_a is None or df_b is None:
        return None
    win_a = df_a.loc[(df_a.index >= train_start) & (df_a.index <= train_end)]
    win_b = df_b.loc[(df_b.index >= train_start) & (df_b.index <= train_end)]
    if len(win_a) < 60 or len(win_b) < 60:
        return None
    ret_a = pd.Series(_gap_aware_returns(win_a), index=win_a.index)
    ret_b = pd.Series(_gap_aware_returns(win_b), index=win_b.index)
    scan = lagged_corr_scan(ret_a, ret_b, _LEAD_LAG_MAX_LAG)
    corr0, n0 = scan.get(0, (None, 0))
    k_star, c_star, n_star = best_lag(scan)
    if corr0 is None or c_star is None:
        return None
    return (abs(c_star) - abs(corr0)) >= _LEAD_LAG_MIN_LIFT


def run_pilot(grid_bars: List[int], n_folds: int, n_workers: int) -> pd.DataFrame:
    universe = load_universe_wrds_daily(columns=["close"])
    log.info(f"Universe: {len(universe)} symbols with daily data (WRDS-primary merged universe)")
    universe_start, universe_end = determine_analysis_window(universe)
    log.info(f"Analysis window: [{universe_start.date()}, {universe_end.date()}]")

    fold_starts = _fold_start_dates(universe_start, universe_end, n_folds, max(grid_bars))
    log.info(f"Folds: {[d.date() for d in fold_starts]}")
    log.info(f"Grid (bars): {grid_bars}")

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
            log.info(f"[{cell_i}/{n_cells}] fold={fold_start.date()} L={l_bars} bars "
                     f"(train=[{fold_start.date()},{train_end.date()}], "
                     f"test=[{test_start.date()},{test_end.date()}]): screening...")
            confirmed = screen_universe_at_cutoff(universe, fold_start, train_end, n_workers)
            log.info(f"  {len(confirmed)} pairs confirmed in {time.time()-t0:.1f}s, backtesting OOS...")

            for pair_result in confirmed:
                mech_lead_lag = _mechanical_lead_lag(pair_result, universe, fold_start, train_end)
                trades, metrics = backtest_pair_on_test_window(
                    pair_result, universe, fold_start, test_start, test_end
                )
                n_trades = metrics.get("n_trades", 0)
                sharpe = metrics.get("sharpe", np.nan)
                held_up = bool(n_trades >= _MIN_OOS_TRADES and np.isfinite(sharpe) and sharpe > 0)
                rows.append({
                    "fold_start": fold_start, "nominal_l_bars": l_bars,
                    "train_end": train_end, "test_start": test_start, "test_end": test_end,
                    "symbol_a": pair_result.symbol_a, "symbol_b": pair_result.symbol_b,
                    "actual_n_overlap": pair_result.n_overlap,
                    "mechanical_lead_lag": mech_lead_lag,
                    "oos_n_trades": n_trades, "oos_sharpe": sharpe, "held_up": held_up,
                })
            log.info(f"  cell complete in {time.time()-t0:.1f}s")

    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    """False-confirmation rate by actual-overlap bucket, split by lead-lag
    flag. Bucketed on ACTUAL overlap (not nominal L) since that's the real
    quantity MIN_OVERLAP_BY_TF gates on."""
    if df.empty:
        return df
    bucket_edges = sorted(set(_DEFAULT_GRID_BARS) | {int(df["actual_n_overlap"].max()) + 1})
    df = df.copy()
    df["overlap_bucket"] = pd.cut(df["actual_n_overlap"], bins=[0] + bucket_edges, right=False)
    df["lead_lag_cohort"] = df["mechanical_lead_lag"].map(
        {True: "mechanical_lead_lag", False: "clean", None: "unknown"}
    ).fillna("unknown")

    def _agg(g):
        return pd.Series({
            "n_pairs": len(g),
            "n_held_up": g["held_up"].sum(),
            "false_confirmation_rate": 1.0 - g["held_up"].mean(),
        })

    result = (
        df.groupby(["overlap_bucket", "lead_lag_cohort"], observed=True)
        .apply(_agg, include_groups=False)
        .reset_index()
    )
    # pandas' Interval dtype (from pd.cut) has no pyarrow parquet mapping --
    # found live, 2026-09-12, running the actual pilot: crashed on the very
    # last step after 32 minutes of real compute, with the expensive raw
    # observations already safely saved. String form is also more portable/
    # readable in the saved summary than a serialized Interval object.
    result["overlap_bucket"] = result["overlap_bucket"].astype(str)
    return result


def main():
    p = argparse.ArgumentParser(
        description="Empirical PIT-safe MIN_OVERLAP_BY_TF threshold study (1D, WRDS-primary)"
    )
    p.add_argument("--grid", type=int, nargs="+", default=_DEFAULT_GRID_BARS,
                    help="Overlap bar-count grid to test (default: a 9-point pilot grid)")
    p.add_argument("--folds", type=int, default=3,
                    help="Number of independent historical fold start-points (default 3 -- "
                         "a pilot scale; each (fold, L) cell costs roughly the same as one "
                         "full-scale full_universe_eg_confirmation.py run, so folds x len(grid) "
                         "full production-scale screens run sequentially)")
    p.add_argument("--n-workers", type=int, default=Config.RUNTIME.N_WORKERS)
    args = p.parse_args()

    _setup_logging()
    log.info("=== overlap_threshold_pit_test.py: empirical PIT-safe MIN_OVERLAP_BY_TF study ===")
    log.info(f"grid={args.grid} folds={args.folds} n_workers={args.n_workers} "
             f"-- estimated {len(args.grid) * args.folds} full production-scale PIT screens")

    os.makedirs(_OUT_DIR, exist_ok=True)
    t0 = time.time()
    df = run_pilot(args.grid, args.folds, args.n_workers)
    log.info(f"Pilot complete in {(time.time()-t0)/60:.1f} min, {len(df)} pair-cell observations")

    if df.empty:
        log.warning("No observations produced -- check fold/grid feasibility against the "
                     "real universe date range logged above")
        return

    df.to_parquet(_OUT_PATH, index=False)
    log.info(f"Saved raw observations -> {_OUT_PATH}")

    summary = summarize(df)
    summary_path = _OUT_PATH.replace(".parquet", "_summary.parquet")
    summary.to_parquet(summary_path, index=False)
    log.info(f"Saved summary -> {summary_path}")
    log.info("\n" + summary.to_string(index=False))


if __name__ == "__main__":
    main()
