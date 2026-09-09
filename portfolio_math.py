"""
portfolio_math.py — canonical portfolio-level daily P&L / Sharpe utilities.

Single source of truth for pooling trade-level P&L to daily frequency. Every
calendar day between the first and last exit MUST get a row (0.0 if no trade
exited that day) via resample("1D").sum() — NOT groupby(exit_date), which
silently drops zero-P&L calendar days, shrinks N, and inflates Sharpe.

This exact bug (BUG-D62, portfolio_sim.py, 2026-07-13; BUG-D64, sensitivity.py,
same day — an independent recurrence of D62 in a second file) was found
recurring in FOUR more places during the 2026-07-20 Grand Sweep:
deflated_sharpe.py's _daily_pnl_stats() (feeds the paper's headline DSR),
stats.py's run_permutation_test() (feeds the S6 permutation p-value),
cvar.py's daily_pnl_series() (feeds VaR/CVaR), and fresh_holdout_compare.py's
_pooled_sharpe() (whose own docstring incorrectly claimed to already match
aggregate_portfolio()'s convention). This module exists so the same bug
cannot recur an eighth time — every one of the above now calls this module
instead of reimplementing the pooling inline.

Matches backtest.py's aggregate_portfolio() convention exactly.

Two per-pair WIDE-panel call sites (stats.py's _build_daily_pnl(),
research/portfolio_effective_bets.py) and one trade-sequence-autocorrelation
site (research/return_smoothing_audit.py) were deliberately NOT migrated here
— they answer a structurally different question (cross-pair correlation /
lag structure, not a single pooled portfolio Sharpe) and need their own
dedicated review before deciding whether calendar zero-fill is even the
right convention for them. See Development.md, 2026-07-20 Grand Sweep entry.
"""
import numpy as np
import pandas as pd


def daily_pnl_from_exits(exit_times, pnl_values) -> pd.Series:
    """Zero-filled daily P&L series from trade-level exit times + P&L values."""
    exit_times = list(exit_times)
    if len(exit_times) == 0:
        return pd.Series(dtype=float)
    s = pd.Series(list(pnl_values), index=pd.DatetimeIndex(pd.to_datetime(exit_times))).sort_index()
    return s.resample("1D").sum()


def daily_pnl_from_trades(trades: pd.DataFrame, pnl_col: str = "pnl_net") -> pd.Series:
    """Same as daily_pnl_from_exits, reading a trades DataFrame with an
    'exit_time' column and pnl_col (defaults to 'pnl_net')."""
    if trades is None or len(trades) == 0:
        return pd.Series(dtype=float)
    return daily_pnl_from_exits(trades["exit_time"], trades[pnl_col])


def sharpe_from_daily_pnl(daily_pnl: pd.Series, min_days: int = 5, ann_factor: float = 252.0) -> float:
    """Annualized Sharpe from an ALREADY daily-frequency (zero-filled) P&L series."""
    if daily_pnl is None or len(daily_pnl) < min_days or daily_pnl.std() == 0:
        return float("nan")
    return float(daily_pnl.mean() / daily_pnl.std() * np.sqrt(ann_factor))


def sharpe_from_trades(trades: pd.DataFrame, pnl_col: str = "pnl_net", min_days: int = 5) -> float:
    """Convenience: zero-fill + annualized Sharpe in one call, matching
    aggregate_portfolio()'s exact convention."""
    return sharpe_from_daily_pnl(daily_pnl_from_trades(trades, pnl_col), min_days=min_days)


# ---------------------------------------------------------------------------
# Sortino, rolling Sharpe, Calmar, M2 (added 2026-09-07, Ross's queued risk-
# metrics item). All take an ALREADY daily-frequency, zero-filled P&L series
# (daily_pnl_from_trades/daily_pnl_from_exits above) as their primary input,
# matching this module's own single-source-of-truth convention -- no metric
# here re-derives its own daily pooling.
# ---------------------------------------------------------------------------

def downside_deviation(daily_pnl: pd.Series, mar: float = 0.0) -> float:
    """Semi-deviation below a minimum acceptable return (MAR, default 0 -- matches this
    project's own zero-risk-free-rate convention used throughout options.py/backtest.py).
    Standard Sortino-ratio denominator: sqrt(mean(min(r - mar, 0)^2)), NOT std() of only the
    negative observations -- that would silently drop every zero/positive day from the sample
    size, understating N the same way the project's own daily-zero-fill discipline (this
    module's whole reason for existing) already guards against for Sharpe."""
    if daily_pnl is None or len(daily_pnl) == 0:
        return float("nan")
    downside = np.minimum(daily_pnl.to_numpy() - mar, 0.0)
    return float(np.sqrt(np.mean(downside ** 2)))


