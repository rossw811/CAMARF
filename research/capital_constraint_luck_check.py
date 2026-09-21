"""
research/capital_constraint_luck_check.py -- tests whether a `--capital-sim`
run's TAKEN trade subset is a meaningfully different (better/worse)
population than what got SKIPPED for lack of capital, or than a random
same-size draw from the full unconstrained pool -- i.e. whether the
capital-constrained headline Sharpe reflects the strategy's real edge or is
mostly a function of WHICH trades happened to fit the budget.

Motivation (Ross, 2026-09-21, after the capital-size sweep showed a noisy,
non-monotonic relationship between account size and headline Sharpe): "we
need to add a system similar to DSR to penalize for lucky trades, if our
system just doesn't have enough money to trade we should set up a system
for penalizing maybe by factoring in trades which would've happened had we
had more money."

Two complementary checks, both real, both reported:

1. TAKEN vs SKIPPED comparison: the skipped set is recovered as the set
   difference between the gate's FULL unconstrained trade population and
   the capital_sim's own taken-trades file (anti-join on symbol_a/symbol_b/
   tf/entry_time/exit_time/entry_spread -- unique per real trade). If
   skipped trades look just as good as taken ones (similar or better mean
   P&L / per-period Sharpe), that's direct evidence the capital constraint
   is discarding good trades arbitrarily, not filtering toward better ones
   -- the capital-constrained result doesn't reflect a quality-based
   selection at all.

2. Random-subsample control (reuses research/squeeze_momentum_signal_
   validation.py's exact null-distribution machinery): draws many random
   same-size subsamples from the full unconstrained population and reports
   where the REAL taken-trade Sharpe falls. If it's not an outlier relative
   to random same-size draws, the capital-constrained Sharpe is
   statistically indistinguishable from "whichever 400-ish trades happened
   to fit the budget," independent of any real quality signal.

Usage:
    python research/capital_constraint_luck_check.py \\
        --full-trades output/backtest/momgate_trades_layer1_storm.parquet \\
        --taken-trades output/backtest/momgate_trades_layer1_storm_capsim_fixed_100000.parquet \\
        --n-draws 2000
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from portfolio_math import sharpe_from_trades
from research.squeeze_momentum_signal_validation import random_subsample_null

_KEY_COLS = ["symbol_a", "symbol_b", "tf", "entry_time", "exit_time", "entry_spread", "n_shares_b"]
# n_shares_b (not hedge_method -- absent from the taken-trades file) is required: the same
# pair/entry/exit window produces TWO distinct rows in full_trades, one per hedge_method
# (ols vs kalman), sharing an IDENTICAL entry_spread to full float precision but a different
# hedge_ratio -> different n_shares_b. Without it the anti-join silently double-matches both
# hedge-method siblings for ~93% of trades (confirmed empirically 2026-09-21: 89,178/95,485
# rows collide on the 6-col key; 0 collide once n_shares_b is added). This is what caused the
# "matched 632/415" warning -- not a data-integrity problem with the input files themselves.


def split_taken_skipped(full_trades: pd.DataFrame, taken_trades: pd.DataFrame) -> tuple:
    """Returns (taken_subset_of_full, skipped) -- both as rows of `full_trades`
    (so both carry the SAME original-size pnl_net basis, an apples-to-apples
    comparison; `taken_trades`'s own capital-scaled actual_pnl is a different,
    smaller-notional basis and would not be comparable to skipped trades'
    un-scaled pnl_net)."""
    missing = set(_KEY_COLS) - set(full_trades.columns)
    if missing:
        raise ValueError(f"full_trades missing key columns: {missing}")
    missing = set(_KEY_COLS) - set(taken_trades.columns)
    if missing:
        raise ValueError(f"taken_trades missing key columns: {missing}")

    full_keyed = full_trades.copy()
    full_keyed["_key"] = list(zip(*[full_keyed[c] for c in _KEY_COLS]))
    taken_keys = set(zip(*[taken_trades[c] for c in _KEY_COLS]))

    taken_mask = full_keyed["_key"].isin(taken_keys)
    taken_subset = full_keyed[taken_mask].drop(columns=["_key"])
    skipped = full_keyed[~taken_mask].drop(columns=["_key"])
    return taken_subset, skipped


def compare_taken_vs_skipped(taken_subset: pd.DataFrame, skipped: pd.DataFrame) -> dict:
    taken_sharpe = sharpe_from_trades(taken_subset)
    skipped_sharpe = sharpe_from_trades(skipped)
    taken_mean_pnl = float(taken_subset["pnl_net"].mean()) if len(taken_subset) else float("nan")
    skipped_mean_pnl = float(skipped["pnl_net"].mean()) if len(skipped) else float("nan")
    return {
        "n_taken": len(taken_subset), "n_skipped": len(skipped),
        "taken_sharpe_original_size": taken_sharpe,
        "skipped_sharpe_original_size": skipped_sharpe,
        "taken_mean_pnl": taken_mean_pnl, "skipped_mean_pnl": skipped_mean_pnl,
        "taken_better_than_skipped": (
            None if not (np.isfinite(taken_sharpe) and np.isfinite(skipped_sharpe))
            else bool(taken_sharpe > skipped_sharpe)
        ),
    }


def main():
    p = argparse.ArgumentParser(description="Capital-constraint luck check: taken vs skipped, random-subsample control")
    p.add_argument("--full-trades", required=True,
                    help="The GATE's own full unconstrained trades file (NOT the ungated baseline)")
    p.add_argument("--taken-trades", required=True, help="The capital_sim's own taken-trades output file")
    p.add_argument("--n-draws", type=int, default=2000)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    full_trades = pd.read_parquet(args.full_trades)
    taken_trades = pd.read_parquet(args.taken_trades)

    taken_subset, skipped = split_taken_skipped(full_trades, taken_trades)
    if len(taken_subset) != len(taken_trades):
        print(f"WARNING: matched {len(taken_subset)}/{len(taken_trades)} taken trades against "
              f"the full population -- some taken trades were not found (key mismatch?). "
              f"Results below only cover the matched subset.")

    print("=== 1. Taken vs skipped comparison ===")
    cmp_result = compare_taken_vs_skipped(taken_subset, skipped)
    for k, v in cmp_result.items():
        print(f"  {k}: {v}")
    if cmp_result["taken_better_than_skipped"] is False:
        print("  ==> SKIPPED trades look at least as good as TAKEN trades -- the capital "
              "constraint is NOT preferentially keeping better trades.")
    elif cmp_result["taken_better_than_skipped"] is True:
        print("  ==> TAKEN trades look better than SKIPPED -- consistent with (not proof of) "
              "the capital constraint preferentially admitting better trades.")

    print("\n=== 2. Random-subsample control (taken subset vs random same-size draws) ===")
    n_sample = len(taken_subset)
    real_sharpe = cmp_result["taken_sharpe_original_size"]
    null_sharpes = random_subsample_null(full_trades, n_sample, args.n_draws, seed=args.seed)
    null_sharpes = null_sharpes[np.isfinite(null_sharpes)]
    n_valid = len(null_sharpes)
    percentile = float((null_sharpes < real_sharpe).mean() * 100) if n_valid else float("nan")
    p_value = float((null_sharpes >= real_sharpe).mean()) if n_valid else float("nan")
    print(f"  Taken-subset Sharpe (original size): {real_sharpe:.4f}")
    print(f"  Null (n={n_valid} random same-size draws from full unconstrained pool): "
          f"mean={np.mean(null_sharpes):.4f} std={np.std(null_sharpes):.4f}")
    print(f"  Real Sharpe is at the {percentile:.1f}th percentile of the null distribution")
    print(f"  One-tailed p-value (P(null >= real)): {p_value:.4f}")
    if percentile < 90:
        print("  ==> NOT a clear outlier vs random same-size draws -- the capital-constrained "
              "result is not statistically distinguishable from 'whichever trades happened to "
              "fit the budget.'")
    else:
        print("  ==> A real outlier vs random same-size draws -- the capital-constrained result "
              "reflects more than just which trades fit the budget.")


if __name__ == "__main__":
    main()
