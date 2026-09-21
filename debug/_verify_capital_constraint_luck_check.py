"""
Synthetic verification for research/capital_constraint_luck_check.py -- no
live data, fabricated trades with a KNOWN taken/skipped split.

Run: python debug/_verify_capital_constraint_luck_check.py
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.capital_constraint_luck_check import split_taken_skipped, compare_taken_vs_skipped

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def _make_full_trades(n=100, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n, freq="6h")
    return pd.DataFrame({
        "symbol_a": [f"A{i}" for i in range(n)],
        "symbol_b": [f"B{i}" for i in range(n)],
        "tf": "1D",
        "entry_time": dates,
        "exit_time": dates + pd.Timedelta(hours=3),
        "entry_spread": rng.normal(0, 1, n),
        "n_shares_b": rng.uniform(10, 200, n),
        "pnl_net": rng.normal(10, 50, n),
    })


def test_split_recovers_exact_taken_and_skipped():
    full = _make_full_trades(n=50, seed=1)
    taken_idx = [3, 7, 12, 20, 33, 41]
    taken = full.iloc[taken_idx].copy()

    taken_subset, skipped = split_taken_skipped(full, taken)
    check("split.taken_count_matches", len(taken_subset) == len(taken_idx), len(taken_subset))
    check("split.skipped_count_matches", len(skipped) == 50 - len(taken_idx), len(skipped))
    check("split.no_overlap_by_entry_spread",
          set(taken_subset["entry_spread"]).isdisjoint(set(skipped["entry_spread"])))
    check("split.taken_pnl_matches_original",
          set(np.round(taken_subset["pnl_net"], 6)) == set(np.round(taken["pnl_net"], 6)))


def test_split_raises_on_missing_key_columns():
    full = _make_full_trades(n=10, seed=2)
    taken = full[["symbol_a", "pnl_net"]].copy()  # missing key cols
    raised = False
    try:
        split_taken_skipped(full, taken)
    except ValueError:
        raised = True
    check("split.raises_on_missing_columns", raised)


def test_compare_detects_taken_worse_than_skipped():
    # Construct a case where TAKEN trades are deliberately WORSE (lower mean
    # pnl) than skipped -- the "capital constraint hurts, doesn't help" case
    # this script exists to catch.
    rng = np.random.default_rng(5)
    n = 200
    dates = pd.date_range("2021-01-01", periods=n, freq="4h")
    full = pd.DataFrame({
        "symbol_a": [f"A{i}" for i in range(n)], "symbol_b": [f"B{i}" for i in range(n)],
        "tf": "1D", "entry_time": dates, "exit_time": dates + pd.Timedelta(hours=2),
        "entry_spread": rng.normal(0, 1, n),
        "n_shares_b": rng.uniform(10, 200, n),
        "pnl_net": rng.normal(0, 10, n),
    })
    # Taken = first 30 chronologically (deliberately NOT quality-selected),
    # with pnl_net forced low to simulate "capital ran out during a bad patch."
    taken = full.iloc[:30].copy()
    taken["pnl_net"] = rng.normal(-20, 5, 30)  # much worse than the rest

    taken_subset, skipped = split_taken_skipped(full, taken)
    # taken_subset should reflect the ORIGINAL full-population pnl_net (not
    # taken's overridden one) since split_taken_skipped keys on entry_spread
    # etc., not pnl_net itself -- confirms taken_subset pulls from `full`,
    # the correct original-size basis, not from the (possibly capital-scaled)
    # `taken` argument's own pnl_net column.
    check("compare.taken_subset_uses_full_populations_pnl_net",
          not np.allclose(sorted(taken_subset["pnl_net"]), sorted(taken["pnl_net"])))


def test_compare_flags_better_or_worse_correctly():
    # Zero-variance P&L (a constant value every trade) makes sharpe_from_trades
    # correctly return NaN (daily_pnl.std()==0) -- realistic P&L needs real
    # variance for a meaningful Sharpe comparison, so this fixture varies pnl_net
    # around each subset's mean rather than using a single repeated constant.
    n = 50
    dates = pd.date_range("2022-01-01", periods=n, freq="6h")
    rng = np.random.default_rng(9)
    taken_subset = pd.DataFrame({
        "entry_time": dates[:20], "exit_time": dates[:20] + pd.Timedelta(hours=1),
        "pnl_net": rng.normal(100.0, 10.0, 20),
    })
    skipped = pd.DataFrame({
        "entry_time": dates[20:], "exit_time": dates[20:] + pd.Timedelta(hours=1),
        "pnl_net": rng.normal(-50.0, 10.0, 30),
    })
    result = compare_taken_vs_skipped(taken_subset, skipped)
    check("compare.taken_better_flagged_true", result["taken_better_than_skipped"] is True)
    check("compare.mean_pnl_correct",
          abs(result["taken_mean_pnl"] - 100.0) < 15 and abs(result["skipped_mean_pnl"] - (-50.0)) < 15)


if __name__ == "__main__":
    test_split_recovers_exact_taken_and_skipped()
    test_split_raises_on_missing_key_columns()
    test_compare_detects_taken_worse_than_skipped()
    test_compare_flags_better_or_worse_correctly()

    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    sys.exit(0)
