"""
research/beta_weighted_portfolio.py -- Phase 3 of the new backlog (Ross: "for the beta weighting
let's use SPY and compare both hedge and report only").

Pairs trading is theoretically market-neutral (long one leg, short the other), but the two legs'
own market betas are never actually equal in practice -- a pair confirmed on cointegration alone
can still carry real, unmeasured net market exposure if leg A's beta and leg B's beta differ.
This measures that exposure directly against SPY (WRDS total-return-adjusted, this project's
priority data source) and builds two comparison arms:

  - REPORT-ONLY: measure and report the portfolio's net dollar beta exposure over time, as a
    diagnostic -- no positions change.
  - HEDGE: each day, take an offsetting SPY position sized to bring net beta exposure to zero,
    and recompute the portfolio's daily P&L (original + hedge) through this project's own
    canonical portfolio_math.py metrics -- does actually neutralizing the exposure improve
    risk-adjusted return, or is it a net cost (the standard, unavoidable hedging tradeoff
    options.py's own protective-overlay work already found for pair-level put/call hedges)?

Per-leg beta is a rolling, CAUSAL regression beta (cov(asset, SPY) / var(SPY) over a trailing
window, ending at/before the position's entry date -- never using data from after entry), held
constant for that trade's holding period -- a reasonable approximation; re-estimating beta
continuously WITHIN a single trade's holding period is a refinement flagged for later, not
essential to answer "does beta-hedging help."

Verified against synthetic ground truth first: debug/_verify_beta_weighted_portfolio.py.

Usage:
    python research/beta_weighted_portfolio.py
"""
import logging
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from options import load_price_series
from portfolio_math import daily_pnl_from_trades, sharpe_from_daily_pnl, sortino_from_daily_pnl, \
    calmar_from_daily_pnl, rolling_sharpe

log = logging.getLogger("beta_weighted_portfolio")

BETA_WINDOW = 63  # ~1 trading quarter, standard convention (matches options.py's own vol-window scale)
STARTING_CAPITAL = 100_000  # matches this project's own portfolio_sim.py/pit_wfa_wrds_daily.py convention
_SPY_WRDS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "output", "cache", "wrds", "SPY_1D.parquet")


def _setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")


def load_spy_returns() -> pd.Series:
    """WRDS total-return-adjusted SPY daily log returns -- this project's priority data source
    (CLAUDE.md: 'WRDS takes complete priority over other providers of data')."""
    df = pd.read_parquet(_SPY_WRDS_PATH)
    close = df["close_total_return"].dropna()
    close.index = pd.to_datetime(close.index)
    return np.log(close).diff().dropna()


def rolling_beta(asset_returns: pd.Series, market_returns: pd.Series, window: int = BETA_WINDOW) -> pd.Series:
    """Causal rolling beta = cov(asset, market) / var(market) over a trailing window -- a
    pandas .rolling().cov()/.rolling().var() pair, never a lookahead: the value at date t uses
    only returns up to and including t."""
    aligned = pd.DataFrame({"asset": asset_returns, "market": market_returns}).dropna()
    cov = aligned["asset"].rolling(window).cov(aligned["market"])
    var = aligned["market"].rolling(window).var()
    beta = cov / var
    return beta.replace([np.inf, -np.inf], np.nan)


def value_at_date(series: pd.Series, date) -> float:
    """Last available value (beta OR price -- generic, reused for both) AT OR BEFORE `date` --
    causal lookup, same 'pad, not nearest' convention as portfolio_sim.py's get_price_at()/
    get_spread_at() (a lookahead risk otherwise)."""
    if series is None or len(series) == 0:
        return np.nan
    idx = series.index.get_indexer([pd.Timestamp(date)], method="pad")[0]
    return float(series.iloc[idx]) if idx >= 0 else np.nan


