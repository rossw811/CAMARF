"""
Synthetic verification of backtest.py's compute_pit_confidence_weights()
(Thread A Step 4, C:\\Users\\RossW\\.claude\\plans\\ancient-mixing-feather.md)
BEFORE trusting it on the real Tiered comparison-arm pairs file.

Checks:
  1. Known tiers map to the documented multipliers exactly
     (full_episodic=1.0, partial_episodic=0.6, full_history_only=0.3).
  2. Keys are "{symbol_a}/{symbol_b}" (the same convention
     compute_risk_parity_weights/compute_hub_weights already use).
  3. An unrecognized tier value falls back to 1.0, not a crash or a
     silently-dropped row.
  4. None input (no --pairs-override) returns {} (flat sizing), not a
     crash.
  5. A pairs_df missing pit_confidence_tier entirely (e.g. the Purity or
     Hybrid arm's own file, or the standard pairs.parquet) returns {}, the
     same "explicit empty, not a silent fallback" discipline as
     research/pit_pair_discovery.py.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from backtest import compute_pit_confidence_weights


def main():
    failures = []

    # --- 1 & 2: known tiers map correctly, key convention matches ---
    df = pd.DataFrame([
        {"symbol_a": "AAA", "symbol_b": "BBB", "tf_label": "1D", "pit_confidence_tier": "full_episodic"},
        {"symbol_a": "CCC", "symbol_b": "DDD", "tf_label": "1D", "pit_confidence_tier": "partial_episodic"},
        {"symbol_a": "EEE", "symbol_b": "FFF", "tf_label": "1D", "pit_confidence_tier": "full_history_only"},
    ])
    weights = compute_pit_confidence_weights(df)
    expected = {"AAA/BBB": 1.0, "CCC/DDD": 0.6, "EEE/FFF": 0.3}
    if weights != expected:
        failures.append(f"Tier mapping mismatch: got {weights}, expected {expected}")

    # --- 3: unrecognized tier falls back to 1.0, not dropped/crashed ---
    df_unknown = pd.DataFrame([
        {"symbol_a": "GGG", "symbol_b": "HHH", "tf_label": "1D", "pit_confidence_tier": "some_new_tier"},
    ])
    weights_unknown = compute_pit_confidence_weights(df_unknown)
    if weights_unknown.get("GGG/HHH") != 1.0:
        failures.append(f"Unrecognized tier should fall back to 1.0, got {weights_unknown}")

    # --- 4: None input -> {} ---
    weights_none = compute_pit_confidence_weights(None)
    if weights_none != {}:
        failures.append(f"None input should return {{}}, got {weights_none}")

    # --- 5: missing pit_confidence_tier column -> {} ---
    df_no_tier = pd.DataFrame([
        {"symbol_a": "III", "symbol_b": "JJJ", "tf_label": "1D"},
    ])
    weights_no_tier = compute_pit_confidence_weights(df_no_tier)
    if weights_no_tier != {}:
        failures.append(f"Missing pit_confidence_tier column should return {{}}, got {weights_no_tier}")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All compute_pit_confidence_weights() checks passed.")
    print(f"  tier mapping: {weights}")
    print(f"  unknown-tier fallback: {weights_unknown}")
    print(f"  None input: {weights_none}")
    print(f"  missing-column input: {weights_no_tier}")


if __name__ == "__main__":
    main()
