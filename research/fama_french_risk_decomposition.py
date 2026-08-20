"""
research/fama_french_risk_decomposition.py -- Thread F Part A of the WRDS
supplementary data integration plan
(C:\\Users\\RossW\\.claude\\plans\\ancient-mixing-feather.md).

QUESTION THIS ANSWERS: is CAMARF's backtested edge genuine alpha, or just
beta exposure to known risk factors (market, size, value, and -- for the
5-factor model -- profitability and investment)? Applied POST-HOC to
already-realized daily portfolio returns from a completed backtest run --
no lookahead risk, since nothing here feeds back into a trading decision.

DAILY RETURN SERIES CONSTRUCTION: backtest.py's --capital-sim replay
(portfolio_sim.py::replay_portfolio) computes a genuine equity_curve
internally but does NOT persist it to disk -- only per-trade rows and a
single-row summary get saved (confirmed by reading backtest.py's own
capital_sim block, lines ~1990-2004). Rather than modifying that
already-tested code path, this script reconstructs a daily return series
directly from the trades parquet: realized `actual_pnl` grouped by
`exit_time`'s calendar date, reindexed to a full daily calendar (0 P&L on
days with no exits), cumulative-summed onto `starting_capital` for a daily
equity curve, then converted to daily percentage returns. A defensible,
standard simplification (P&L realized on exit date, not full intraday
mark-to-market) for this diagnostic's purposes.

Reuses Fama-French data exactly as fetched by
research/build_wrds_supplementary_data.py (NOT re-fetched here):
output/cache/wrds/ff_factors_3_daily.parquet / ff_factors_5_daily.parquet.

Synthetic verification FIRST: debug/_verify_fama_french_risk_decomposition.py
-- run that before trusting this script's real-data output.

Usage:
    python research/fama_french_risk_decomposition.py \\
        --trades output/research/step5_arm_results/purity_is_trades_capsim.parquet \\
        --starting-capital 100000 --model 5
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WRDS_CACHE_DIR = os.path.join(_ROOT, "output", "cache", "wrds")
_FF3_PATH = os.path.join(_WRDS_CACHE_DIR, "ff_factors_3_daily.parquet")
_FF5_PATH = os.path.join(_WRDS_CACHE_DIR, "ff_factors_5_daily.parquet")


def build_daily_return_series(trades_df: pd.DataFrame, starting_capital: float) -> pd.Series:
    """Realized daily P&L (grouped by exit_time's calendar date) -> cumulative
    equity on top of starting_capital -> daily percentage returns."""
    if trades_df.empty:
        return pd.Series(dtype=float)
    exit_dates = pd.to_datetime(trades_df["exit_time"]).dt.normalize()
    daily_pnl = trades_df.assign(_exit_date=exit_dates).groupby("_exit_date")["actual_pnl"].sum()
    full_idx = pd.date_range(daily_pnl.index.min(), daily_pnl.index.max(), freq="D")
    daily_pnl = daily_pnl.reindex(full_idx, fill_value=0.0)
    equity = starting_capital + daily_pnl.cumsum()
    prev_equity = equity.shift(1)
    prev_equity.iloc[0] = starting_capital
    returns = (equity - prev_equity) / prev_equity
    return returns


def run_regression(portfolio_returns: pd.Series, factors_df: pd.DataFrame, factor_cols: list) -> dict:
    """OLS: portfolio_return - rf ~ factor_cols. factors_df must have a
    DatetimeIndex and an 'rf' column (WRDS ff.factors_daily/fivefactors_daily
    convention: mktrf/smb/hml/rf, or +rmw/cma for 5-factor -- all already in
    decimal-fraction daily-return units, same scale as portfolio_returns)."""
    joined = pd.DataFrame({"portfolio_return": portfolio_returns}).join(factors_df, how="inner").dropna()
    if len(joined) < 30:
        return {"ok": False, "reason": "insufficient_overlap", "n": len(joined)}

    y = (joined["portfolio_return"] - joined["rf"]).to_numpy()
    x_cols = [joined[c].to_numpy() for c in factor_cols]
    x = np.column_stack([np.ones(len(joined))] + x_cols)
    beta, residuals, rank, sv = np.linalg.lstsq(x, y, rcond=None)

    y_hat = x @ beta
    resid = y - y_hat
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan

    n, k = x.shape
    dof = max(n - k, 1)
    sigma2 = ss_res / dof
    xtx_inv = np.linalg.pinv(x.T @ x)
    se = np.sqrt(np.diag(sigma2 * xtx_inv))
    alpha_daily = float(beta[0])
    alpha_se = float(se[0]) if se[0] > 0 else np.nan
    alpha_t = alpha_daily / alpha_se if alpha_se and np.isfinite(alpha_se) else np.nan

    loadings = {col: float(b) for col, b in zip(factor_cols, beta[1:])}
    return {
        "ok": True, "n": n,
        "alpha_daily": alpha_daily, "alpha_annualized": alpha_daily * 252,
        "alpha_t_stat": alpha_t, "r_squared": r_squared,
        "loadings": loadings,
    }


def main():
    p = argparse.ArgumentParser(description="Fama-French risk decomposition of a backtest's daily returns")
    p.add_argument("--trades", required=True, help="Path to a trades_*_capsim_*.parquet file")
    p.add_argument("--starting-capital", type=float, default=100000.0)
    p.add_argument("--model", choices=["3", "5"], default="5")
    args = p.parse_args()

    trades_df = pd.read_parquet(args.trades)
    returns = build_daily_return_series(trades_df, args.starting_capital)
    print(f"Built {len(returns)}-day return series from {len(trades_df)} trades "
          f"({returns.index.min()} to {returns.index.max()})")

    ff_path = _FF3_PATH if args.model == "3" else _FF5_PATH
    if not os.path.exists(ff_path):
        print(f"ERROR: {ff_path} not found -- run research/build_wrds_supplementary_data.py first.")
        return
    ff = pd.read_parquet(ff_path)
    ff["date"] = pd.to_datetime(ff["date"])
    ff = ff.set_index("date")
    # Verified directly against the cached data (2026-08-11): WRDS's ff
    # library already stores factor values as decimal fractions (e.g.
    # mktrf ~ 0.0006 on a typical day, rf ~ 0.0001/day matching a real
    # ~2-5%/year risk-free rate), NOT percent -- same scale as
    # portfolio_returns already uses, no conversion needed.
    factor_cols = ["mktrf", "smb", "hml"] if args.model == "3" else ["mktrf", "smb", "hml", "rmw", "cma"]

    result = run_regression(returns, ff, factor_cols)
    if not result.get("ok"):
        print(f"Regression not run: {result.get('reason')} (n={result.get('n')})")
        return

    print(f"\n=== Fama-French {args.model}-factor decomposition ({args.trades}) ===")
    print(f"n_days={result['n']}  R²={result['r_squared']:.3f}")
    print(f"Annualized alpha: {result['alpha_annualized']*100:.2f}%  (t-stat={result['alpha_t_stat']:.2f})")
    for factor, loading in result["loadings"].items():
        print(f"  {factor} loading: {loading:.3f}")
    return result


if __name__ == "__main__":
    main()