def trade_net_dollar_beta_exposure(symbol_a: str, symbol_b: str, entry_time, price_a: float,
                                     price_b: float, n_shares_a: float, n_shares_b: float, side: str,
                                     beta_a_series: pd.Series, beta_b_series: pd.Series) -> float:
    """Net dollar beta exposure at trade entry: (signed dollar notional of leg A * its beta) +
    (signed dollar notional of leg B * its beta). side='long' means leg A is bought (positive
    notional) and leg B is sold (negative notional) to hedge the spread; side='short' is the
    reverse -- same sign convention backtest.py's own Trade.side already uses throughout this
    project. Returns NaN (not a fabricated 0) when either leg's beta isn't estimable yet."""
    beta_a = value_at_date(beta_a_series, entry_time)
    beta_b = value_at_date(beta_b_series, entry_time)
    if not np.isfinite(beta_a) or not np.isfinite(beta_b):
        return np.nan
    sign = 1.0 if side == "long" else -1.0
    notional_a = sign * n_shares_a * price_a
    notional_b = -sign * n_shares_b * price_b
    return float(notional_a * beta_a + notional_b * beta_b)


def build_daily_net_exposure(trades: pd.DataFrame) -> pd.Series:
    """Sums each open trade's (constant-during-the-trade) net_dollar_beta_exposure across every
    calendar day the trade is open, producing a single portfolio-level daily exposure series --
    an event-driven interval sum, not a naive re-loop per day (would be the same O(n_trades *
    n_days) anti-pattern class already fixed elsewhere in this project at real scale; this uses
    a difference-array technique: +exposure at entry, -exposure the day after exit, then a
    cumulative sum, giving the exact same result in O(n_trades + n_days))."""
    valid = trades.dropna(subset=["net_dollar_beta_exposure"])
    if len(valid) == 0:
        return pd.Series(dtype=float)
    # Real bug found live (2026-09-07): entry/exit times carry an intraday component for
    # sub-daily timeframes (e.g. "2023-10-02 14:00:00" for a 1h trade). Without .normalize()
    # here, pd.date_range's every subsequent day preserves that SAME intraday offset, which
    # never matches the .normalize()'d (midnight) lookups below -> KeyError on every real
    # trades file. Normalize both endpoints so the whole daily index is midnight-aligned.
    all_days = pd.date_range(valid["entry_time"].min().normalize(),
                              valid["exit_time"].max().normalize(), freq="D")
    delta = pd.Series(0.0, index=all_days)
    for _, t in valid.iterrows():
        delta.loc[t["entry_time"].normalize()] += t["net_dollar_beta_exposure"]
        exit_next_day = t["exit_time"].normalize() + pd.Timedelta(days=1)
        if exit_next_day in delta.index:
            delta.loc[exit_next_day] -= t["net_dollar_beta_exposure"]
    return delta.cumsum()


def hedge_overlay_daily_pnl(daily_net_exposure: pd.Series, spy_returns: pd.Series) -> pd.Series:
    """Daily P&L of an offsetting SPY position sized to bring net beta exposure to zero each
    day: hedge_notional(t) = -daily_net_exposure(t), hedge_pnl(t) = hedge_notional(t) *
    spy_return(t) -- realized the SAME day the exposure is measured (a same-day hedge-and-mark
    convention; a T+1 lag would be a real, disclosed refinement, not built in this first pass)."""
    aligned_spy = spy_returns.reindex(daily_net_exposure.index).fillna(0.0)
    hedge_notional = -daily_net_exposure
    return hedge_notional * aligned_spy


