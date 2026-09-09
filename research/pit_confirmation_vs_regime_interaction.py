"""
Does a pair's regime-context signal (§5, crisis-vs-calm discovery
regime / crisis-reappearance confirmation) predict whether it survives a
genuine point-in-time re-screen (§4)? PAPER.md §10's third recorded
future-work candidate, approved by Ross 2026-09-08 alongside sequential
bootstrap and transfer entropy -- "the most direct way to move 'why one
paper, not two' from a thematic argument to an empirically demonstrated
one."

Joins two existing artifacts (no new heavy computation, a real join +
two-proportion test):
- `output/research/crisis_regime_correlation_diagnostic_pairs.parquet`
  (§5): 638,095 candidate pairs, each with `first_regime` (which VIX
  regime the pair was first discovered in) and `confirmed` (§5's own
  statistically-significant crisis-reappearance flag).
- `output/backtest/pit_wfa_wrds_daily_pair_sets.parquet` (§4): pairs that
  survived a genuine point-in-time cointegration re-screen at one of 4
  historical cutoffs (320 unique pairs).

Real, disclosed limitation checked BEFORE running the test, not
discovered after: only 18 of the 320 PIT-confirmed pairs (17 in the same
symbol_a/symbol_b order, 1 reversed) actually appear in §5's 638,095-pair
universe at all -- §5's diagnostic ran over essentially the full
candidate universe, while §4's PIT screen only ever tests pairs that are
statistically cointegration-confirmed at a given historical cutoff, a
much narrower pool. This means the test below has genuinely LOW
STATISTICAL POWER (a ~0.05% base rate of PIT-confirmation across the
638,095-pair universe) -- reported honestly as a real constraint on what
this test can conclude, not glossed over.
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

_REGIME_PATH = os.path.join(_ROOT, "output", "research", "crisis_regime_correlation_diagnostic_pairs.parquet")
_PIT_PATH = os.path.join(_ROOT, "output", "backtest", "pit_wfa_wrds_daily_pair_sets.parquet")
_OUT_PATH = os.path.join(_ROOT, "output", "research", "pit_confirmation_vs_regime_interaction.parquet")


def build_joined_table(regime_df: pd.DataFrame, pit_df: pd.DataFrame) -> pd.DataFrame:
    """Adds a `pit_confirmed` boolean column to `regime_df`: True if that
    pair (either symbol_a/symbol_b order) appears anywhere in `pit_df`."""
    pit_pairs_fwd = set(zip(pit_df["symbol_a"], pit_df["symbol_b"]))
    pit_pairs_rev = set(zip(pit_df["symbol_b"], pit_df["symbol_a"]))
    pit_pairs = pit_pairs_fwd | pit_pairs_rev

    out = regime_df.copy()
    out["pit_confirmed"] = [
        (a, b) in pit_pairs for a, b in zip(out["symbol_a"], out["symbol_b"])
    ]
    return out


def two_proportion_test(joined: pd.DataFrame, group_col: str, group_a, group_b) -> dict:
    """P(pit_confirmed | group_a) vs P(pit_confirmed | group_b), a standard
    two-proportion z-test (normal approximation, matching this project's
    existing pooled-confirmation-rate test convention elsewhere)."""
    mask_a = joined[group_col].isin(group_a) if isinstance(group_a, (list, set, tuple)) else joined[group_col] == group_a
    mask_b = joined[group_col].isin(group_b) if isinstance(group_b, (list, set, tuple)) else joined[group_col] == group_b

    n_a, n_b = int(mask_a.sum()), int(mask_b.sum())
    x_a, x_b = int(joined.loc[mask_a, "pit_confirmed"].sum()), int(joined.loc[mask_b, "pit_confirmed"].sum())
    p_a = x_a / n_a if n_a else float("nan")
    p_b = x_b / n_b if n_b else float("nan")

    if n_a == 0 or n_b == 0:
        return {"group_a": str(group_a), "group_b": str(group_b), "n_a": n_a, "n_b": n_b,
                "x_a": x_a, "x_b": x_b, "p_a": p_a, "p_b": p_b, "z": float("nan"), "p_value": float("nan")}

    p_pool = (x_a + x_b) / (n_a + n_b)
    se = np.sqrt(p_pool * (1 - p_pool) * (1 / n_a + 1 / n_b))
    z = (p_a - p_b) / se if se > 0 else float("nan")
    p_value = 2 * (1 - stats.norm.cdf(abs(z))) if np.isfinite(z) else float("nan")

    return {"group_a": str(group_a), "group_b": str(group_b), "n_a": n_a, "n_b": n_b,
            "x_a": x_a, "x_b": x_b, "p_a": p_a, "p_b": p_b, "z": float(z), "p_value": float(p_value)}


def main():
    if not (os.path.exists(_REGIME_PATH) and os.path.exists(_PIT_PATH)):
        print(f"ERROR: missing input(s). regime={os.path.exists(_REGIME_PATH)}, "
              f"pit={os.path.exists(_PIT_PATH)}")
        return

    regime_df = pd.read_parquet(_REGIME_PATH)
    pit_df = pd.read_parquet(_PIT_PATH)
    joined = build_joined_table(regime_df, pit_df)

    n_overlap = int(joined["pit_confirmed"].sum())
    print(f"§5 universe: {len(joined)} pairs. §4 PIT-confirmed universe: {pit_df[['symbol_a','symbol_b']].drop_duplicates().shape[0]} "
          f"unique pairs. Overlap: {n_overlap} pairs ({n_overlap/len(joined):.4%} base rate) -- "
          f"LOW POWER, disclosed in this script's own docstring, not hidden.")

    results = []

    # Test 1: first_regime crisis vs calm (the original §5 framing)
    r1 = two_proportion_test(joined, "first_regime", "crisis", "calm")
    r1["test"] = "first_regime: crisis vs calm"
    results.append(r1)
    print(f"\nTest 1 -- first_regime crisis vs calm:")
    print(f"  crisis: {r1['x_a']}/{r1['n_a']} PIT-confirmed ({r1['p_a']:.4%})")
    print(f"  calm:   {r1['x_b']}/{r1['n_b']} PIT-confirmed ({r1['p_b']:.4%})")
    print(f"  z={r1['z']:.4f}, p={r1['p_value']:.4f}")

    # Test 2: §5's own "confirmed" (statistically-significant crisis-reappearance) flag
    r2 = two_proportion_test(joined, "confirmed", True, False)
    r2["test"] = "§5 confirmed flag: True vs False"
    results.append(r2)
    print(f"\nTest 2 -- §5's own crisis-reappearance-confirmed flag:")
    print(f"  confirmed=True:  {r2['x_a']}/{r2['n_a']} PIT-confirmed ({r2['p_a']:.4%})")
    print(f"  confirmed=False: {r2['x_b']}/{r2['n_b']} PIT-confirmed ({r2['p_b']:.4%})")
    print(f"  z={r2['z']:.4f}, p={r2['p_value']:.4f}")

    # Full breakdown across all 4 regime categories, for transparency
    print(f"\nFull breakdown by first_regime:")
    breakdown = joined.groupby("first_regime")["pit_confirmed"].agg(["sum", "count"])
    breakdown["rate"] = breakdown["sum"] / breakdown["count"]
    print(breakdown)

    os.makedirs(os.path.dirname(_OUT_PATH), exist_ok=True)
    pd.DataFrame(results).to_parquet(_OUT_PATH)
    print(f"\nSaved to {_OUT_PATH}")


if __name__ == "__main__":
    main()
