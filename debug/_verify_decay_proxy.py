"""
Synthetic verification of compute_pair_decay_zscore() (decay_proxy.py),
BEFORE trusting it on real trade data.

Checks:
  1. Fewer than MIN_TRADES total trades -> returns None (insufficient data,
     not a forced/noisy computation).
  2. Stable performance throughout (recent window drawn from the SAME
     distribution as history) -> z-score near 0, not flagged.
  3. Recent window clearly underperforming (much higher-variance, near-zero-
     mean P&L in the most recent trades vs. consistently profitable history)
     -> z-score strongly negative, flagged.
  4. Recent window clearly OUTPERFORMING -> z-score positive, NOT flagged
     (this is a one-sided decay flag, not a general "different" flag).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from decay_proxy import compute_pair_decay_zscore

rng = np.random.default_rng(5)


def main():
    failures = []

    # --- 1. Insufficient trades ---
    pnls = rng.normal(loc=10, scale=5, size=20)  # below _MIN_TRADES=40
    result = compute_pair_decay_zscore(pnls)
    if result is not None:
        failures.append(f"Case 1 (insufficient trades): expected None, got {result}")

    # --- 2. Stable performance throughout ---
    pnls = rng.normal(loc=10, scale=5, size=200)  # same distribution end to end
    result = compute_pair_decay_zscore(pnls)
    if result is None:
        failures.append("Case 2 (stable): expected a result, got None")
    elif abs(result["z_score"]) > 2.5:
        failures.append(f"Case 2 (stable): expected |z| roughly small, got z={result['z_score']:.2f}")
    elif result["flagged"]:
        failures.append(f"Case 2 (stable): should not be flagged, got flagged=True (z={result['z_score']:.2f})")

    # --- 3. Recent window clearly decaying ---
    historical = rng.normal(loc=20, scale=5, size=180)
    recent = rng.normal(loc=-5, scale=15, size=20)  # much worse, noisier
    pnls = np.concatenate([historical, recent])
    result = compute_pair_decay_zscore(pnls)
    if result is None:
        failures.append("Case 3 (decaying): expected a result, got None")
    elif not result["flagged"]:
        failures.append(f"Case 3 (decaying): expected flagged=True, got z={result['z_score']:.2f}")

    # --- 4. Recent window clearly outperforming (should NOT flag) ---
    historical = rng.normal(loc=5, scale=5, size=180)
    recent = rng.normal(loc=40, scale=5, size=20)  # much better recently
    pnls = np.concatenate([historical, recent])
    result = compute_pair_decay_zscore(pnls)
    if result is None:
        failures.append("Case 4 (outperforming): expected a result, got None")
    elif result["flagged"]:
        failures.append(f"Case 4 (outperforming): should NOT be flagged (one-sided decay "
                         f"flag), got flagged=True (z={result['z_score']:.2f})")
    elif result["z_score"] <= 0:
        failures.append(f"Case 4 (outperforming): expected positive z-score, got {result['z_score']:.2f}")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All compute_pair_decay_zscore checks passed.")


if __name__ == "__main__":
    main()