def sortino_from_daily_pnl(daily_pnl: pd.Series, min_days: int = 5, ann_factor: float = 252.0,
                             mar: float = 0.0) -> float:
    """Annualized Sortino ratio from an already-daily, zero-filled P&L series -- same shape and
    guard convention as sharpe_from_daily_pnl above, substituting downside_deviation for std()."""
    if daily_pnl is None or len(daily_pnl) < min_days:
        return float("nan")
    dd = downside_deviation(daily_pnl, mar=mar)
    if dd == 0 or not np.isfinite(dd):
        return float("nan")
    return float((daily_pnl.mean() - mar) / dd * np.sqrt(ann_factor))


def sortino_from_trades(trades: pd.DataFrame, pnl_col: str = "pnl_net", min_days: int = 5,
                          mar: float = 0.0) -> float:
    """Convenience: zero-fill + annualized Sortino in one call, matching
    sharpe_from_trades()'s own call shape."""
    return sortino_from_daily_pnl(daily_pnl_from_trades(trades, pnl_col), min_days=min_days, mar=mar)


def rolling_sharpe(daily_pnl: pd.Series, window: int = 60, min_periods: int = None,
                     ann_factor: float = 252.0) -> pd.Series:
    """Rolling annualized Sharpe over a trailing window of daily P&L -- a time series (not a
    single number), for tracking whether a strategy's risk-adjusted edge is stable or decaying
    over its own history. min_periods defaults to the full window (no partial-window Sharpe
    values at the start of the series, which would be noisy low-N estimates dressed up as real
    numbers) -- pass an explicit smaller value only if that's genuinely wanted."""
    if daily_pnl is None or len(daily_pnl) == 0:
        return pd.Series(dtype=float)
    min_periods = window if min_periods is None else min_periods
    roll_mean = daily_pnl.rolling(window, min_periods=min_periods).mean()
    roll_std = daily_pnl.rolling(window, min_periods=min_periods).std()
    return (roll_mean / roll_std * np.sqrt(ann_factor)).replace([np.inf, -np.inf], np.nan)


def calmar_from_daily_pnl(daily_pnl: pd.Series, starting_capital: float, min_days: int = 5) -> float:
    """Standard Calmar ratio = annualized return / max drawdown (%), generalizing
    portfolio_sim.py's calmar_from_replay() to work off any already-daily P&L series rather
    than only a portfolio_sim replay result dict -- same formula, same BUG-D62/D64 daily-
    resample basis, deliberately NOT backtest.py compute_metrics()'s non-standard, non-
    annualized total_pnl/max_dd 'calmar' field. Requires starting_capital explicitly (Calmar is
    fundamentally a RETURN-space metric; this module never silently assumes a capital base)."""
    if daily_pnl is None or len(daily_pnl) < min_days or starting_capital <= 0:
        return float("nan")
    equity = starting_capital + daily_pnl.cumsum()
    total_return = float(equity.iloc[-1] / starting_capital - 1.0)
    n_years = len(daily_pnl) / 252.0
    if n_years <= 0:
        return float("nan")
    base = 1.0 + total_return
    annualized_return = (base ** (1.0 / n_years) - 1.0) if base > 0 else float("nan")
    running_max = equity.cummax()
    max_dd_pct = float(((running_max - equity) / running_max).max())
    if not np.isfinite(annualized_return) or not np.isfinite(max_dd_pct) or max_dd_pct <= 0:
        return float("nan")
    return annualized_return / max_dd_pct


def m2_ratio(daily_pnl: pd.Series, benchmark_daily_returns: pd.Series, starting_capital: float,
              min_days: int = 5, ann_factor: float = 252.0) -> float:
    """Modigliani-Modigliani (M2) risk-adjusted performance measure: the strategy's Sharpe
    ratio rescaled to the BENCHMARK's own volatility, then expressed as an annualized return --
    directly comparable to the benchmark's own annualized return, unlike a bare Sharpe ratio
    (which has no return units at all). M2 = Sharpe_strategy * sigma_benchmark_annualized (zero
    risk-free rate, matching this project's convention throughout options.py/backtest.py).
    Requires starting_capital to convert the strategy's dollar P&L into the return space M2 is
    defined in."""
    if daily_pnl is None or len(daily_pnl) < min_days or starting_capital <= 0:
        return float("nan")
    if benchmark_daily_returns is None or len(benchmark_daily_returns) < min_days:
        return float("nan")
    strategy_returns = daily_pnl / starting_capital
    sharpe = sharpe_from_daily_pnl(strategy_returns, min_days=min_days, ann_factor=ann_factor)
    if not np.isfinite(sharpe):
        return float("nan")
    benchmark_vol_annualized = float(benchmark_daily_returns.std() * np.sqrt(ann_factor))
    return float(sharpe * benchmark_vol_annualized)
