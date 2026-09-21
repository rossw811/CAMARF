"""
research/squeeze_momentum_signal_validation.py -- validates that the 3
squeeze/momentum STORM gates (2026-09-15) are doing something real, not just
benefiting from sample-size variance.

MOTIVATION: each gate shrinks the unconstrained Purity trade set substantially
(158,963 -> 41,627/95,485/25,851 for squeeze/momentum/combined) and shows a
markedly better unconstrained Sharpe than the ungated baseline. A smaller
random subsample of ANY large noisy trade population will, by chance, show
higher SHARPE VARIANCE than the full population purely from having fewer
observations -- some random subsamples of the same size would look better
than the full population even with no real selection effect at all. This
script tests the gates against the correct null: for each gate, draw many
random subsamples of the SAME SIZE from the full ungated Purity trade set
(no cherry-picking which trades, just matching N) and compare the gate's
REAL Sharpe against that null distribution. If the gate's Sharpe is a clear
outlier relative to random same-size draws, the gate is selecting something
real, not just shrinking the sample.

Uses portfolio_math.sharpe_from_trades throughout -- the exact same function
backtest.py's aggregate_portfolio() computation is built on -- so every
number here is directly comparable to the real backtest.py runs' own
sharpe_portfolio values, not a separately-reinvented metric.

Usage:
    python research/squeeze_momentum_signal_validation.py \\
        --full-trades output/backtest/purity_trades_layer1_storm.parquet \\
        --gate-trades output/backtest/sqzgate_trades_layer1_storm.parquet \\
        --gate-name squeeze_gate \\
        --n-draws 2000
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from portfolio_math import sharpe_from_trades


def random_subsample_null(full_trades: pd.DataFrame, n_sample: int, n_draws: int,
                           seed: int = 0) -> np.ndarray:
    """Draws n_draws random subsamples of size n_sample (without replacement,
    each draw independent -- i.e. sampling WITH replacement ACROSS draws) from
    full_trades, returns an array of their Sharpe ratios."""
    rng = np.random.default_rng(seed)
    n_total = len(full_trades)
    if n_sample > n_total:
        raise ValueError(f"n_sample ({n_sample}) > n_total ({n_total})")
    sharpes = np.empty(n_draws)
    idx_array = full_trades.index.values
    for i in range(n_draws):
        draw_idx = rng.choice(n_total, size=n_sample, replace=False)
        sub = full_trades.iloc[draw_idx]
        sharpes[i] = sharpe_from_trades(sub)
    return sharpes


def validate_gate(full_trades: pd.DataFrame, gate_trades: pd.DataFrame, gate_name: str,
                   n_draws: int, seed: int = 0) -> dict:
    n_sample = len(gate_trades)
    real_sharpe = sharpe_from_trades(gate_trades)
    null_sharpes = random_subsample_null(full_trades, n_sample, n_draws, seed=seed)
    null_sharpes = null_sharpes[np.isfinite(null_sharpes)]
    n_valid = len(null_sharpes)
    percentile = float((null_sharpes < real_sharpe).mean() * 100) if n_valid else float("nan")
    p_value_one_tailed = float((null_sharpes >= real_sharpe).mean()) if n_valid else float("nan")
    return {
        "gate_name": gate_name,
        "n_sample": n_sample,
        "n_total": len(full_trades),
        "real_sharpe": real_sharpe,
        "null_mean": float(np.mean(null_sharpes)) if n_valid else float("nan"),
        "null_std": float(np.std(null_sharpes)) if n_valid else float("nan"),
        "null_p5": float(np.percentile(null_sharpes, 5)) if n_valid else float("nan"),
        "null_p95": float(np.percentile(null_sharpes, 95)) if n_valid else float("nan"),
        "percentile_of_real_in_null": percentile,
        "p_value_one_tailed": p_value_one_tailed,
        "n_draws_valid": n_valid,
        "n_draws_requested": n_draws,
    }


def main():
    p = argparse.ArgumentParser(description="Random-subsample control test for squeeze/momentum gates")
    p.add_argument("--full-trades", required=True)
    p.add_argument("--gate-trades", required=True)
    p.add_argument("--gate-name", required=True)
    p.add_argument("--n-draws", type=int, default=2000)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    full_trades = pd.read_parquet(args.full_trades)
    gate_trades = pd.read_parquet(args.gate_trades)

    result = validate_gate(full_trades, gate_trades, args.gate_name, args.n_draws, args.seed)

    print(f"=== Random-subsample control: {result['gate_name']} ===")
    print(f"  Gate trade count: {result['n_sample']} / {result['n_total']} total")
    print(f"  Real gate Sharpe: {result['real_sharpe']:.4f}")
    print(f"  Null (random same-size draws, n={result['n_draws_valid']} valid of "
          f"{result['n_draws_requested']}): mean={result['null_mean']:.4f} "
          f"std={result['null_std']:.4f} [5th,95th]=[{result['null_p5']:.4f}, "
          f"{result['null_p95']:.4f}]")
    print(f"  Real Sharpe is at the {result['percentile_of_real_in_null']:.1f}th percentile "
          f"of the null distribution")
    print(f"  One-tailed p-value (P(null >= real)): {result['p_value_one_tailed']:.4f}")


if __name__ == "__main__":
    main()
