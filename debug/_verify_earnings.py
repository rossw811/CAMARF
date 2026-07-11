"""
Synthetic verification for earnings.py's EarningsCalendar.near_earnings().
No network calls — constructs an EarningsCalendar directly from known
dates and checks the +-window_days blackout logic.

Run: python debug/_verify_earnings.py
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from earnings import EarningsCalendar


def _cal():
    return EarningsCalendar(dates_by_symbol={
        "AMD": [pd.Timestamp("2024-05-01"), pd.Timestamp("2024-08-01")],
        "DD": [],  # no known earnings dates
    })


def case1_within_window():
    cal = _cal()
    result = cal.near_earnings("AMD", pd.Timestamp("2024-05-03"), window_days=3)
    print(f"Case 1 (2 days after earnings, window=3): {result}")
    assert result is True
    print("  PASS")


def case2_outside_window():
    cal = _cal()
    result = cal.near_earnings("AMD", pd.Timestamp("2024-05-10"), window_days=3)
    print(f"Case 2 (9 days after earnings, window=3): {result}")
    assert result is False
    print("  PASS")


def case3_exact_boundary():
    cal = _cal()
    result_in = cal.near_earnings("AMD", pd.Timestamp("2024-05-04"), window_days=3)  # exactly 3 days
    result_out = cal.near_earnings("AMD", pd.Timestamp("2024-05-05"), window_days=3)  # 4 days
    print(f"Case 3 (boundary): +3days={result_in}, +4days={result_out}")
    assert result_in is True
    assert result_out is False
    print("  PASS")


def case4_no_known_earnings_not_blacked_out():
    cal = _cal()
    result = cal.near_earnings("DD", pd.Timestamp("2024-05-01"), window_days=3)
    print(f"Case 4 (symbol with no known earnings dates): {result}")
    assert result is False, "absence of earnings data must not be treated as a blackout"
    print("  PASS")


def case5_unknown_symbol():
    cal = _cal()
    result = cal.near_earnings("ZZZZ", pd.Timestamp("2024-05-01"), window_days=3)
    print(f"Case 5 (symbol never fetched): {result}")
    assert result is False
    print("  PASS")


if __name__ == "__main__":
    case1_within_window()
    case2_outside_window()
    case3_exact_boundary()
    case4_no_known_earnings_not_blacked_out()
    case5_unknown_symbol()
    print("\nAll earnings.py checks passed.")
