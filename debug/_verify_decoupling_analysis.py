"""
Synthetic verification of classify_decoupling_event() (research/
decoupling_analysis.py), BEFORE trusting it on real spread data. Constructs
one synthetic spread array per classification case with a known, designed-in
pattern and confirms the function recovers the correct label.

Checks:
  1. CONTINUED_DIVERGENCE: pre-break flat, post-break linearly trending away.
  2. REVERTED_TO_OLD_EQUILIBRIUM: pre-break flat, post-break jumps then decays
     back toward the pre-break mean.
  3. NEW_EQUILIBRIUM_SHIFT: pre-break flat at one level, post-break flat at a
     clearly different level (no trend, but a real shift).
  4. INCONCLUSIVE: insufficient post-break history (below _MIN_POST_BARS).
  5. INCONCLUSIVE: post-break is pure noise around the SAME pre-break mean
     (no trend, no shift) — a "break" that didn't actually change anything.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from research.decoupling_analysis import classify_decoupling_event

rng = np.random.default_rng(11)


def main():
    failures = []
    pre_window, min_post = 60, 20

    # --- 1. Continued divergence ---
    pre = 10.0 + rng.normal(scale=0.2, size=pre_window)
    post = 10.0 + np.linspace(0, 8.0, 100) + rng.normal(scale=0.2, size=100)
    spread = np.concatenate([pre, post])
    result = classify_decoupling_event(spread, pre_window)
    if result["classification"] != "CONTINUED_DIVERGENCE":
        failures.append(f"Case 1 (continued divergence): expected CONTINUED_DIVERGENCE, got {result['classification']}")

    # --- 2. Reverted to old equilibrium ---
    pre = 10.0 + rng.normal(scale=0.2, size=pre_window)
    decay = 6.0 * np.exp(-np.linspace(0, 4, 100))  # jumps to +6, decays back to ~0
    post = 10.0 + decay + rng.normal(scale=0.2, size=100)
    spread = np.concatenate([pre, post])
    result = classify_decoupling_event(spread, pre_window)
    if result["classification"] != "REVERTED_TO_OLD_EQUILIBRIUM":
        failures.append(f"Case 2 (reverted to old equilibrium): expected REVERTED_TO_OLD_EQUILIBRIUM, got {result['classification']}")

    # --- 3. New equilibrium shift ---
    pre = 10.0 + rng.normal(scale=0.2, size=pre_window)
    post = 15.0 + rng.normal(scale=0.2, size=100)  # flat at a new, clearly different level
    spread = np.concatenate([pre, post])
    result = classify_decoupling_event(spread, pre_window)
    if result["classification"] != "NEW_EQUILIBRIUM_SHIFT":
        failures.append(f"Case 3 (new equilibrium shift): expected NEW_EQUILIBRIUM_SHIFT, got {result['classification']}")

    # --- 4. Insufficient post-break history ---
    pre = 10.0 + rng.normal(scale=0.2, size=pre_window)
    post = 15.0 + rng.normal(scale=0.2, size=5)  # only 5 post-break bars, below min_post
    spread = np.concatenate([pre, post])
    result = classify_decoupling_event(spread, pre_window)
    if result["classification"] != "INCONCLUSIVE":
        failures.append(f"Case 4 (insufficient history): expected INCONCLUSIVE, got {result['classification']}")

    # --- 5. No real break (noise around the same pre-break mean) ---
    pre = 10.0 + rng.normal(scale=0.2, size=pre_window)
    post = 10.0 + rng.normal(scale=0.2, size=100)  # same mean, same noise level
    spread = np.concatenate([pre, post])
    result = classify_decoupling_event(spread, pre_window)
    if result["classification"] != "INCONCLUSIVE":
        failures.append(f"Case 5 (no real break): expected INCONCLUSIVE, got {result['classification']}")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All classify_decoupling_event checks passed.")


if __name__ == "__main__":
    main()
