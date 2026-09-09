"""Synthetic proof for research/price_target_pairs_overlay.py -- confirms
the causal/staleness-gated target lookup, the relative-divergence sign
convention, and the long/short agreement logic against known cases."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

import price_target_pairs_overlay as pto

n_checks = 0
n_passed = 0


def check(name, cond):
    global n_checks, n_passed
    n_checks += 1
    status = "PASS" if cond else "FAIL"
    if cond:
        n_passed += 1
    print(f"[{status}] {name}")


# --- 1. build_target_series: correct PIT ordering, indexed by statpers ---
ibes_df = pd.DataFrame([
    {"permno": 1, "statpers": pd.Timestamp("2020-01-01"), "mean_price_target": 100.0},
    {"permno": 1, "statpers": pd.Timestamp("2020-04-01"), "mean_price_target": 110.0},
    {"permno": 2, "statpers": pd.Timestamp("2020-01-01"), "mean_price_target": 50.0},
])
series1 = pto.build_target_series(1, ibes_df)
check("build_target_series returns 2 rows for permno=1", len(series1) == 2)
check("build_target_series values match the real target rows",
      list(series1.values) == [100.0, 110.0])

series_missing = pto.build_target_series(999, ibes_df)
check("build_target_series returns empty series for a permno with no rows", series_missing.empty)

# --- 2. implied_return_to_target: causal lookup, correct formula, staleness gate ---
permno_map = {"AAA": 1, "BBB": 2}
price_cache = {"AAA": pd.Series([100.0], index=[pd.Timestamp("2020-02-01")])}

# Entry AFTER the Jan-1 target, BEFORE the Apr-1 target -> should use the Jan-1 target (100.0),
# price is 100.0 -> implied return = (100-100)/100 = 0.0
r = pto.implied_return_to_target("AAA", pd.Timestamp("2020-02-01"), permno_map, ibes_df, price_cache)
check("implied_return_to_target uses the LAST target at-or-before entry_time, not a future one",
      np.isclose(r, 0.0))

# Entry AFTER the Apr-1 target -> should use 110.0, price still 100 in this synthetic cache ->
# implied return = (110-100)/100 = 0.10
price_cache2 = {"AAA": pd.Series([100.0], index=[pd.Timestamp("2020-05-01")])}
r2 = pto.implied_return_to_target("AAA", pd.Timestamp("2020-05-01"), permno_map, ibes_df, price_cache2)
check("implied_return_to_target picks up a LATER target once entry_time has passed it",
      np.isclose(r2, 0.10))

# Entry far in the future (> staleness window past the last real target) -> NaN, not extrapolated
price_cache3 = {"AAA": pd.Series([100.0], index=[pd.Timestamp("2021-06-01")])}
r3 = pto.implied_return_to_target("AAA", pd.Timestamp("2021-06-01"), permno_map, ibes_df, price_cache3)
check("implied_return_to_target returns NaN when the last known target is stale "
      f"(> {pto._MAX_TARGET_STALENESS_DAYS} days old), not silently extrapolated",
      r3 != r3)  # NaN != NaN

# Unknown symbol -> NaN, not a crash
r4 = pto.implied_return_to_target("ZZZZZ", pd.Timestamp("2020-02-01"), permno_map, ibes_df, price_cache)
check("unknown symbol (no permno mapping) returns NaN without crashing", r4 != r4)

# --- 3. compute_overlay: agreement sign convention, long vs short ---
trades = pd.DataFrame([
    # long trade, A has higher implied return than B -> analysts agree with "long A/short B"
    {"symbol_a": "AAA", "symbol_b": "BBB", "entry_time": pd.Timestamp("2020-02-01"),
     "side": "long", "pnl_net": 10.0},
    # short trade, same underlying divergence (A > B) -> analysts DISAGREE with "short A/long B"
    {"symbol_a": "AAA", "symbol_b": "BBB", "entry_time": pd.Timestamp("2020-02-01"),
     "side": "short", "pnl_net": -5.0},
])
# Rig implied_return_to_target's inputs so AAA has clearly higher implied return than BBB.
permno_map2 = {"AAA": 1, "BBB": 2}
ibes_df2 = pd.DataFrame([
    {"permno": 1, "statpers": pd.Timestamp("2020-01-01"), "mean_price_target": 120.0},  # AAA: +20%
    {"permno": 2, "statpers": pd.Timestamp("2020-01-01"), "mean_price_target": 102.0},  # BBB: +2%
])

class _FakeSeries:
    pass

import unittest.mock as mock
with mock.patch.object(pto.options, "load_price_series") as mock_load:
    def fake_load(sym):
        return pd.Series([100.0], index=[pd.Timestamp("2020-02-01")])
    mock_load.side_effect = fake_load
    overlay = pto.compute_overlay(trades, permno_map2, ibes_df2)

print(overlay[["side", "relative_divergence", "agrees_with_consensus"]])
check("long trade with A's implied return > B's is flagged AGREES with consensus",
      bool(overlay.loc[overlay["side"] == "long", "agrees_with_consensus"].iloc[0]))
check("short trade with the SAME underlying divergence is flagged DISAGREES with consensus "
      "(same relative_divergence sign, opposite trade direction)",
      not bool(overlay.loc[overlay["side"] == "short", "agrees_with_consensus"].iloc[0]))
check("relative_divergence is positive and identical for both trades (same legs, same entry_time)",
      np.isclose(overlay["relative_divergence"].iloc[0], overlay["relative_divergence"].iloc[1])
      and overlay["relative_divergence"].iloc[0] > 0)

# --- 4. Real bug caught live: agrees_with_consensus is object-dtype (True/False/None) --
# `~` on that column does Python bitwise NOT (~True == -2), not boolean negation, and
# selecting scored[~scored["agrees_with_consensus"]] crashes with a KeyError trying to
# select columns [-2, -1, ...]. Casting to bool first (main()'s fix) must actually work.
scored_check = overlay[overlay["agrees_with_consensus"].notna()].copy()
scored_check["agrees_with_consensus"] = scored_check["agrees_with_consensus"].astype(bool)
try:
    disagree_check = scored_check[~scored_check["agrees_with_consensus"]]
    negation_correct = (disagree_check["agrees_with_consensus"] == False).all() and len(disagree_check) == 1
except KeyError:
    disagree_check = None
    negation_correct = False
check("~ on the bool-cast agrees_with_consensus column negates correctly, no KeyError, "
      "and selects exactly the False row", negation_correct)

print(f"\n{n_passed}/{n_checks} checks passed")
sys.exit(0 if n_passed == n_checks else 1)