def main():
    _setup_logging()
    log.info("=== beta_weighted_portfolio.py: net market-beta exposure vs. SPY, report-only "
              "vs. hedge comparison arms ===")

    trades_path = "output/backtest/baseline_trades_layer1.parquet"
    if not os.path.exists(trades_path):
        log.warning(f"No trades found at {trades_path} -- run backtest.py first.")
        return
    trades = pd.read_parquet(trades_path)
    trades = trades[trades["hedge_method"] == "ols"].copy()
    trades["entry_time"] = pd.to_datetime(trades["entry_time"])
    trades["exit_time"] = pd.to_datetime(trades["exit_time"])
    log.info(f"{len(trades)} OLS trades loaded.")

    spy_returns = load_spy_returns()
    price_cache = {}
    beta_cache = {}

    def get_beta_series(sym):
        if sym not in beta_cache:
            close = load_price_series(sym)
            price_cache[sym] = close
            if close is None:
                beta_cache[sym] = None
            else:
                asset_returns = np.log(close).diff()
                beta_cache[sym] = rolling_beta(asset_returns, spy_returns)
        return beta_cache[sym]

    exposures = []
    for _, t in trades.iterrows():
        beta_a_series = get_beta_series(t["symbol_a"])
        beta_b_series = get_beta_series(t["symbol_b"])
        price_a_series = price_cache.get(t["symbol_a"])
        price_b_series = price_cache.get(t["symbol_b"])
        if beta_a_series is None or beta_b_series is None or price_a_series is None or price_b_series is None:
            exposures.append(np.nan)
            continue
        p_a = value_at_date(price_a_series, t["entry_time"])
        p_b = value_at_date(price_b_series, t["entry_time"])
        exposures.append(trade_net_dollar_beta_exposure(
            t["symbol_a"], t["symbol_b"], t["entry_time"], p_a, p_b,
            t["n_shares_a"], t["n_shares_b"], t["side"], beta_a_series, beta_b_series))
    trades["net_dollar_beta_exposure"] = exposures
    n_valid = trades["net_dollar_beta_exposure"].notna().sum()
    log.info(f"{n_valid}/{len(trades)} trades have a computable net beta exposure "
             f"(both legs' price history + {BETA_WINDOW}d beta estimate available).")

    daily_exposure = build_daily_net_exposure(trades)
    pct_of_capital = daily_exposure / STARTING_CAPITAL
    log.info(f"REPORT-ONLY: net beta exposure as %% of ${STARTING_CAPITAL:,.0f} capital -- "
             f"mean={pct_of_capital.mean():.4f}, std={pct_of_capital.std():.4f}, "
             f"max_abs={pct_of_capital.abs().max():.4f}")

    original_daily_pnl = daily_pnl_from_trades(trades)
    original_daily_pnl = original_daily_pnl.reindex(daily_exposure.index).fillna(0.0)
    hedge_pnl = hedge_overlay_daily_pnl(daily_exposure, spy_returns)
    hedged_daily_pnl = original_daily_pnl + hedge_pnl

    for label, pnl in [("UNHEDGED", original_daily_pnl), ("HEDGED", hedged_daily_pnl)]:
        sharpe = sharpe_from_daily_pnl(pnl)
        sortino = sortino_from_daily_pnl(pnl)
        calmar = calmar_from_daily_pnl(pnl, STARTING_CAPITAL)
        log.info(f"  {label}: Sharpe={sharpe:.4f}  Sortino={sortino:.4f}  Calmar={calmar:.4f}  "
                 f"total_pnl=${pnl.sum():,.2f}")

    os.makedirs("output/research", exist_ok=True)
    out = pd.DataFrame({"date": daily_exposure.index, "net_beta_exposure": daily_exposure.to_numpy(),
                          "unhedged_daily_pnl": original_daily_pnl.to_numpy(),
                          "hedge_pnl": hedge_pnl.reindex(daily_exposure.index).fillna(0.0).to_numpy(),
                          "hedged_daily_pnl": hedged_daily_pnl.to_numpy()})
    out.to_parquet("output/research/beta_weighted_portfolio.parquet")
    log.info("Saved -> output/research/beta_weighted_portfolio.parquet")
    log.info("beta_weighted_portfolio.py complete")


if __name__ == "__main__":
    main()
