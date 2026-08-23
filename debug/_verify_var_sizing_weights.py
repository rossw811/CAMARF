"""Synthetic verification for backtest.py::compute_var_sizing_weights() -- Thread N #1,
the VaR-based position-sizing sub-arm Finding #35 (docs/FINDINGS.md) flagged as unblocked.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from backtest import compute_var_sizing_weights


def _trades(rows):
    """rows: list of (symbol_a, symbol_b, pnl_net)."""
    return pd.DataFrame(rows, columns=["symbol_a", "symbol_b", "pnl_net"])


def check_1_higher_tail_risk_gets_smaller_multiplier():
    rng = np.random.default_rng(0)
    quiet = [("AAA", "BBB", float(x)) for x in rng.normal(0, 10, 30)]
    volatile = [("CCC", "DDD", float(x)) for x in rng.normal(0, 100, 30)]
    w = compute_var_sizing_weights(trades_df=_trades(quiet + volatile), min_obs=20)
    assert w["AAA/BBB"] > w["CCC/DDD"], "quiet pair should get a LARGER multiplier than volatile"
    print("PASS: check_1_higher_tail_risk_gets_smaller_multiplier")


def check_2_thin_pairs_excluded_not_degenerate():
    rng = np.random.default_rng(1)
    enough = [("AAA", "BBB", float(x)) for x in rng.normal(0, 10, 25)]
    thin = [("EEE", "FFF", float(x)) for x in rng.normal(0, 10, 5)]
    w = compute_var_sizing_weights(trades_df=_trades(enough + thin), min_obs=20)
    assert "AAA/BBB" in w and "EEE/FFF" not in w, "thin pair must be excluded, not weighted"
    print("PASS: check_2_thin_pairs_excluded_not_degenerate")


def check_3_all_pairs_thin_returns_empty_not_crash():
    rows = [("AAA", "BBB", 1.0), ("AAA", "BBB", 2.0)]
    w = compute_var_sizing_weights(trades_df=_trades(rows), min_obs=20)
    assert w == {}, "all-pairs-too-thin must return empty dict, not raise or fabricate a weight"
    print("PASS: check_3_all_pairs_thin_returns_empty_not_crash")


def check_4_clipped_to_expected_range():
    rng = np.random.default_rng(2)
    tiny = [("AAA", "BBB", float(x)) for x in rng.normal(0, 0.001, 30)]
    huge = [("CCC", "DDD", float(x)) for x in rng.normal(0, 10000, 30)]
    w = compute_var_sizing_weights(trades_df=_trades(tiny + huge), min_obs=20)
    assert all(0.1 <= v <= 5.0 for v in w.values()), f"weights out of clip range: {w}"
    print("PASS: check_4_clipped_to_expected_range")


def check_5_empty_trades_returns_empty():
    w = compute_var_sizing_weights(trades_df=pd.DataFrame(columns=["symbol_a", "symbol_b", "pnl_net"]))
    assert w == {}
    print("PASS: check_5_empty_trades_returns_empty")


if __name__ == "__main__":
    check_1_higher_tail_risk_gets_smaller_multiplier()
    check_2_thin_pairs_excluded_not_degenerate()
    check_3_all_pairs_thin_returns_empty_not_crash()
    check_4_clipped_to_expected_range()
    check_5_empty_trades_returns_empty()
    print("\nALL 5 CHECKS PASSED")
