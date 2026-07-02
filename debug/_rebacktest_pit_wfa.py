"""
One-off recovery: re-runs ONLY the backtest step of pit_wfa.py's already-
completed run, reusing the point-in-time confirmed pair sets already saved
in output/backtest/pit_wfa_pair_sets.parquet, after fixing
backtest_pair_on_test_window's calendar-padding bug (missing
drop_data_gap_rows=True on the isolated 2-symbol alignment call — same bug
class as research/decoupling_backtest.py earlier this session). Screening
(the expensive ~90-min step, and NOT affected by this bug) is not re-run —
only the fast backtest step, which was affected.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from pit_wfa import (
    load_universe_1h, determine_analysis_window, compute_fold_dates,
    backtest_pair_on_test_window, FOLD_EXPANDING, FOLD_ROLLING,
)
from backtest import aggregate_portfolio

_OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "backtest")


def main():
    pair_sets = pd.read_parquet(os.path.join(_OUT_DIR, "pit_wfa_pair_sets.parquet"))
    universe = load_universe_1h()
    print(f"Universe: {len(universe)} symbols")
    start, end = determine_analysis_window(universe)
    print(f"Analysis window: [{start.date()}, {end.date()}]")

    fold_lookup = {}
    for variant, fold_specs in [("expanding", FOLD_EXPANDING), ("rolling", FOLD_ROLLING)]:
        for spec in fold_specs:
            fd = compute_fold_dates(start, end, spec)
            fold_lookup[(variant, fd["label"])] = fd

    portfolio_rows = []
    for (variant, fold), group in pair_sets.groupby(["wfa_variant", "fold"]):
        fold_dates = fold_lookup[(variant, fold)]
        all_trades, all_metrics = [], []
        for _, row in group.iterrows():
            pr = SimpleNamespace(symbol_a=row["symbol_a"], symbol_b=row["symbol_b"])
            trades, metrics = backtest_pair_on_test_window(
                pr, universe, fold_dates["train_start"], fold_dates["test_start"], fold_dates["test_end"]
            )
            if trades:
                all_trades.extend(trades)
                if metrics:
                    all_metrics.append(metrics)
        portfolio_stats = aggregate_portfolio(all_trades, all_metrics)
        portfolio_stats.update({
            "wfa_variant": variant, "fold": fold,
            "n_pit_confirmed_pairs": len(group), "n_pairs_with_trades": len(all_metrics),
        })
        print(f"[{variant}/{fold}] {len(all_metrics)} pairs traded, {len(all_trades)} trades, "
              f"Sharpe={portfolio_stats.get('sharpe_portfolio', float('nan')):.4f}")
        portfolio_rows.append(portfolio_stats)

    result = pd.DataFrame(portfolio_rows)
    print("\n" + result.to_string(index=False))
    result.to_parquet(os.path.join(_OUT_DIR, "pit_wfa_portfolio_FIXED.parquet"), index=False)
    print(f"\nSaved -> output/backtest/pit_wfa_portfolio_FIXED.parquet")


if __name__ == "__main__":
    main()
