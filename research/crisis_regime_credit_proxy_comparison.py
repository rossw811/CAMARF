"""
Tier B item #9 of the 2026-09-08 caveat/limitation search: does §5's
regime-conditional confirmation pattern hold under a DIFFERENT regime
classifier (BAA10Y credit-spread proxy) instead of VIX alone? The paper's
own §10 named this explicitly: "test whether §5's regime-conditional
confirmation/persistence pattern holds under a different regime proxy
(credit spreads, realized-volatility regime) rather than VIX alone —
would strengthen the claim beyond a single macro indicator."

Cheap to build, not a re-run of the expensive part: `crisis_regime_
correlation_diagnostic.py`'s `build_pair_level_table(windows_df,
regime_lookup, alpha)` already takes the regime lookup as a plain
argument -- the expensive step (loading the Tier 3 windows table) is
unchanged, only the regime classifier passed in differs. Reuses `macro.
build()`'s existing `credit_regime_proxy` column (BAA10Y-based,
`_classify_credit_proxy`, three buckets: tight/normal/wide -- a DIFFERENT
taxonomy than VIX's four buckets, not directly comparable value-for-value,
per that function's own docstring) instead of reinventing a classifier.
"""
import os
import sys

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "research"))

import macro
from crisis_regime_correlation_diagnostic import load_tier3_windows, build_pair_level_table
from pit_confirmation_vs_regime_interaction import two_proportion_test

_OUT_PATH = os.path.join(_ROOT, "output", "research", "crisis_regime_credit_proxy_comparison.parquet")


def build_credit_regime_lookup() -> pd.Series:
    result = macro.build(series=["BAA10Y"])
    if "credit_regime_proxy" not in result.data.columns:
        raise RuntimeError("macro.build() did not produce credit_regime_proxy -- "
                            "BAA10Y fetch/classification failed, cannot proceed.")
    return result.data["credit_regime_proxy"]


def main():
    print("Loading the ALREADY-COMPUTED Tier 3 windows table (the expensive step, unchanged)...")
    windows_df = load_tier3_windows()
    print(f"  {len(windows_df)} windows loaded")

    print("Building the BAA10Y credit-spread regime lookup (macro.build, already-established "
          "classifier, not reinvented)...")
    credit_regime = build_credit_regime_lookup()
    print(f"  {credit_regime.notna().sum()} classified trading days, "
          f"buckets: {sorted(credit_regime.dropna().unique())}")

    print("Rebuilding the pair-level table with the credit-spread regime instead of VIX "
          "(cheap -- only the regime label per pair changes, not the underlying window data)...")
    pair_table = build_pair_level_table(windows_df, credit_regime, alpha=0.05)
    pair_table = pair_table.rename(columns={"first_regime": "first_credit_regime"})

    print(f"\nBreakdown by credit regime:")
    breakdown = pair_table.groupby("first_credit_regime")["confirmed"].agg(["sum", "count"])
    breakdown["rate"] = breakdown["sum"] / breakdown["count"]
    print(breakdown)

    results = []
    regimes = sorted(pair_table["first_credit_regime"].dropna().unique())
    if "wide" in regimes and "tight" in regimes:
        r = two_proportion_test(
            pair_table.assign(pit_confirmed=pair_table["confirmed"]),
            "first_credit_regime", "wide", "tight",
        )
        r["test"] = "credit regime: wide (stress) vs tight (calm)"
        results.append(r)
        print(f"\nwide (credit stress) vs tight (calm): {r['x_a']}/{r['n_a']} ({r['p_a']:.4%}) vs "
              f"{r['x_b']}/{r['n_b']} ({r['p_b']:.4%}), z={r['z']:.4f}, p={r['p_value']:.4f}")
        print(f"\nComparison point: §5's original VIX-based crisis-vs-calm gap was "
              f"0.248% vs 0.146% (z=2.77, p=0.0056) -- same direction test, different regime "
              f"classifier.")

    if results:
        pd.DataFrame(results).to_parquet(_OUT_PATH)
        print(f"\nSaved to {_OUT_PATH}")


if __name__ == "__main__":
    main()
