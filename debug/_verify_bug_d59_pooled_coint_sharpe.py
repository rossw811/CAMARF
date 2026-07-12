"""
Verifies the BUG-D59 fix in distance.py (2026-07-12): the cointegration-vs-distance-method
portfolio comparison must use POOLED daily P&L across all pairs, not an unweighted mean of
per-pair Sharpes.

Real-data motivation (Development.md, 2026-07-12): the OLD `coint_port_sharpe` (mean of 21
per-pair Sharpes) came out to 20.435 -- traced directly to one thinly-traded pair (LNT/WELL,
6 days of holdout P&L) showing a Sharpe of 114 purely from small-sample variance, dominating the
unweighted mean. The pooled statistic on the SAME real data came out to 8.542 -- genuinely
comparable to the distance method's own pooled Sharpe (7.865), instead of an apples-to-oranges
20 vs 7.9 comparison.

This test reproduces that exact failure mode synthetically: one pair with few trades and a
lucky run (extreme per-pair Sharpe), several pairs with realistic trade counts and modest
Sharpes. Confirms:
  1. The OLD unweighted-mean statistic is dominated by the lucky thin pair (matches the bug).
  2. The NEW pooled statistic is close to the realistic pairs' true portfolio-level Sharpe,
     not distorted by the thin pair's noise.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from backtest import Trade
from distance import _portfolio_sharpe_from_dollar_trades

RNG = np.random.default_rng(3)


def make_trades(symbol_a, symbol_b, n, daily_mean, daily_std, start="2026-01-01"):
    """n trades, one per day, each day's pnl_net drawn from N(daily_mean, daily_std)."""
    dates = pd.bdate_range(start, periods=n)
    trades = []
    for d in dates:
        pnl = RNG.normal(daily_mean, daily_std)
        trades.append(Trade(
            tf="1h", symbol_a=symbol_a, symbol_b=symbol_b, hedge_method="ols", hedge_ratio=1.0,
            entry_time=d, entry_z=2.0, entry_spread=0.0, side="short",
            n_shares_a=100, n_shares_b=100.0, half_life_at_entry=20.0, hurst_at_entry=0.4,
            exit_time=d, pnl_net=pnl,
        ))
    return trades


def main():
    failures = []

    # Realistic pairs: modest, believable daily Sharpe (~1-2 annualized-equivalent), decent N.
    realistic_trades = []
    for i in range(5):
        realistic_trades += make_trades(f"SYM{i}A", f"SYM{i}B", n=40, daily_mean=5.0, daily_std=50.0)

    # One thin, "lucky" pair: only 6 days, all small positive P&L with tiny variance --
    # exactly the LNT/WELL pattern (6 days, Sharpe=114).
    lucky_trades = make_trades("LUCKY_A", "LUCKY_B", n=6, daily_mean=20.0, daily_std=2.0)

    # OLD (buggy) statistic: unweighted mean of per-pair Sharpes.
    def per_pair_sharpe(trades):
        return _portfolio_sharpe_from_dollar_trades(trades)

    per_pair_sharpes = [per_pair_sharpe(realistic_trades[i * 40:(i + 1) * 40]) for i in range(5)]
    lucky_sharpe = per_pair_sharpe(lucky_trades)
    old_mean_sharpe = float(np.mean(per_pair_sharpes + [lucky_sharpe]))

    # NEW (fixed) statistic: pool everything, one Sharpe.
    all_trades = realistic_trades + lucky_trades
    new_pooled_sharpe = _portfolio_sharpe_from_dollar_trades(all_trades)

    realistic_only_pooled = _portfolio_sharpe_from_dollar_trades(realistic_trades)

    print(f"Per-pair Sharpes (5 realistic): {[round(s, 2) for s in per_pair_sharpes]}")
    print(f"Lucky thin-pair Sharpe (6 days): {lucky_sharpe:.2f}")
    print(f"OLD unweighted mean (bug): {old_mean_sharpe:.2f}")
    print(f"NEW pooled Sharpe (fix): {new_pooled_sharpe:.2f}")
    print(f"Realistic-pairs-only pooled Sharpe (reference, no lucky pair): {realistic_only_pooled:.2f}")

    if not (lucky_sharpe > 3 * max(per_pair_sharpes)):
        failures.append("fixture didn't reproduce the small-sample blowup -- lucky pair's Sharpe "
                         "should be far higher than any realistic pair's, adjust fixture")

    if not (old_mean_sharpe > 1.5 * new_pooled_sharpe):
        failures.append(f"OLD statistic should be substantially inflated by the lucky pair "
                         f"relative to NEW: old={old_mean_sharpe:.2f} new={new_pooled_sharpe:.2f}")

    if not np.isclose(new_pooled_sharpe, realistic_only_pooled, rtol=0.5):
        failures.append(f"NEW pooled Sharpe with the lucky pair included ({new_pooled_sharpe:.2f}) "
                         f"should stay reasonably close to the realistic-only reference "
                         f"({realistic_only_pooled:.2f}) -- pooling should dilute, not eliminate, "
                         f"a small pair's influence, proportional to its trade count")

    print()
    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("BUG-D59 fix verified: pooled portfolio Sharpe is not dominated by a thinly-traded "
          "lucky pair the way the old unweighted per-pair mean was.")


if __name__ == "__main__":
    main()
