"""
Synthetic verification of research/liquidity_threshold_sensitivity.py's
implied_min_adv_from_position_sizes -- the one non-trivial piece of logic
(threshold_pass_rates is a straightforward descriptive sweep, not separately
tested).

Checks:
  1. A known, hand-computed position-size distribution recovers the exact
     expected implied minimum ADV at each percentile (N / participation_rate).
  2. A higher max_participation_rate (more tolerance) implies a LOWER
     minimum ADV requirement for the same position sizes (inverse relationship).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from research.liquidity_threshold_sensitivity import implied_min_adv_from_position_sizes


def main():
    failures = []

    # --- Check 1: exact known values ---
    notionals = pd.Series([10_000.0, 20_000.0, 30_000.0, 40_000.0, 100_000.0])
    result = implied_min_adv_from_position_sizes(notionals, max_participation_rate=0.05)
    expected_median_notional = 30_000.0  # exact median of [10k,20k,30k,40k,100k]
    if abs(result["median_notional"] - expected_median_notional) > 1e-6:
        failures.append(f"Check 1: expected median_notional={expected_median_notional}, "
                         f"got {result['median_notional']}")
    expected_median_adv = expected_median_notional / 0.05
    if abs(result["median_implied_min_adv"] - expected_median_adv) > 1e-6:
        failures.append(f"Check 1: expected median_implied_min_adv={expected_median_adv}, "
                         f"got {result['median_implied_min_adv']}")
    if abs(result["max_notional"] - 100_000.0) > 1e-6:
        failures.append(f"Check 1: expected max_notional=100000, got {result['max_notional']}")

    # --- Check 2: higher participation tolerance -> lower implied ADV requirement ---
    result_tight = implied_min_adv_from_position_sizes(notionals, max_participation_rate=0.01)
    result_loose = implied_min_adv_from_position_sizes(notionals, max_participation_rate=0.10)
    if not (result_loose["median_implied_min_adv"] < result_tight["median_implied_min_adv"]):
        failures.append(f"Check 2: a LOOSER participation rate (0.10) should imply a LOWER "
                         f"minimum ADV requirement than a tighter one (0.01), got "
                         f"loose={result_loose['median_implied_min_adv']} "
                         f"tight={result_tight['median_implied_min_adv']}")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All liquidity threshold sensitivity checks passed.")
    print(f"  Check 1: median_notional={result['median_notional']}, "
          f"median_implied_min_adv={result['median_implied_min_adv']}")
    print(f"  Check 2: tight(1%)={result_tight['median_implied_min_adv']:.0f} > "
          f"loose(10%)={result_loose['median_implied_min_adv']:.0f}")


if __name__ == "__main__":
    main()
