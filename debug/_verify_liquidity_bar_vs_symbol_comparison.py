"""
Synthetic verification of research/liquidity_bar_vs_symbol_comparison.py::
compare_bar_vs_symbol -- run BEFORE trusting it against real international
price data.

Checks:
  1. A symbol whose FLAT AVERAGE dollar volume is above threshold, but where
     a real fraction of individual bars fall below it, is correctly flagged:
     symbol_level_pass=True but bar_level_pass_rate < 1.0 (the "hidden
     illiquid days" case).
  2. A symbol whose flat average is BELOW threshold, but which has a real
     fraction of individually liquid bars, is correctly flagged the other
     way: symbol_level_pass=False but bar_level_pass_rate > 0 (the "days
     being thrown away" case).
  3. A uniformly liquid symbol (every bar comfortably above threshold)
     shows symbol_level_pass=True AND bar_level_pass_rate=1.0 (full
     agreement case, sanity check that nothing is broken for the simple case).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from research.liquidity_bar_vs_symbol_comparison import compare_bar_vs_symbol
from data_wrds import _OUT_DIR

_TEST_LABEL = "TESTSYM_VERIFY"
_TEST_PATH = os.path.join(_OUT_DIR, f"{_TEST_LABEL}_1D.parquet")


def _write_test_file(closes, volumes):
    idx = pd.date_range("2023-01-01", periods=len(closes), freq="D")
    df = pd.DataFrame({"open": closes, "high": closes, "low": closes,
                        "close": closes, "volume": volumes}, index=idx)
    os.makedirs(_OUT_DIR, exist_ok=True)
    df.to_parquet(_TEST_PATH)


def main():
    failures = []
    threshold = 1_000_000.0
    usd_mult = 1.0  # trivial currency, USD already

    try:
        # --- Check 1: hidden illiquid days (average passes, some bars don't) ---
        # 100 bars: 80 bars with dollar_vol=2M (comfortably liquid), 20 bars with dollar_vol=100k
        # (illiquid). Average = (80*2M + 20*100k)/100 = 1.62M > threshold, but 20% of bars fail.
        closes1 = [10.0] * 100
        volumes1 = [200_000] * 80 + [10_000] * 20  # dollar_vol = close*volume
        _write_test_file(closes1, volumes1)
        r1 = compare_bar_vs_symbol(_TEST_LABEL, "USD", usd_mult, threshold, trailing_days=100)
        if not r1["symbol_level_pass"]:
            failures.append(f"Check 1: expected symbol_level_pass=True (avg={r1['symbol_level_avg_usd']}), "
                             f"got False")
        if abs(r1["bar_level_pass_rate"] - 0.80) > 1e-6:
            failures.append(f"Check 1: expected bar_level_pass_rate=0.80, got {r1['bar_level_pass_rate']}")

        # --- Check 2: days thrown away (average fails, some bars are liquid) ---
        # 100 bars: 30 bars with dollar_vol=3M (liquid), 70 bars with dollar_vol=200k (illiquid).
        # Average = (30*3M + 70*200k)/100 = 1.04M -- just above! Need average clearly BELOW.
        # Use 20 liquid bars, 80 illiquid: avg = (20*3M + 80*200k)/100 = 760k < threshold.
        closes2 = [10.0] * 100
        volumes2 = [300_000] * 20 + [20_000] * 80
        _write_test_file(closes2, volumes2)
        r2 = compare_bar_vs_symbol(_TEST_LABEL, "USD", usd_mult, threshold, trailing_days=100)
        if r2["symbol_level_pass"]:
            failures.append(f"Check 2: expected symbol_level_pass=False (avg={r2['symbol_level_avg_usd']}), "
                             f"got True")
        if abs(r2["bar_level_pass_rate"] - 0.20) > 1e-6:
            failures.append(f"Check 2: expected bar_level_pass_rate=0.20, got {r2['bar_level_pass_rate']}")

        # --- Check 3: full agreement (uniformly liquid) ---
        closes3 = [10.0] * 100
        volumes3 = [500_000] * 100  # dollar_vol = 5M every bar, comfortably above threshold
        _write_test_file(closes3, volumes3)
        r3 = compare_bar_vs_symbol(_TEST_LABEL, "USD", usd_mult, threshold, trailing_days=100)
        if not r3["symbol_level_pass"] or abs(r3["bar_level_pass_rate"] - 1.0) > 1e-6:
            failures.append(f"Check 3: expected full agreement (pass=True, rate=1.0), got "
                             f"pass={r3['symbol_level_pass']}, rate={r3['bar_level_pass_rate']}")
    finally:
        if os.path.exists(_TEST_PATH):
            os.remove(_TEST_PATH)

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All bar-vs-symbol liquidity comparison checks passed.")
    print(f"  Check 1 (hidden illiquid days): symbol_pass={r1['symbol_level_pass']}, "
          f"bar_rate={r1['bar_level_pass_rate']:.2f}")
    print(f"  Check 2 (days thrown away): symbol_pass={r2['symbol_level_pass']}, "
          f"bar_rate={r2['bar_level_pass_rate']:.2f}")
    print(f"  Check 3 (full agreement): symbol_pass={r3['symbol_level_pass']}, "
          f"bar_rate={r3['bar_level_pass_rate']:.2f}")


if __name__ == "__main__":
    main()
