"""
CAMARF strategy_risk_precision.py — comparison/diagnostic method, NOT part
of the production pipeline.

Lopez de Prado (AFML, Ch. 15, "Understanding Strategy Risk") — for a
binary-outcome betting strategy (win probability p = "precision," n bets
per year = "frequency," symmetric win/loss magnitude), the annualized
Sharpe ratio is a deterministic function of precision and frequency alone:

    SR_per_bet = (2p - 1) / (2 * sqrt(p * (1-p)))
    SR_annualized = SR_per_bet * sqrt(n)

This is applied per confirmed pair here, using each pair's own IS win rate
(precision) and trade count/year (frequency) from backtest.py's trade
log, flagging which of the 23 confirmed pairs are "high-precision,
low-frequency" (a small edge-per-bet, few opportunities) vs. "structurally
fragile" (win rate close to 50%, only surviving on frequency) — a per-pair
diagnostic that doesn't currently exist anywhere in the pipeline.

This is the SYMMETRIC special case of AFML's own more general asymmetric-
payout formula (which also takes separate profit-taking/stop-loss
magnitudes) — deliberately using only the symmetric case here since it has
a simple, directly simulation-verifiable closed form (see this module's
own debug/_verify_strategy_risk_precision.py), rather than re-deriving the
more general asymmetric formula from memory without an independent check.

Read-only. Never fetches, never recomputes trades.

Usage:
    python research/strategy_risk_precision.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def binomial_sharpe(precision, frequency_per_year):
    """
    precision: win probability p, in (0,1) exclusive.
    frequency_per_year: expected number of bets per year, n > 0.
    Returns (sharpe_per_bet, sharpe_annualized).
    """
    p = np.clip(precision, 1e-6, 1 - 1e-6)
    sr_per_bet = (2 * p - 1) / (2 * np.sqrt(p * (1 - p)))
    sr_annualized = sr_per_bet * np.sqrt(frequency_per_year)
    return float(sr_per_bet), float(sr_annualized)


def main():
    trades_path = "output/backtest/trades_layer1.parquet"
    if not os.path.exists(trades_path):
        print(f"No trades file at {trades_path} — run backtest.py first.")
        return
    trades = pd.read_parquet(trades_path)
    trades["pair_key"] = trades["symbol_a"] + "/" + trades["symbol_b"]
    trades["exit_time"] = pd.to_datetime(trades["exit_time"])
    trades["entry_time"] = pd.to_datetime(trades["entry_time"])

    rows = []
    for pair_key, grp in trades.groupby("pair_key"):
        n_trades = len(grp)
        if n_trades < 10:
            print(f"SKIP {pair_key}: only {n_trades} trades, too few for a stable precision estimate")
            continue
        precision = float((grp["pnl_net"] > 0).mean())
        span_days = (grp["exit_time"].max() - grp["entry_time"].min()).days
        span_years = max(span_days / 365.25, 1 / 365.25)
        frequency = n_trades / span_years

        sr_per_bet, sr_annualized = binomial_sharpe(precision, frequency)
        rows.append({
            "pair_key": pair_key, "n_trades": n_trades, "precision": precision,
            "frequency_per_year": frequency,
            "sharpe_per_bet": sr_per_bet, "sharpe_annualized_implied": sr_annualized,
        })
        print(f"{pair_key}: n={n_trades} precision={precision:.3f} "
              f"freq/yr={frequency:.1f} implied_annual_SR={sr_annualized:.3f}")

    out_df = pd.DataFrame(rows).sort_values("sharpe_annualized_implied")
    os.makedirs("output/research", exist_ok=True)
    out_df.to_parquet("output/research/strategy_risk_precision.parquet")

    if len(out_df):
        low_precision_high_freq = out_df[out_df["precision"] < 0.55]
        print(f"\nWrote output/research/strategy_risk_precision.parquet: {len(out_df)} pairs")
        print(f"{len(low_precision_high_freq)} pairs have precision < 0.55 (near coin-flip, "
              f"'structurally fragile' — surviving mostly on frequency/timing, not per-bet edge): "
              f"{list(low_precision_high_freq['pair_key'])}")


if __name__ == "__main__":
    main()
