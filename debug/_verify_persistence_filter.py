"""
Synthetic verification for pit_wfa.py's run_persistence_fold() intersection
logic (2026-07-14, Ross's request to test whether requiring a pair to
survive two consecutive point-in-time screens would have avoided
checkpoint 1's -1.9037 Sharpe). Mocks screen_universe_at_cutoff to return
two controlled, overlapping PairResult lists and confirms only the true
intersection survives, keyed on (symbol_a, symbol_b) regardless of any
other field differing between the two screens (as expected, since the two
screens fit on different train windows and should have different scalar
values for the same pair).
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pit_wfa
from analysis import PairResult


def _make(sym_a, sym_b, coint_frac):
    return PairResult(
        symbol_a=sym_a, symbol_b=sym_b, asset_class_a="equity", asset_class_b="equity",
        tf_label="1hr", is_cross_asset=False, pearson_corr=0.8,
        coint_pvalue_raw=0.01, coint_pvalue_adjusted=0.02, coint_fraction_rolling=coint_frac,
        hedge_ratio_ols=1.0, hedge_ratio_tls=1.0, hedge_ratio_kalman_mean=1.0,
        half_life_rolling=20.0, half_life_expanding=20.0, mean_reversion_speed=0.05,
        half_life_trend_slope=-0.1, zivot_andrews_break=None, cusum_first_excursion=None,
        hurst_rs=0.4, hurst_dfa=0.4, hurst_divergence=0.0, passes_ml_gate=True,
        hurst_interpretation="mean_reverting", eigenport_pvalue=0.02, passes_eigenportfolio=True,
        n_factors_removed=1, confidence_tier="silver", n_bars=500, n_overlap=500,
        source_a="yfinance", source_b="yfinance",
    )


earlier_set = [_make("A", "B", 0.10), _make("C", "D", 0.20), _make("E", "F", 0.15)]
now_set = [_make("A", "B", 0.30), _make("C", "D", 0.05), _make("G", "H", 0.40)]
# Expected intersection: only (A,B) and (C,D) appear in both; (E,F) drops
# out (not re-confirmed), (G,H) drops out (newly confirmed, not persistent).

call_log = []


def fake_screen(universe, train_start, train_end, n_workers):
    call_log.append(train_end)
    return now_set if len(call_log) == 2 else earlier_set


import pandas as pd

fold_dates = {
    "label": "test", "train_start": pd.Timestamp("2023-01-01"),
    "train_end": pd.Timestamp("2024-01-01"),
    "test_start": pd.Timestamp("2024-01-01"), "test_end": pd.Timestamp("2024-06-01"),
}

with patch.object(pit_wfa, "screen_universe_at_cutoff", side_effect=fake_screen), \
     patch.object(pit_wfa, "backtest_pair_on_test_window", return_value=([], {})):
    metrics, portfolio_stats, pair_sets = pit_wfa.run_persistence_fold(
        {}, fold_dates, "persistence_sweep", n_workers=1, lookback_days=90
    )

kept_keys = {(r["symbol_a"], r["symbol_b"]) for r in pair_sets}
expected_keys = {("A", "B"), ("C", "D")}

print(f"kept pairs: {kept_keys}")
print(f"expected:   {expected_keys}")
print(f"n_pre_filter_pairs (should be 3, len(now_set)): {portfolio_stats['n_pre_filter_pairs']}")
print(f"n_pit_confirmed_pairs (should be 2, the intersection): {portfolio_stats['n_pit_confirmed_pairs']}")

# Confirm the earlier-cutoff call used train_end - 90 days, not train_end itself.
assert call_log[0] == fold_dates["train_end"] - pd.Timedelta(days=90), \
    f"earlier screen should use train_end-90d, got {call_log[0]}"
assert call_log[1] == fold_dates["train_end"], "second screen should use the real train_end"

ok = (
    kept_keys == expected_keys
    and portfolio_stats["n_pre_filter_pairs"] == 3
    and portfolio_stats["n_pit_confirmed_pairs"] == 2
)
print("\nPASS" if ok else "\nFAIL")
sys.exit(0 if ok else 1)
