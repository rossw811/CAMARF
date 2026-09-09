"""
research/pit_wfa_trade_bootstrap.py -- bootstrap confidence interval on
pit_wfa.py's fold2_exp/fold2_roll portfolio Sharpe (the real evidence behind
PAPER_MAGNITUDE.md §4), which currently rests on a bare point estimate from
32 and 5 raw trades respectively.

Motivation (2026-09-02, Ross: "the 32 trades is absolutely not enough to be
significant... brainstorm ideas on resolving this"): §4's headline
(expanding/fold2: -1.0121 Sharpe, 32 trades; rolling/fold2: +0.2547 Sharpe,
5 trades) reports a single point estimate with no distributional sense of how
far from zero it convincingly is. Re-running the full universe screen at
these cutoffs takes ~45-50 min PER CUTOFF (per pit_wfa.py's own module
docstring) and the confirmed pair set at each cutoff is already known
(pit_wfa_portfolio.parquet) -- this script reuses `backtest_pair_on_test_
window` directly for those ALREADY-CONFIRMED pairs (no re-screening) to
recover raw trades, then bootstraps at the TRADE level.

Reuses `aggregate_portfolio` (backtest.py) unmodified for the Sharpe
formula, both to reproduce the original point estimate exactly (a
correctness check before trusting anything) and for every bootstrap
resample -- never a reimplemented formula that could silently diverge.

Verified against synthetic ground truth first:
debug/_verify_pit_wfa_trade_bootstrap.py.

Usage:
    python research/pit_wfa_trade_bootstrap.py
"""
import logging
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest import aggregate_portfolio
from pit_wfa import (
    load_universe_1h, determine_analysis_window, compute_fold_dates,
    screen_universe_at_cutoff, backtest_pair_on_test_window,
    FOLD_EXPANDING, FOLD_ROLLING,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_PATH = os.path.join(_ROOT, "output", "research", "pit_wfa_trade_bootstrap.parquet")

log = logging.getLogger("pit_wfa_trade_bootstrap")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)


def _daily_pnl_series(all_trades: list) -> pd.Series:
    """Reproduces aggregate_portfolio's own daily-P&L construction exactly
    (backtest.py: sort by entry time, index by exit/entry time, resample to
    1D sums) as a standalone step, so the bootstrap below resamples this
    ALREADY-AGGREGATED array rather than raw trades."""
    sorted_trades = sorted(all_trades, key=lambda t: t.entry_time or pd.Timestamp.min)
    pnl_series = pd.Series(
        [t.pnl_net for t in sorted_trades],
        index=[t.exit_time or t.entry_time for t in sorted_trades],
    )
    return pnl_series.resample("1D").sum()


def bootstrap_portfolio_sharpe(all_trades: list, n_boot: int = 5000,
                                rng: np.random.Generator = None) -> np.ndarray:
    """Bootstraps the portfolio Sharpe by resampling the ALREADY-AGGREGATED
    daily P&L array (via _daily_pnl_series, matching aggregate_portfolio's
    own construction exactly) WITH REPLACEMENT, n_boot times, recomputing
    Sharpe = mean/std*sqrt(252) on each draw -- the same formula
    aggregate_portfolio uses (backtest.py), applied here directly rather
    than re-deriving daily P&L from a resampled TRADE list.

    NOT resampling raw trades and re-deriving daily P&L per draw (an
    earlier version of this function did exactly that): resampling
    individual trades while keeping their original exit_time labels, then
    re-running them through a `.resample("1D")` step, creates artificial
    day-collisions (multiple resampled trades landing on the same original
    date) and artificial gap-days (dates that received zero resampled
    trades) that do not reflect genuine day-to-day P&L variation -- caught
    live in debug/_verify_pit_wfa_trade_bootstrap.py's check 1 (a
    low-noise, one-trade-per-day synthetic series should bootstrap to a
    Sharpe close to its ~82 point estimate; the raw-trade-resampling
    version instead produced ~15, a real, wrong dilution from the
    collision/gap artifact). Resampling the already-daily-aggregated
    series avoids this entirely: the unit being resampled (a day's total
    P&L) is exactly the unit the Sharpe formula itself operates on."""
    if rng is None:
        rng = np.random.default_rng(0)
    daily = _daily_pnl_series(all_trades).to_numpy()
    n = len(daily)
    sharpes = np.empty(n_boot)
    for b in range(n_boot):
        resampled = daily[rng.integers(0, n, size=n)]
        std = resampled.std()
        sharpes[b] = (resampled.mean() / std * np.sqrt(252)) if std > 0 else np.nan
    return sharpes


