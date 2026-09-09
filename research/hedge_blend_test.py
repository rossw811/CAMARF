"""
research/hedge_blend_test.py -- Phase 4 (part B) of the discovery-event research program (Ross:
"blend correlated-pair trades with uncorrelated-asset hedging", tested with/without comparison
arms to find optimal parameters, not a single fixed design).

Blends this project's real production pair-trading strategy (baseline_trades_layer1.parquet,
daily-resampled returns, the SAME convention as backtest.py:aggregate_portfolio()) with an
uncorrelated-asset basket's returns (reusing research/diversification_basket_test.py's own
basket-construction logic, so "uncorrelated" means the same thing in both halves of Phase 4):

    blended_daily_return = w * pair_strategy_return + (1 - w) * hedge_basket_return

...swept across w in {1.0, 0.9, 0.8, 0.7, 0.6, 0.5} -- w=1.0 IS the with/without baseline (pure
pair strategy, no hedge blend at all), so every other w is a genuine comparison arm against it,
not an arbitrary standalone number.

Tests the real question directly: does allocating part of the portfolio to a currently-
uncorrelated asset basket improve the pair-trading strategy's realized Sharpe/volatility, or does
it just dilute return for no real risk benefit? Reported honestly either way.

Verified against synthetic ground truth first: debug/_verify_hedge_blend_test.py.

Usage:
    python research/hedge_blend_test.py
"""
import logging
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

log = logging.getLogger("hedge_blend_test")

_ROOT = os.path.dirname(os.path.abspath(__file__))
_TRADES_PATH = os.path.join(os.path.dirname(_ROOT), "output", "backtest", "baseline_trades_layer1.parquet")
_TRANSITIONS_PATH = os.path.join(os.path.dirname(_ROOT), "output", "research", "correlation_transitions.parquet")
_OUT_PATH = os.path.join(os.path.dirname(_ROOT), "output", "research", "hedge_blend_test.parquet")

BLEND_WEIGHTS = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5]  # weight on the pair-trading strategy
STARTING_CAPITAL = 100_000  # matches this project's own portfolio_sim.py/pit_wfa_wrds_daily.py convention
BASKET_SIZE = 20
_RNG_SEED = 42


def _setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")


def pair_strategy_daily_returns(trades: pd.DataFrame, starting_capital: float) -> pd.Series:
    """Daily-resampled pair-trading strategy RETURNS (not dollar P&L), matching
    backtest.py:aggregate_portfolio()'s own daily-bucketing convention but converted to a
    percentage return series (dollar P&L / starting_capital) so it can be blended with the
    hedge basket's own percentage-return series on a like-for-like basis."""
    pnl = pd.Series(trades["pnl_net"].values, index=pd.to_datetime(trades["exit_time"].fillna(trades["entry_time"])))
    daily_pnl = pnl.sort_index().resample("1D").sum()
    return daily_pnl / starting_capital


def basket_daily_returns(close_by_symbol: dict, symbols: list) -> pd.Series:
    """Equal-weight daily return series for a basket of symbols -- same construction as
    diversification_basket_test.py's own basket returns, reused here for consistency."""
    price_df = pd.concat({s: close_by_symbol[s] for s in symbols if s in close_by_symbol}, axis=1)
    plain = price_df.astype("float64")
    returns = np.log(plain.where(plain > 0)).diff()
    return returns.mean(axis=1)


def blend_and_evaluate(pair_returns: pd.Series, hedge_returns: pd.Series, weight: float) -> dict:
    """Blends the two return series on their common calendar-day index (days only the pair
    strategy traded get a real hedge_returns value via reindex+fillna(0) for the hedge leg --
    the hedge basket itself has a return every trading day regardless of whether the pair
    strategy happened to trade that day, so its own return series is reindexed onto the pair
    series' dates, not the other way around, to avoid manufacturing hedge-only days with no
    pair activity)."""
    aligned_hedge = hedge_returns.reindex(pair_returns.index).fillna(0.0)
    blended = weight * pair_returns.fillna(0.0) + (1 - weight) * aligned_hedge
    if len(blended) < 5 or blended.std() == 0:
        return {"weight": weight, "sharpe": np.nan, "volatility": np.nan, "mean_daily_return": np.nan}
    sharpe = float(blended.mean() / blended.std() * np.sqrt(252))
    return {"weight": weight, "sharpe": sharpe, "volatility": float(blended.std()),
            "mean_daily_return": float(blended.mean())}


def main():
    _setup_logging()
    log.info("=== hedge_blend_test.py: does blending the real pair-trading strategy with an "
              "uncorrelated-asset basket improve Sharpe, swept across blend weights? ===")
    import universe_loader
    from research.diversification_basket_test import latest_state_symbols

    trades = pd.read_parquet(_TRADES_PATH)
    pair_returns = pair_strategy_daily_returns(trades, STARTING_CAPITAL)
    log.info(f"Pair-trading strategy: {len(trades)} trades, {len(pair_returns)} daily-return "
              f"observations, {pair_returns.index.min().date()} to {pair_returns.index.max().date()}.")

    transitions = pd.read_parquet(_TRANSITIONS_PATH)
    not_coint_symbols = latest_state_symbols(transitions)["not_coint"]
    universe = universe_loader.load_full_universe(
        tf_label="1D", include_yfinance=True, include_wrds=True, include_binance=True, include_ibkr=True,
        columns=["close"],
    )
    close_by_symbol = {s: universe[s]["close"] for s in not_coint_symbols
                        if s in universe and universe[s] is not None and not universe[s].empty}
    log.info(f"Real price data available for {len(close_by_symbol)}/{len(not_coint_symbols)} "
             f"currently-decoupled pool symbols.")

    rng = np.random.default_rng(_RNG_SEED)
    available = [s for s in not_coint_symbols if s in close_by_symbol]
    chosen = list(rng.choice(available, size=min(BASKET_SIZE, len(available)), replace=False))
    hedge_returns = basket_daily_returns(close_by_symbol, chosen)
    log.info(f"Hedge basket: {len(chosen)} currently-uncorrelated symbols.")

    rows = []
    for w in BLEND_WEIGHTS:
        r = blend_and_evaluate(pair_returns, hedge_returns, w)
        rows.append(r)
        label = "pair-only baseline" if w == 1.0 else f"blended {w:.0%}/{1-w:.0%}"
        log.info(f"  weight={w:.1f} ({label}): Sharpe={r['sharpe']:.4f}, "
                  f"volatility={r['volatility']:.6f}, mean_daily_return={r['mean_daily_return']:.6f}")

    out = pd.DataFrame(rows)
    out.to_parquet(_OUT_PATH)
    log.info(f"Saved -> {_OUT_PATH}")
    log.info("hedge_blend_test.py complete")


if __name__ == "__main__":
    main()
