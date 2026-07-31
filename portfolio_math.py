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
