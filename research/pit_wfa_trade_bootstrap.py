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

D10 / R5.8 (Ross 2026-10-12; fixed 2026-10-19): the bootstrap resampled days iid (no serial dependence), dropped
every all-zero draw (std 0 -> NaN -> np.nanpercentile; fold2_roll has 5 non-zero days), zero-filled only between the
first and last exit instead of over the fold's test window (R5.1), used numpy's ddof=0 std (production
portfolio_math.sharpe_from_daily_pnl uses ddof=1), and logged "resampling N trades" while resampling days. Now: the
daily P&L over the whole test window, zeros included; stationary block bootstrap (Politis & Romano 1994) with mean
block length by Politis & White (2004) automatic selection as corrected by Patton, Politis & White (2009)
(arch.bootstrap.optimal_block_length); every draw kept -- an all-zero draw has Sharpe 0 by definition (no P&L) and is
counted (n_degenerate_draws). debug/_verify_pit_wfa_bootstrap_d10.py

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


def _daily_pnl_series(all_trades: list, start=None, end=None) -> pd.Series:
    """Reproduces aggregate_portfolio's own daily-P&L construction exactly
    (backtest.py: sort by entry time, index by exit/entry time, resample to
    1D sums) as a standalone step, so the bootstrap below resamples this
    ALREADY-AGGREGATED array rather than raw trades."""
    sorted_trades = sorted(all_trades, key=lambda t: t.entry_time or pd.Timestamp.min)
    pnl_series = pd.Series(
        [t.pnl_net for t in sorted_trades],
        index=[t.exit_time or t.entry_time for t in sorted_trades],
    )
    import portfolio_math
    # business days (code review P1); start/end = the fold's test window so edge no-trade days are zeros (R5.1)
    return portfolio_math.daily_pnl_from_exits(pnl_series.index, pnl_series.to_numpy(), start=start, end=end)


def sharpe_of(daily: np.ndarray) -> float:
    """portfolio_math.sharpe_from_daily_pnl's formula (pandas std, ddof=1) on an array, without its min_days/NaN
    rule: a zero-variance draw returns 0.0 when it is all zeros (no P&L), NaN otherwise."""
    daily = np.asarray(daily, float)
    sd = daily.std(ddof=1) if len(daily) > 1 else 0.0
    if sd > 0:
        return float(daily.mean() / sd * np.sqrt(252))
    return 0.0 if not np.any(daily) else float("nan")


def politis_white_block_length(daily: np.ndarray) -> float:
    """Mean block length for the stationary bootstrap: Politis & White (2004) with the Patton, Politis & White (2009)
    correction, as implemented in arch.bootstrap.optimal_block_length; at least 1."""
    from arch.bootstrap import optimal_block_length
    daily = np.asarray(daily, float)
    if len(daily) < 10 or not np.any(daily - daily.mean()):
        return 1.0
    return float(max(1.0, optimal_block_length(daily)["stationary"].iloc[0]))


def stationary_bootstrap_sharpe(daily: np.ndarray, n_boot: int = 5000, rng: np.random.Generator = None,
                                block_length: float = None, return_draws: bool = False) -> dict:
    """Stationary block bootstrap (Politis & Romano 1994) of the daily P&L array, zeros included: each draw strings
    together blocks with uniform random starts and geometric lengths (mean = block_length), wrapping circularly.
    Every draw is kept; all-zero draws get Sharpe 0 and are counted."""
    rng = rng or np.random.default_rng(0)
    daily = np.asarray(daily, float)
    n = len(daily)
    L = float(block_length) if block_length else politis_white_block_length(daily)
    p = 1.0 / L
    sharpes = np.empty(n_boot)
    draws = [] if return_draws else None
    n_degenerate = 0
    for b in range(n_boot):
        idx = np.empty(n, dtype=int)
        idx[0] = rng.integers(n)
        new_block = rng.random(n) < p
        starts = rng.integers(0, n, size=n)
        for t in range(1, n):
            idx[t] = starts[t] if new_block[t] else (idx[t - 1] + 1) % n
        d = daily[idx]
        n_degenerate += not np.any(d)
        sharpes[b] = sharpe_of(d)
        if return_draws:
            draws.append(d)
    out = {"sharpes": sharpes, "block_length": L, "n_days": n, "n_nonzero_days": int(np.count_nonzero(daily)),
           "n_degenerate_draws": int(n_degenerate)}
    if return_draws:
        out["draws"] = draws
    return out


def bootstrap_portfolio_sharpe(all_trades: list, n_boot: int = 5000,
                                rng: np.random.Generator = None) -> np.ndarray:
    """SUPERSEDED by stationary_bootstrap_sharpe (D10, 2026-10-19): iid days, ddof=0, all-zero draws -> NaN. Kept only
    as the pre-D10 reference its own test (debug/_verify_pit_wfa_trade_bootstrap.py) pins; main() no longer calls it.
    Bootstraps the portfolio Sharpe by resampling the ALREADY-AGGREGATED
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
    sweep -- only the 2 folds with nonzero trades. Returns (trades, test_start, test_end)."""
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
    return all_trades, fold_dates["test_start"], fold_dates["test_end"]


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
        trades, test_start, test_end = get_fold_trades(universe, fold_spec, wfa_variant, start, end, n_workers=None
                                                       or __import__("config").Config.RUNTIME.N_WORKERS)
        if not trades:
            log.warning(f"[{wfa_variant}/{target_label}] no trades recovered -- skipping")
            continue
        original_stats = aggregate_portfolio(trades, [])
        log.info(f"[{wfa_variant}/{target_label}] recovered {len(trades)} trades, "
                 f"reproduced portfolio Sharpe={original_stats.get('sharpe_portfolio'):.4f}")

        daily = _daily_pnl_series(trades, start=test_start, end=test_end)
        r = stationary_bootstrap_sharpe(daily.to_numpy(), n_boot=5000, rng=np.random.default_rng(0))
        ci_low, ci_high = np.percentile(r["sharpes"], [2.5, 97.5])   # every draw kept (D10)
        log.info(f"[{wfa_variant}/{target_label}] stationary block bootstrap 95% CI (n_boot=5000, resampling "
                 f"{r['n_days']} daily P&L values over the test window, {r['n_nonzero_days']} non-zero, mean block "
                 f"length {r['block_length']:.2f} (Politis-White); {r['n_degenerate_draws']} all-zero draws kept as "
                 f"Sharpe 0): [{ci_low:.4f}, {ci_high:.4f}]; Sharpe of the window series {sharpe_of(daily):.4f}")
        results[f"{wfa_variant}/{target_label}"] = {
            "n_trades": len(trades),
            "point_estimate_sharpe": original_stats.get("sharpe_portfolio"),
            "sharpe_test_window_series": sharpe_of(daily),
            "ci_low": ci_low, "ci_high": ci_high,
            "method": "stationary block bootstrap (Politis-Romano 1994), block length Politis-White (2004)/PPW (2009)",
            "block_length": r["block_length"], "n_days": r["n_days"], "n_nonzero_days": r["n_nonzero_days"],
            "n_degenerate_draws": r["n_degenerate_draws"], "test_start": test_start, "test_end": test_end,
        }

    pd.DataFrame(results).T.to_parquet(_OUT_PATH)
    log.info(f"Saved -> {_OUT_PATH}")
    log.info("pit_wfa_trade_bootstrap.py complete")


if __name__ == "__main__":
    main()