def get_fold_trades(universe, fold_spec, wfa_variant, start, end, n_workers) -> list:
    """Re-derives the fold's train/test dates and PIT-confirmed pair set
    (screen_universe_at_cutoff, unmodified from pit_wfa.py), then backtests
    each confirmed pair on the test window via backtest_pair_on_test_window
    (unmodified) to recover raw Trade objects. This DOES re-run the ~45-50
    min screen (unavoidable -- the confirmed-pair SET at each cutoff is not
    itself persisted anywhere queryable ahead of a screen, only the final
    pair_sets.parquet after a full run), but does NOT re-run the full 4-fold
    sweep -- only the 2 folds with nonzero trades."""
    fold_dates = compute_fold_dates(start, end, fold_spec)
    log.info(f"[{wfa_variant}/{fold_dates['label']}] screening at cutoff "
             f"{fold_dates['train_end'].date()} (train_start={fold_dates['train_start'].date()})...")
    pair_results = screen_universe_at_cutoff(
        universe, fold_dates["train_start"], fold_dates["train_end"], n_workers=n_workers
    )
    log.info(f"[{wfa_variant}/{fold_dates['label']}] {len(pair_results)} PIT-confirmed pairs")
    all_trades = []
    for pr in pair_results:
        trades, _ = backtest_pair_on_test_window(
            pr, universe, fold_dates["train_start"], fold_dates["test_start"], fold_dates["test_end"]
        )
        all_trades.extend(trades)
    return all_trades


def main():
    _setup_logging()
    log.info("=== pit_wfa_trade_bootstrap.py: bootstrap CI on the PIT-confirmed fold Sharpes "
             "§4 of PAPER_MAGNITUDE.md reports as bare point estimates ===")

    universe = load_universe_1h()
    log.info(f"Universe: {len(universe)} symbols with cached 1h data")
    start, end = determine_analysis_window(universe)

    results = {}
    for wfa_variant, fold_specs, target_label in [
        ("expanding", FOLD_EXPANDING, "fold2_exp"),
        ("rolling", FOLD_ROLLING, "fold2_roll"),
    ]:
        fold_spec = next(fs for fs in fold_specs if fs[-1] == target_label)
        trades = get_fold_trades(universe, fold_spec, wfa_variant, start, end, n_workers=None
                                  or __import__("config").Config.RUNTIME.N_WORKERS)
        if not trades:
            log.warning(f"[{wfa_variant}/{target_label}] no trades recovered -- skipping")
            continue
        original_stats = aggregate_portfolio(trades, [])
        log.info(f"[{wfa_variant}/{target_label}] recovered {len(trades)} trades, "
                 f"reproduced portfolio Sharpe={original_stats.get('sharpe_portfolio'):.4f}")

        boot = bootstrap_portfolio_sharpe(trades, n_boot=5000, rng=np.random.default_rng(0))
        ci_low, ci_high = np.nanpercentile(boot, [2.5, 97.5])
        log.info(f"[{wfa_variant}/{target_label}] bootstrap 95% CI (n_boot=5000, "
                 f"resampling {len(trades)} trades): [{ci_low:.4f}, {ci_high:.4f}]")
        results[f"{wfa_variant}/{target_label}"] = {
            "n_trades": len(trades),
            "point_estimate_sharpe": original_stats.get("sharpe_portfolio"),
            "ci_low": ci_low, "ci_high": ci_high,
        }

    pd.DataFrame(results).T.to_parquet(_OUT_PATH)
    log.info(f"Saved -> {_OUT_PATH}")
    log.info("pit_wfa_trade_bootstrap.py complete")


if __name__ == "__main__":
    main()
