"""
Synthetic verification for analysis.py's AnalysisPipeline._predict_degeneracy_risk()
(Ross's "Option A" gate, 2026-07-11: cap+sector prediction for visibility/
prioritization only, never for exclusion). Checks the exact validated
threshold boundaries from research/price_degeneracy_root_cause.py.

Run: python debug/_verify_predicted_degeneracy_risk.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import AnalysisPipeline

_predict = AnalysisPipeline._predict_degeneracy_risk


def case1_high_risk_small_cap():
    r = _predict(1.0e9, "Technology")  # well below $3.28B, even non-target sector
    print(f"Case 1 ($1.0B, Technology): {r}")
    assert r == "high"
    print("  PASS")


def case2_medium_q2_any_sector():
    r = _predict(5.0e9, "Technology")  # between $3.28B and $6.43B
    print(f"Case 2 ($5.0B, Technology): {r}")
    assert r == "medium"
    print("  PASS")


def case3_medium_q3_target_sector():
    r = _predict(10.0e9, "Real Estate")  # Q3 band, REIT
    print(f"Case 3 ($10.0B, Real Estate): {r}")
    assert r == "medium"
    print("  PASS")


def case4_low_q3_other_sector():
    r = _predict(10.0e9, "Technology")  # same cap band, non-target sector
    print(f"Case 4 ($10.0B, Technology): {r}")
    assert r == "low"
    print("  PASS: same cap band as Case 3, different sector -> different risk "
          "(confirms sector is applied, not just cap)")


def case5_low_large_cap():
    r = _predict(50.0e9, "Real Estate")  # large cap, even target sector
    print(f"Case 5 ($50.0B, Real Estate): {r}")
    assert r == "low"
    print("  PASS")


def case6_missing_market_cap():
    r = _predict(None, "Real Estate")
    r2 = _predict(np.nan, "Real Estate")
    print(f"Case 6 (missing market cap): None->{r}, NaN->{r2}")
    assert r is None and r2 is None, "missing data must return None, not a fabricated 'low'"
    print("  PASS: missing data correctly returns None, not a false low-risk reading")


def case7_boundary_exact():
    # Exactly at the Q1/Q2 boundary should NOT be "high" (< is strict).
    r = _predict(3.28e9, "Technology")
    print(f"Case 7 (exactly $3.28B boundary): {r}")
    assert r == "medium", "exactly at the boundary should fall into the next tier, not high"
    print("  PASS")


if __name__ == "__main__":
    case1_high_risk_small_cap()
    case2_medium_q2_any_sector()
    case3_medium_q3_target_sector()
    case4_low_q3_other_sector()
    case5_low_large_cap()
    case6_missing_market_cap()
    case7_boundary_exact()
    print("\nAll predicted_degeneracy_risk checks passed.")
