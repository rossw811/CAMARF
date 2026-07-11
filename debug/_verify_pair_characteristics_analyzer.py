"""
Synthetic verification for research/pair_characteristics_analyzer.py's
fit_tree_with_validation(). Tests the core discipline the original spec
requires: a genuine, discoverable characteristic should be found and
survive chronological holdout; pure noise should NOT show permutation
significance; insufficient data should be handled gracefully.

Run: python debug/_verify_pair_characteristics_analyzer.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from pair_characteristics_analyzer import fit_tree_with_validation, _prep_features

np.random.seed(11)


def _synthetic_trades(n, real_effect=False):
    entry_time = pd.date_range("2023-01-01", periods=n, freq="4h")
    entry_z = np.random.uniform(2.0, 4.0, n)
    half_life = np.random.uniform(10, 60, n)
    hurst = np.random.uniform(0.2, 0.5, n)
    regime = np.random.choice(["calm", "elevated"], n)
    side = np.random.choice(["long", "short"], n)

    if real_effect:
        # Genuine, discoverable rule: high |z| entries win far more often
        # (this is a real, stable pattern, not noise — should survive
        # BOTH the permutation test and chronological holdout).
        p_win = np.where(entry_z > 3.0, 0.85, 0.35)
    else:
        p_win = np.full(n, 0.5)  # pure coin-flip, no real structure
    pnl_net = np.where(np.random.uniform(0, 1, n) < p_win, 100.0, -80.0)

    df = pd.DataFrame({
        "entry_time": entry_time, "entry_z": entry_z * np.random.choice([-1, 1], n),
        "half_life_at_entry": half_life, "hurst_at_entry": hurst,
        "vix_ts_regime": regime, "yield_regime": "normal", "side": side,
        "pnl_net": pnl_net,
    })
    return _prep_features(df)


def case1_real_effect_survives_holdout():
    df = _synthetic_trades(300, real_effect=True)
    result = fit_tree_with_validation(df)
    print(f"Case 1 (real effect, n=300): permutation_significant={result['permutation_significant']}, "
          f"n_confirmed_leaves={result['n_confirmed_leaves']}, "
          f"best_leaf_winrate={result['best_leaf']['train_winrate']:.2f}" if result.get("best_leaf") else "no confirmed leaf")
    assert result["ok"]
    assert result["permutation_significant"] is True, "a genuine, stable effect must beat the permutation null"
    assert result["n_confirmed_leaves"] >= 1, "a genuine effect must survive chronological holdout"
    assert result["best_leaf"]["train_winrate"] > 0.6, "the discovered rule should show the real high win rate"
    print("  PASS: genuine characteristic correctly discovered and holdout-confirmed")


def case2_pure_noise_not_significant():
    df = _synthetic_trades(300, real_effect=False)
    result = fit_tree_with_validation(df)
    print(f"Case 2 (pure noise, n=300): permutation_significant={result['permutation_significant']}, "
          f"n_confirmed_leaves={result['n_confirmed_leaves']}")
    assert result["ok"]
    assert result["permutation_significant"] is False, (
        "pure coin-flip outcomes must NOT beat the permutation null — a positive here would mean "
        "the validation discipline itself is broken (false-positive characteristic discovery)"
    )
    print("  PASS: pure noise correctly fails to beat the permutation null")


def case3_insufficient_trades():
    df = _synthetic_trades(15, real_effect=True)
    result = fit_tree_with_validation(df)
    print(f"Case 3 (n=15, below MIN_TRADES_PER_PAIR): ok={result['ok']}, reason={result.get('reason')}")
    assert result["ok"] is False
    assert result["reason"] == "insufficient_trades"
    print("  PASS: correctly refuses to analyze a pair with too few trades")


if __name__ == "__main__":
    case1_real_effect_survives_holdout()
    case2_pure_noise_not_significant()
    case3_insufficient_trades()
    print("\nAll pair_characteristics_analyzer checks passed.")
