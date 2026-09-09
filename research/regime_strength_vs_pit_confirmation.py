"""
§4's regime-strength segmentation vs. PIT-confirmation precision -- Tier A
item #7 of the 2026-09-08 caveat/limitation search. "Does a pair's
regime strength (strong/moderate/weak, §7.2) predict whether it survives
a genuine point-in-time re-screen?" -- PAPER_MAGNITUDE.md §10's own
wording, never previously asked of the data.

Reuses pit_confirmation_vs_regime_interaction.py's exact join machinery
(build_joined_table, two_proportion_test) unchanged -- only the input
table and the predictor column differ (regime_strength_vs_discovery_
regime.parquet's `strength` column instead of the crisis-regime
diagnostic's `first_regime`).
"""
import os
import sys

import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "research"))

from pit_confirmation_vs_regime_interaction import build_joined_table, two_proportion_test

_STRENGTH_PATH = os.path.join(_ROOT, "output", "research", "regime_strength_vs_discovery_regime.parquet")
_PIT_PATH = os.path.join(_ROOT, "output", "backtest", "pit_wfa_wrds_daily_pair_sets.parquet")
_OUT_PATH = os.path.join(_ROOT, "output", "research", "regime_strength_vs_pit_confirmation.parquet")


def main():
    if not (os.path.exists(_STRENGTH_PATH) and os.path.exists(_PIT_PATH)):
        print("ERROR: missing input(s).")
        return

    strength_df = pd.read_parquet(_STRENGTH_PATH)
    pit_df = pd.read_parquet(_PIT_PATH)

    joined = build_joined_table(strength_df, pit_df)
    n_overlap = int(joined["pit_confirmed"].sum())
    print(f"Regime-strength universe: {len(joined)} pairs. PIT-confirmed universe: "
          f"{pit_df[['symbol_a','symbol_b']].drop_duplicates().shape[0]} unique pairs. "
          f"Overlap: {n_overlap} pairs ({n_overlap/len(joined):.4%} base rate).")

    print(f"\nBreakdown by strength:")
    breakdown = joined.groupby("strength")["pit_confirmed"].agg(["sum", "count"])
    breakdown["rate"] = breakdown["sum"] / breakdown["count"]
    print(breakdown)

    results = []
    strengths = sorted(joined["strength"].dropna().unique())
    if "strong" in strengths and "weak" in strengths:
        r = two_proportion_test(joined, "strength", "strong", "weak")
        r["test"] = "strength: strong vs weak"
        results.append(r)
        print(f"\nstrong vs weak: {r['x_a']}/{r['n_a']} ({r['p_a']:.4%}) vs "
              f"{r['x_b']}/{r['n_b']} ({r['p_b']:.4%}), z={r['z']:.4f}, p={r['p_value']:.4f}")

    if results:
        pd.DataFrame(results).to_parquet(_OUT_PATH)
        print(f"\nSaved to {_OUT_PATH}")


if __name__ == "__main__":
    main()
