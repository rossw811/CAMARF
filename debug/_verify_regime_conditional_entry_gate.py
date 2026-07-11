"""
Synthetic verification for research/regime_conditional_entry_gate.py's
classify_regime(). Tests the rule-based bucketing logic directly against
known-answer cases from the original spec's own worked example.

Run: python debug/_verify_regime_conditional_entry_gate.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from regime_conditional_entry_gate import classify_regime


def case1_good_regime():
    # Mean-reverting (H<0.45), spread not widening (vel<=0), calm macro
    result = classify_regime(hurst_at_entry=0.30, spread_vel_at_entry=-0.5, vix_regime="calm")
    print(f"Case 1 (mean-reverting + consolidating + calm): {result}")
    assert result == "good"
    print("  PASS")


def case2_bad_regime():
    # Trending (H>0.55), spread widening (vel>0) — per spec's own example:
    # "one leg trending + spread widening -> do not enter"
    result = classify_regime(hurst_at_entry=0.70, spread_vel_at_entry=1.2, vix_regime="elevated")
    print(f"Case 2 (trending + widening): {result}")
    assert result == "bad"
    print("  PASS")


def case3_neutral_regime():
    # Mean-reverting but macro NOT calm -> doesn't meet full "good" bar
    result = classify_regime(hurst_at_entry=0.30, spread_vel_at_entry=-0.5, vix_regime="elevated")
    print(f"Case 3 (mean-reverting but macro not calm): {result}")
    assert result == "neutral"
    print("  PASS")


def case4_missing_data():
    result = classify_regime(hurst_at_entry=np.nan, spread_vel_at_entry=0.1, vix_regime="calm")
    print(f"Case 4 (missing hurst): {result}")
    assert result == "unknown"
    print("  PASS")


if __name__ == "__main__":
    case1_good_regime()
    case2_bad_regime()
    case3_neutral_regime()
    case4_missing_data()
    print("\nAll regime_conditional_entry_gate checks passed.")
